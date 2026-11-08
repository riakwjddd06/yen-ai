"""환율 목록으로 요약 지표를 계산하는 순수 함수 모음 (DB와 무관, 테스트 쉬움)."""
from datetime import date, timedelta
from statistics import mean

Row = tuple[str, float]  # (날짜 'YYYY-MM-DD', 원/100엔)


def _since(rows: list[Row], days: int) -> list[Row]:
    last = date.fromisoformat(rows[-1][0])
    start = (last - timedelta(days=days)).isoformat()
    return [r for r in rows if r[0] > start]


def _percentile(values: list[float], current: float) -> float:
    return round(sum(v < current for v in values) / len(values) * 100, 1)


def basic_metrics(rows: list[Row]) -> dict:
    values = [v for _, v in rows]
    max_row = max(rows, key=lambda r: r[1])
    min_row = min(rows, key=lambda r: r[1])
    one_year = _since(rows, 365)
    month_ago = rows[-22][1] if len(rows) >= 22 else rows[0][1]
    return {
        "latest": {"date": rows[-1][0], "value": rows[-1][1]},
        "average": round(mean(values), 2),
        "max": {"date": max_row[0], "value": max_row[1]},
        "min": {"date": min_row[0], "value": min_row[1]},
        "avg_1y": round(mean(v for _, v in one_year), 2),
        "change_1m_pct": round((rows[-1][1] / month_ago - 1) * 100, 2),
        "change_1y_pct": round((rows[-1][1] / one_year[0][1] - 1) * 100, 2),
    }


def trend(rows: list[Row]) -> str:
    values = [v for _, v in rows]
    if len(values) < 60:
        return "판단 불가 (데이터 60개 미만)"
    change_20 = (values[-1] / values[-21] - 1) * 100
    ma20, ma60 = mean(values[-20:]), mean(values[-60:])
    if change_20 > 1 and ma20 > ma60:
        word = "상승 (엔화 강세)"
    elif change_20 < -1 and ma20 < ma60:
        word = "하락 (엔화 약세)"
    else:
        word = "유지 (횡보)"
    return f"{word}, 최근 20영업일 {change_20:+.2f}%, 20일선 {ma20:.1f} / 60일선 {ma60:.1f}"


def position(rows: list[Row]) -> dict:
    current = rows[-1][1]
    p1 = _percentile([v for _, v in _since(rows, 365)], current)
    p5 = _percentile([v for _, v in _since(rows, 365 * 5)], current)
    if p1 <= 20:
        label = "최근 1년 중 엔화가 싼 편"
    elif p1 >= 80:
        label = "최근 1년 중 엔화가 비싼 편"
    else:
        label = "최근 1년 중 중간 수준"
    return {"percentile_1y": p1, "percentile_5y": p5, "label": label}


def travel(percentile_1y: float, calendar: list[dict]) -> dict:
    rate_score = round(100 - percentile_1y)
    if rate_score >= 80:
        rate_label = "환전 적기"
    elif rate_score >= 60:
        rate_label = "나쁘지 않음"
    elif rate_score >= 40:
        rate_label = "보통"
    else:
        rate_label = "분할 환전·관망"
    monthly = []
    for m in calendar:
        season_score = (5 - m["crowd"]) / 4 * 100  # crowd 1 → 100점, 5 → 0점
        monthly.append({
            "month": m["month"],
            "crowd": m["crowd"],
            "score": round(rate_score * 0.7 + season_score * 0.3),
            "note": m["note"],
        })
    return {
        "rate_score": rate_score,
        "rate_label": rate_label,
        "monthly": monthly,
        "note": "환율 예측이 아니라 과거 대비 현재 위치입니다. 한 번에 환전하기보다 나눠서 환전하는 방법도 있습니다.",
    }
