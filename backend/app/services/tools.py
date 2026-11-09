"""AI가 부를 수 있는 도구(Function Calling) 6개.

요약(시스템 프롬프트)에는 큰 급변동 5개와 대표 숫자만 들어간다. 그 밖의 날짜·기간, 이유의 자세한 설명,
여행 예산 계산, 지난 대화 찾기는 AI가 필요할 때 이 도구를 불러서 데이터를 받아 답한다.

- SCHEMAS : AI에게 보내는 도구 설명 (이름, 언제 쓰는지, 인자)
- run()   : AI가 고른 도구를 실제로 실행
도구는 캐시된 시계열(meta/series)과 요약을 쓰므로 Firestore를 거의 읽지 않는다.
같은 정의를 MCP 서버(멀티채널)에서도 그대로 가져다 쓴다.
"""
import json
import logging
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from statistics import fmean

from app.services import conversation_service, summary_service

logger = logging.getLogger("yen-ai")

MAX_ROWS = 60  # 기간 조회 때 돌려주는 원본 행 최대 개수 (토큰 절약)

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_summary",
            "description": "원/엔 환율 전체 요약(최신 값, 평균, 최고·최저, 추세, 최근 1년·5년 중 위치, 지금 환전 점수)을 조회한다. 지금 환율이 싼지 비싼지 같은 전반적인 질문에 쓴다.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_period_stats",
            "description": "특정 기간의 원/엔 환율 평균, 최고, 최저, 변동률과 날짜별 값(최대 60개)을 조회한다. '2022년 평균은?', '작년 이맘때는?', '특정 날짜 환율은?'처럼 요약에 없는 기간이나 날짜를 물을 때 쓴다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "시작일 YYYY-MM-DD (포함)"},
                    "end_date": {"type": "string", "description": "종료일 YYYY-MM-DD (포함). 하루만 볼 때는 시작일과 같게"},
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_volatile_periods",
            "description": "환율이 크게 움직인 급변동 구간을 변동폭 순으로 조회한다. 구간마다 변동률, 원화·엔화 중 어느 쪽 요인이 컸는지, 기록된 이유 제목이 들어 있다. '가장 크게 움직인 때는?', '2019년에 급변한 적 있어?'에 쓴다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "이 날짜 이후와 겹치는 구간만 (YYYY-MM-DD, 선택)"},
                    "end_date": {"type": "string", "description": "이 날짜 이전과 겹치는 구간만 (YYYY-MM-DD, 선택)"},
                    "limit": {"type": "integer", "description": "최대 개수 (1~10, 기본 5)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_events",
            "description": "기간과 겹치는 '기록된 급변동 이유'를 설명과 출처 기사 링크까지 조회한다. '왜 올랐어?', '그때 무슨 일이 있었어?'처럼 이유를 자세히 물을 때 쓴다. 결과가 비면 기록된 이유가 없다는 뜻이다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "시작일 YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "종료일 YYYY-MM-DD"},
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_travel_advice",
            "description": "일본 여행 환전 판단 자료를 조회한다. 지금 환전 점수, 여행 달의 혼잡도와 종합 점수, 예산(원)을 지금 환율과 최근 1년 평균·최저 환율로 바꾸면 몇 엔인지 계산한다. 'O월에 가려는데', '100만 원이면 몇 엔?'에 쓴다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "travel_month": {"type": "integer", "description": "여행 가는 달 1~12 (선택)"},
                    "budget_krw": {"type": "integer", "description": "환전할 예산, 원 단위 (선택)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_conversations",
            "description": "저장된 지난 대화를 제목에 들어간 낱말로 찾는다. '지난번에 물어본 거', '전에 도쿄 얘기한 대화'처럼 예전 대화를 찾을 때 쓴다.",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "찾을 낱말 (예: 도쿄, 2024년)"}},
                "required": ["keyword"],
            },
        },
    },
]

TOOL_NAMES = {"get_summary": "전체 요약", "get_period_stats": "기간 통계", "get_volatile_periods": "급변동 구간",
              "get_events": "급변동 이유", "get_travel_advice": "여행 환전 계산", "search_conversations": "대화 검색"}


