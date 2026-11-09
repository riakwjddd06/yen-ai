"""요약 계산과 캐시.

Firestore 무료 한도(하루 읽기 5만 건)를 아끼기 위해 3단계로 캐시한다.
1) 서버 메모리  2) Firestore meta/summary 문서(서버가 잠들었다 깨어나도 유지)  3) 둘 다 없으면 전체 계산
데이터가 바뀌면(POST/PUT/DELETE) invalidate()로 1)과 2)를 지운다.
"""
import json
import threading
from datetime import datetime, timezone
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


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None
        _meta_ref().delete()
