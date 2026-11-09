"""통계 API용 계산. 캐시된 전체 시계열(meta/series)로 계산하므로 Firestore를 새로 읽지 않는다."""
import math
from statistics import fmean, stdev

from app.core.errors import NotFoundError
from app.services import analysis, summary_service

TRADING_DAYS = 250  # 1년 영업일 수 (변동성 연율화)


def _pct(a: float, b: float) -> float:
    """a에서 b로 몇 % 변했는지"""
    return round((b / a - 1) * 100, 2)


def _volatility(values: list[float]) -> float | None:
    """하루 로그수익률의 표준편차를 1년 기준으로 바꾼 값(%). 환율이 평소 얼마나 출렁이는지."""
    rets = [math.log(values[i] / values[i - 1]) for i in range(1, len(values))]
    if len(rets) < 2:
        return None
    return round(stdev(rets) * math.sqrt(TRADING_DAYS) * 100, 2)


def _moving(values: list[float], window: int) -> dict | None:
    if len(values) < window:
        return None
    ma = fmean(values[-window:])
    return {"value": round(ma, 2), "gap_pct": _pct(ma, values[-1])}  # 지금 환율이 이동평균보다 몇 % 위/아래


def get_statistics(range_key: str) -> dict:
    full = summary_service.full_series()
    dates, values = full["dates"], full["values"]
    if not dates:
        raise NotFoundError("data 컬렉션이 비어 있습니다.")

    first = summary_service.range_start(dates, range_key)
    r_dates, r_values = dates[first:], values[first:]
    r_avg = fmean(r_values)

    # 월별 평균: 기간 평균보다 비싼 달(+), 싼 달(-)
    months: dict[str, list[float]] = {}
    for d, v in zip(r_dates, r_values):
        months.setdefault(d[:7], []).append(v)
    monthly = [
        {"month": m, "average": round(fmean(vs), 2), "diff_pct": _pct(r_avg, fmean(vs)), "days": len(vs)}
        for m, vs in months.items()
    ]

    # 연도별 평균·최고·최저 (기간과 상관없이 전체)
    years: dict[str, list[tuple[str, float]]] = {}
    for d, v in zip(dates, values):
        years.setdefault(d[:4], []).append((d, v))
    yearly = []
    for y, rows in years.items():
        hi = max(rows, key=lambda r: r[1])
        lo = min(rows, key=lambda r: r[1])
        yearly.append({
            "year": int(y),
            "average": round(fmean(v for _, v in rows), 2),
            "max": {"date": hi[0], "value": hi[1]},
            "min": {"date": lo[0], "value": lo[1]},
            "change_pct": _pct(rows[0][1], rows[-1][1]),
        })

    pos = analysis.position(list(zip(dates, values)))
    return {
        "range": range_key,
        "start": r_dates[0],
        "end": r_dates[-1],
        "count": len(r_dates),
        "latest": {"date": dates[-1], "value": values[-1]},
        "change_pct": _pct(r_values[0], r_values[-1]),
        "average": round(r_avg, 2),
        "volatility_pct": _volatility(r_values),
        "volatility_20d_pct": _volatility(values[-21:]),
        "ma20": _moving(values, 20),
        "ma60": _moving(values, 60),
        "percentile_1y": pos["percentile_1y"],
        "percentile_5y": pos["percentile_5y"],
        "monthly": monthly,
        "yearly": yearly,
    }