# ── 도우미 ─────────────────────────
def _day(text: str | None) -> str | None:
    """YYYY-MM-DD 검사. 잘못된 값이면 ValueError"""
    if not text:
        return None
    return date.fromisoformat(str(text).strip()[:10]).isoformat()


def _pct(a: float, b: float) -> float:
    return round((b / a - 1) * 100, 2)


def _series() -> tuple[list[str], list[float], dict]:
    full = summary_service.full_series()
    return full["dates"], full["values"], full.get("memos", {})


# ── 도구 6개 ─────────────────────────
def get_summary() -> dict:
    s = summary_service.get_summary()
    return {
        "period": s["period"], "count": s["count"], "unit": s["unit"], "metrics": s["metrics"],
        "trend": s["trend"], "position": s["position"],
        "exchange_score": {"score": s["travel"]["rate_score"], "label": s["travel"]["rate_label"]},
    }


def get_period_stats(start_date: str, end_date: str) -> dict:
    start, end = _day(start_date), _day(end_date)
    if start > end:
        start, end = end, start
    dates, values, memos = _series()
    i, j = bisect_left(dates, start), bisect_right(dates, end)
    if i >= j:
        return {"error": f"{start} ~ {end}에는 데이터가 없어요. 주말·공휴일이거나 데이터 기간({dates[0]} ~ {dates[-1]}) 밖일 수 있어요."}
    d, v = dates[i:j], values[i:j]
    hi, lo = max(range(len(v)), key=v.__getitem__), min(range(len(v)), key=v.__getitem__)
    idx = summary_service.sample_indices(v, MAX_ROWS)
    return {
        "requested": {"start": start, "end": end},
        "actual": {"start": d[0], "end": d[-1], "business_days": len(d)},
        "average": round(fmean(v), 2),
        "max": {"date": d[hi], "value": v[hi]},
        "min": {"date": d[lo], "value": v[lo]},
        "first": {"date": d[0], "value": v[0]},
        "last": {"date": d[-1], "value": v[-1]},
        "change_pct": _pct(v[0], v[-1]),
        "rows": [{"date": d[k], "value": v[k]} for k in idx],
        "rows_note": "기간이 길면 날짜별 값은 최대 60개로 줄였어요" if len(idx) < len(d) else "",
        "memos": [{"date": x, "memo": memos[x]} for x in d if x in memos],
    }


def get_volatile_periods(start_date: str | None = None, end_date: str | None = None, limit: int = 5) -> dict:
    start, end = _day(start_date), _day(end_date)
    limit = max(1, min(int(limit or 5), 10))
    periods, events = summary_service._periods_and_events()
    hits = [p for p in periods if (not start or p["end"] >= start) and (not end or p["start"] <= end)]
    hits.sort(key=lambda p: abs(p["change_pct"]), reverse=True)
    result = []
    for p in hits[:limit]:
        reasons = [e["title"] for e in events if e["start_date"] <= p["end"] and e["end_date"] >= p["start"]]
        result.append({
            "start": p["start"], "end": p["end"], "type": p["type"], "change_pct": p["change_pct"],
            "main_factor": p["main_factor"], "main_share_pct": p["main_share_pct"],
            "krw_factor_pct": p["krw_factor_pct"], "jpy_factor_pct": p["jpy_factor_pct"],
            "reasons": reasons or ["기록된 이유 없음"],
        })
    return {"total_matched": len(hits), "periods": result,
            "factor_note": "원화 요인 = 원/달러 변화, 엔화 요인 = 엔/달러 변화. 비중이 큰 쪽이 주된 요인"}


def get_events(start_date: str, end_date: str) -> dict:
    start, end = _day(start_date), _day(end_date)
    if start > end:
        start, end = end, start
    _, events = summary_service._periods_and_events()
    hits = sorted((e for e in events if e["start_date"] <= end and e["end_date"] >= start), key=lambda e: e["start_date"])
    keys = ("start_date", "end_date", "title", "direction", "category", "description", "source_url")
    return {
        "events": [{k: e.get(k) for k in keys} for e in hits],
        "note": "" if hits else f"{start} ~ {end}에는 기록된 급변동 이유가 없어요. 추측하지 말고 그렇게 답하세요.",
    }


