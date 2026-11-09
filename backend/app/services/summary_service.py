"""요약 계산과 캐시.

Firestore 무료 한도(하루 읽기 5만 건)를 아끼기 위해 3단계로 캐시한다.
1) 서버 메모리  2) Firestore meta 문서(서버가 잠들었다 깨어나도 유지)  3) 둘 다 없으면 전체 읽기 1번
- meta/series : 전체 날짜·값·메모 (그래프, 요약 계산, 내보내기에 함께 쓴다)
- meta/summary: AI 프롬프트에 넣는 요약
데이터가 바뀌면(POST/PUT/DELETE) apply_change()가 바뀐 1건만 캐시에 반영한다.
(전체 2,918건을 다시 읽지 않으므로 추가·삭제 1번에 읽기는 0~1건)
"""
import json
import logging
import threading
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.core.errors import NotFoundError
from app.core.firebase import get_db
from app.services import analysis, data_service

CALENDAR_PATH = Path(__file__).resolve().parents[2] / "data" / "travel_calendar.json"
TOP_PERIODS = 5  # 프롬프트 길이를 위해 변동폭 상위 5개만
SUMMARY_VERSION = 2  # 요약 모양이 바뀌면 올린다. 저장된 캐시의 버전이 다르면 다시 계산
SERIES_VERSION = 2   # meta/series 모양 버전 (2: 메모 포함)

logger = logging.getLogger("yen-ai")
_cache: dict | None = None
_series_cache: dict | None = None
_pe_cache: tuple[list[dict], list[dict]] | None = None  # 급변동 구간·이유 (seed 때만 바뀜)
_lock = threading.Lock()


def _meta_ref():
    return get_db().collection("meta").document("summary")


def _series_ref():
    return get_db().collection("meta").document("series")


def _periods_and_events() -> tuple[list[dict], list[dict]]:
    """급변동 구간과 이유. 서버가 켜진 뒤 처음 한 번만 읽는다 (약 50건)."""
    global _pe_cache
    if _pe_cache is None:
        db = get_db()
        periods = [d.to_dict() for d in db.collection("volatile_periods").stream()]
        events = [d.to_dict() for d in db.collection("events").stream()]
        _pe_cache = (periods, events)
    return _pe_cache


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


def _compute_and_save(full: dict) -> dict:
    rows = list(zip(full["dates"], full["values"]))
    calendar = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))["months"]
    periods, events = _periods_and_events()
    summary = compute_summary(rows, periods, events, calendar)
    _meta_ref().set(summary)
    return summary


def get_summary() -> dict:
    global _cache
    with _lock:
        if _cache:
            return _cache

        saved = _meta_ref().get()
        if saved.exists and saved.to_dict().get("version") == SUMMARY_VERSION:
            _cache = saved.to_dict()
            return _cache

        full = _all_series()
        if not full["dates"]:
            raise NotFoundError("data 컬렉션이 비어 있습니다. seed_firestore.py로 데이터를 먼저 적재하세요.")
        _cache = _compute_and_save(full)
        return _cache


RANGE_DAYS = {"3m": 92, "1y": 365, "5y": 1826, "all": None}
MAX_POINTS = 400  # 그래프 점이 너무 많으면 브라우저가 느려지므로 줄인다

def _all_series() -> dict:
    """전체 날짜·값·메모. 메모리 → meta/series 문서(읽기 1건) → 전체 읽기(문서 수만큼) 순서로 찾는다.
    _lock을 잡은 상태에서 부른다."""
    global _series_cache
    if _series_cache:
        return _series_cache
    saved = _series_ref().get()
    if saved.exists and saved.to_dict().get("v") == SERIES_VERSION:
        _series_cache = saved.to_dict()
        return _series_cache
    records = data_service.all_records()
    _series_cache = {
        "v": SERIES_VERSION,
        "dates": [r["date"] for r in records],
        "values": [r["value"] for r in records],
        "memos": {r["date"]: r["memo"] for r in records if r["memo"]},  # 메모가 있는 날만
    }
    _series_ref().set(_series_cache)  # 2,918건이어도 문서 하나(약 90KB)에 들어간다
    return _series_cache


def full_series() -> dict:
    """전체 날짜·값·메모 캐시 (통계 계산용). 보통 읽기 0건."""
    with _lock:
        return _all_series()


def range_start(dates: list[str], range_key: str) -> int:
    """기간(3m, 1y, 5y, all)이 시작하는 위치."""
    days = RANGE_DAYS[range_key]
    if not days:
        return 0
    start = (date.fromisoformat(dates[-1]) - timedelta(days=days)).isoformat()
    return next(i for i, d in enumerate(dates) if d > start)


