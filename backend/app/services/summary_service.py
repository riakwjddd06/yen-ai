"""요약 계산과 캐시.

Firestore 무료 한도(하루 읽기 5만 건)를 아끼기 위해 3단계로 캐시한다.
1) 서버 메모리  2) Firestore meta/summary 문서(서버가 잠들었다 깨어나도 유지)  3) 둘 다 없으면 전체 계산
데이터가 바뀌면(POST/PUT/DELETE) invalidate()로 1)과 2)를 지운다.
"""
import json
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.core.errors import NotFoundError
from app.core.firebase import get_db
from app.services import analysis, data_service

CALENDAR_PATH = Path(__file__).resolve().parents[2] / "data" / "travel_calendar.json"
TOP_PERIODS = 5  # 프롬프트 길이를 위해 변동폭 상위 5개만
SUMMARY_VERSION = 2  # 요약 모양이 바뀌면 올린다. 저장된 캐시의 버전이 다르면 다시 계산

_cache: dict | None = None
_lock = threading.Lock()


def _meta_ref():
    return get_db().collection("meta").document("summary")


def _series_ref():
    return get_db().collection("meta").document("series")


def _periods_and_events() -> tuple[list[dict], list[dict]]:
    db = get_db()
    periods = [d.to_dict() for d in db.collection("volatile_periods").stream()]
    events = [d.to_dict() for d in db.collection("events").stream()]
    return periods, events


def top_periods_with_reasons(periods: list[dict], events: list[dict]) -> list[dict]:
    periods = sorted(periods, key=lambda p: abs(p["change_pct"]), reverse=True)
    result = []
    for p in periods[:TOP_PERIODS]:
        reasons = [e["title"] for e in events if e["start_date"] <= p["end"] and e["end_date"] >= p["start"]]
        result.append({
            "type": p["type"], "start": p["start"], "end": p["end"],
            "change_pct": p["change_pct"], "main_factor": p["main_factor"],
            "main_share_pct": p["main_share_pct"], "krw_factor_pct": p["krw_factor_pct"],
            "jpy_factor_pct": p["jpy_factor_pct"], "reasons": reasons,
        })
    return result


def brief_events(events: list[dict]) -> list[dict]:
    keys = ("start_date", "end_date", "title", "direction", "category")
    return sorted(({k: e[k] for k in keys} for e in events), key=lambda e: e["start_date"])


def compute_summary(rows: list[tuple[str, float]], periods: list[dict], events: list[dict], calendar: list[dict]) -> dict:
    pos = analysis.position(rows)
    return {
        "version": SUMMARY_VERSION,
        "period": f"{rows[0][0]} ~ {rows[-1][0]}",
        "count": len(rows),
        "unit": "원/100엔",
        "metrics": analysis.basic_metrics(rows),
        "trend": analysis.trend(rows),
        "position": pos,
        "volatile_periods": top_periods_with_reasons(periods, events),
        "events": brief_events(events),
        "travel": analysis.travel(pos["percentile_1y"], calendar),
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def get_summary() -> dict:
    global _cache
    with _lock:
        if _cache:
            return _cache

        saved = _meta_ref().get()
        if saved.exists and saved.to_dict().get("version") == SUMMARY_VERSION:
            _cache = saved.to_dict()
            return _cache

        rows = data_service.all_values()
        if not rows:
            raise NotFoundError("data 컬렉션이 비어 있습니다. seed_firestore.py로 데이터를 먼저 적재하세요.")
        calendar = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))["months"]
        periods, events = _periods_and_events()
        _cache = compute_summary(rows, periods, events, calendar)
        _meta_ref().set(_cache)
        return _cache


RANGE_DAYS = {"3m": 92, "1y": 365, "5y": 1826, "all": None}
MAX_POINTS = 400  # 그래프 점이 너무 많으면 브라우저가 느려지므로 줄인다

_series_cache: dict | None = None


def _all_series() -> dict:
    """전체 (날짜, 값) 배열. 메모리 → meta/series 문서(읽기 1건) → 전체 읽기 순서로 찾는다."""
    global _series_cache
    if _series_cache:
        return _series_cache
    saved = _series_ref().get()
    if saved.exists:
        _series_cache = saved.to_dict()
        return _series_cache
    rows = data_service.all_values()
    _series_cache = {"dates": [d for d, _ in rows], "values": [v for _, v in rows]}
    _series_ref().set(_series_cache)  # 2,918건이어도 문서 하나(약 90KB)에 들어간다
    return _series_cache


def downsample(dates: list[str], values: list[float], limit: int = MAX_POINTS) -> tuple[list[str], list[float]]:
    if len(dates) <= limit:
        return dates, values
    step = len(dates) / limit
    keep = {int(i * step) for i in range(limit)} | {len(dates) - 1}
    keep |= {values.index(max(values)), values.index(min(values))}  # 최고·최저는 꼭 남긴다
    idx = sorted(keep)
    return [dates[i] for i in idx], [values[i] for i in idx]


def get_series(range_key: str) -> dict:
    with _lock:
        full = _all_series()
    dates, values = full["dates"], full["values"]
    if not dates:
        raise NotFoundError("data 컬렉션이 비어 있습니다.")
    days = RANGE_DAYS[range_key]
    if days:
        start = (date.fromisoformat(dates[-1]) - timedelta(days=days)).isoformat()
        first = next(i for i, d in enumerate(dates) if d > start)
        dates, values = dates[first:], values[first:]
    hi, lo = max(values), min(values)
    out_dates, out_values = downsample(dates, values)
    events = [e for e in get_summary().get("events", []) if e["end_date"] >= dates[0] and e["start_date"] <= dates[-1]]
    return {
        "range": range_key,
        "start": dates[0],
        "end": dates[-1],
        "count": len(dates),
        "average": round(sum(values) / len(values), 2),
        "max": {"date": dates[values.index(hi)], "value": hi},
        "min": {"date": dates[values.index(lo)], "value": lo},
        "dates": out_dates,
        "values": out_values,
        "events": events,
    }


def invalidate() -> None:
    global _cache, _series_cache
    with _lock:
        _cache = None
        _series_cache = None
        _meta_ref().delete()
        _series_ref().delete()