def get_travel_advice(travel_month: int | None = None, budget_krw: int | None = None) -> dict:
    s = summary_service.get_summary()
    m, t = s["metrics"], s["travel"]
    dates, values, _ = _series()
    # 요약(analysis._since)과 같은 기준: 마지막 날짜 365일 전 "다음 날"부터
    one_year = values[bisect_right(dates, (date.fromisoformat(dates[-1]) - timedelta(days=365)).isoformat()):]
    result = {
        "latest": m["latest"],
        "exchange_score": {"score": t["rate_score"], "label": t["rate_label"],
                           "percentile_1y": s["position"]["percentile_1y"]},
        "note": t["note"] + " 매매기준율 기준이며 실제 환전은 수수료·우대율에 따라 달라요.",
    }
    if travel_month:
        mm = int(travel_month)
        month = next((x for x in t["monthly"] if x["month"] == mm), None)
        result["travel_month"] = month or {"error": "travel_month는 1~12"}
        result["best_months"] = sorted(t["monthly"], key=lambda x: x["score"], reverse=True)[:3]
    if budget_krw:
        krw = int(budget_krw)
        to_yen = lambda rate: round(krw / rate * 100)  # 환율은 100엔당 원
        now, avg1, min1 = m["latest"]["value"], fmean(one_year), min(one_year)
        result["budget"] = {
            "krw": krw,
            "yen_now": to_yen(now),
            "yen_at_1y_average": to_yen(avg1),
            "yen_at_1y_low": to_yen(min1),
            "rates": {"now": now, "avg_1y": round(avg1, 2), "low_1y": min1},
            "gain_vs_1y_average_yen": to_yen(now) - to_yen(avg1),
        }
    return result


def search_conversations(keyword: str) -> dict:
    word = (keyword or "").strip().lower()
    if not word:
        return {"error": "keyword가 비었어요"}
    items = conversation_service.list_items(50)  # 제목만 읽는다 (메시지 본문은 읽지 않음)
    hits = [{"id": c["id"], "title": c["title"], "updated_at": c["updated_at"]}
            for c in items if word in c["title"].lower()][:10]
    return {"keyword": keyword, "matches": hits, "searched": len(items),
            "note": "" if hits else "제목에 그 낱말이 들어간 대화가 없어요"}


FUNCTIONS = {
    "get_summary": get_summary,
    "get_period_stats": get_period_stats,
    "get_volatile_periods": get_volatile_periods,
    "get_events": get_events,
    "get_travel_advice": get_travel_advice,
    "search_conversations": search_conversations,
}


def describe(name: str, args: dict) -> str:
    """화면에 보여 줄 한 줄 설명. 예: 기간 통계 (2022-01-01 ~ 2022-12-31)"""
    label = TOOL_NAMES.get(name, name)
    if args.get("start_date") or args.get("end_date"):
        return f"{label} ({args.get('start_date', '처음')} ~ {args.get('end_date', '끝')})"
    parts = []
    if args.get("travel_month"):
        parts.append(f"{args['travel_month']}월")
    if args.get("budget_krw"):
        parts.append(f"{int(args['budget_krw']):,}원")
    if args.get("keyword"):
        parts.append(f"'{args['keyword']}'")
    return f"{label} ({', '.join(parts)})" if parts else label


def run(name: str, arguments: str | dict | None) -> tuple[dict, dict]:
    """도구 하나를 실행한다. (AI에게 돌려줄 결과, 저장·표시용 기록)을 돌려준다.
    잘못된 이름이나 인자는 예외 대신 error 결과로 돌려줘서 AI가 스스로 고칠 수 있게 한다."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    except json.JSONDecodeError:
        args = {}
    record = {"name": name, "arguments": args, "label": describe(name, args)}
    func = FUNCTIONS.get(name)
    if not func:
        return {"error": f"{name}이라는 도구는 없어요"}, record
    try:
        result = func(**args)
    except (TypeError, ValueError) as e:
        result = {"error": f"인자가 올바르지 않아요: {e}"}
    logger.info("도구 호출: %s %s", name, json.dumps(args, ensure_ascii=False))
    return result, record