def moving_average(values: list[float], window: int) -> list[float | None]:
    """직전 window개(오늘 포함) 평균. 앞쪽 window-1개는 None."""
    out: list[float | None] = []
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= window:
            total -= values[i - window]
        out.append(round(total / window, 2) if i >= window - 1 else None)
    return out


def sample_indices(values: list[float], limit: int = MAX_POINTS) -> list[int]:
    """그래프용으로 점을 limit개 정도로 줄일 때 남길 위치. 최고·최저와 마지막 점은 꼭 남긴다."""
    n = len(values)
    if n <= limit:
        return list(range(n))
    step = n / limit
    keep = {int(i * step) for i in range(limit)} | {n - 1}
    keep |= {values.index(max(values)), values.index(min(values))}
    return sorted(keep)


def downsample(dates: list[str], values: list[float], limit: int = MAX_POINTS) -> tuple[list[str], list[float]]:
    idx = sample_indices(values, limit)
    return [dates[i] for i in idx], [values[i] for i in idx]


def get_series(range_key: str) -> dict:
    with _lock:
        full = _all_series()
    all_dates, all_values = full["dates"], full["values"]
    if not all_dates:
        raise NotFoundError("data 컬렉션이 비어 있습니다.")
    first = range_start(all_dates, range_key)
    dates, values = all_dates[first:], all_values[first:]
    ma20 = moving_average(all_values, 20)[first:]  # 기간 앞쪽도 이전 데이터로 계산해 끊기지 않게
    hi, lo = max(values), min(values)
    idx = sample_indices(values)
    events = [e for e in get_summary().get("events", []) if e["end_date"] >= dates[0] and e["start_date"] <= dates[-1]]
    return {
        "range": range_key,
        "start": dates[0],
        "end": dates[-1],
        "count": len(dates),
        "average": round(sum(values) / len(values), 2),
        "max": {"date": dates[values.index(hi)], "value": hi},
        "min": {"date": dates[values.index(lo)], "value": lo},
        "dates": [dates[i] for i in idx],
        "values": [values[i] for i in idx],
        "ma20": [ma20[i] for i in idx],
        "events": events,
    }


def export_records() -> list[dict]:
    """내보내기용 전체 기록. 캐시를 쓰므로 보통 읽기 0건."""
    with _lock:
        full = _all_series()
        memos = full.get("memos", {})
        return [{"date": d, "value": v, "memo": memos.get(d, "")} for d, v in zip(full["dates"], full["values"])]


def apply_change(day: str, *, value: float | None = None, memo: str | None = None, deleted: bool = False) -> None:
    """데이터 1건이 바뀐 뒤, 전체를 다시 읽지 않고 캐시만 고친다.
    환율 값이 바뀐 경우에만 요약을 다시 계산한다 (메모만 바뀌면 요약은 그대로)."""
    global _cache, _series_cache
    with _lock:
        try:
            full = _all_series()
            dates, values = list(full["dates"]), list(full["values"])
            memos = dict(full.get("memos", {}))
            i = bisect_left(dates, day)
            exists = i < len(dates) and dates[i] == day
            value_changed = False

            if deleted:
                if exists:
                    del dates[i], values[i]
                    value_changed = True
                memos.pop(day, None)
            else:
                if value is not None:
                    if exists:
                        value_changed = values[i] != value
                        values[i] = value
                    else:
                        dates.insert(i, day)
                        values.insert(i, value)
                        value_changed = True
                if memo is not None:
                    if memo:
                        memos[day] = memo
                    else:
                        memos.pop(day, None)

            _series_cache = {"v": SERIES_VERSION, "dates": dates, "values": values, "memos": memos}
            _series_ref().set(_series_cache)
            if value_changed:
                if dates:
                    _cache = _compute_and_save(_series_cache)
                else:
                    _cache = None
                    _meta_ref().delete()
        except Exception:
            # 캐시 고치기에 실패하면 예전처럼 지워 두고, 다음 요청 때 다시 계산한다
            logger.exception("캐시 갱신 실패, 캐시를 지웁니다")
            _cache = None
            _series_cache = None
            try:
                _meta_ref().delete()
                _series_ref().delete()
            except Exception:
                logger.exception("meta 캐시 삭제 실패")


def invalidate() -> None:
    """캐시를 모두 지운다. (seed 등으로 데이터가 크게 바뀌었을 때)"""
    global _cache, _series_cache, _pe_cache
    with _lock:
        _cache = None
        _series_cache = None
        _pe_cache = None
        _meta_ref().delete()
        _series_ref().delete()
