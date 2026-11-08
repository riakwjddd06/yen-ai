"""rates.csv를 분석해 요약 통계와 급변동 구간을 출력한다.

실행 위치: backend 폴더
실행 명령: python scripts/analyze.py
결과 파일: data/processed/volatile_periods.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent
RATES_PATH = BACKEND_DIR / "data" / "processed" / "rates.csv"
OUT_PATH = BACKEND_DIR / "data" / "processed" / "volatile_periods.csv"

# ── 기준값: 구간이 15~30개 나오도록 여기 숫자만 조정한다 ──
DAILY_PCT = 3.0   # 하루 변동률이 이 % 이상이면 급변동일
Z_LIMIT = 4.0     # 평소(직전 60영업일) 변동폭의 몇 배 이상이면 급변동일
GAP_DAYS = 5      # 급변동일이 이 영업일 이내로 붙어 있으면 한 구간으로 묶음
WINDOW = 20       # 추세성 급변동을 볼 기간(영업일)
CUM_PCT = 6.0     # WINDOW 동안 이 % 이상 움직이면 추세성 급변동


def load() -> pd.DataFrame:
    df = pd.read_csv(RATES_PATH, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    df["r"] = np.log(df["krw_jpy"]).diff()            # 원/엔 일간 로그 변동률
    df["r_krw"] = np.log(df["krw_usd"]).diff()        # 원 요인: 원화가 달러 대비 약해지면 +
    df["r_jpy"] = -np.log(df["jpy_usd"]).diff()       # 엔 요인: 엔화가 달러 대비 강해지면 +
    df["z"] = df["r"] / df["r"].rolling(60).std().shift(1)
    return df


def print_summary(df: pd.DataFrame) -> None:
    v = df["krw_jpy"]
    latest = df.iloc[-1]
    max_row, min_row = df.loc[v.idxmax()], df.loc[v.idxmin()]
    last_1y = df[df["date"] > latest["date"] - pd.DateOffset(years=1)]

    change_20 = (v.iloc[-1] / v.iloc[-21] - 1) * 100
    ma20, ma60 = v.tail(20).mean(), v.tail(60).mean()
    if change_20 > 1 and ma20 > ma60:
        trend = "상승"
    elif change_20 < -1 and ma20 < ma60:
        trend = "하락"
    else:
        trend = "유지(횡보)"
    pct_1y = (last_1y["krw_jpy"] < latest["krw_jpy"]).mean() * 100

    print("=" * 50)
    print("요약 (단위: 원/100엔)")
    print("=" * 50)
    print(f"기간      : {df['date'].iloc[0]:%Y-%m-%d} ~ {latest['date']:%Y-%m-%d}")
    print(f"건수      : {len(df)}개")
    print(f"최신      : {latest['krw_jpy']:.2f} ({latest['date']:%Y-%m-%d})")
    print(f"전체 평균 : {v.mean():.2f}")
    print(f"최고      : {max_row['krw_jpy']:.2f} ({max_row['date']:%Y-%m-%d})")
    print(f"최저      : {min_row['krw_jpy']:.2f} ({min_row['date']:%Y-%m-%d})")
    print(f"1년 평균  : {last_1y['krw_jpy'].mean():.2f}")
    print(f"추세      : {trend} (최근 20영업일 {change_20:+.2f}%, 20일선 {ma20:.1f} / 60일선 {ma60:.1f})")
    print(f"1년 백분위: {pct_1y:.0f} (낮을수록 최근 1년 중 엔화가 싼 편)")


def group_days(idx: list[int], gap: int) -> list[tuple[int, int]]:
    """가까이 붙은 날짜 번호들을 (시작, 끝) 구간으로 묶는다."""
    periods = []
    for i in idx:
        if periods and i - periods[-1][1] <= gap:
            periods[-1] = (periods[-1][0], i)
        else:
            periods.append((i, i))
    return periods


def find_periods(df: pd.DataFrame) -> list[tuple[int, int, str]]:
    spike_mask = (df["r"].abs() >= DAILY_PCT / 100) | (df["z"].abs() >= Z_LIMIT)
    spikes = group_days(list(df.index[spike_mask]), GAP_DAYS)

    cum = df["krw_jpy"].pct_change(WINDOW).abs() >= CUM_PCT / 100
    trend_days = []
    for end in df.index[cum]:
        trend_days.extend(range(end - WINDOW + 1, end + 1))
    trends = group_days(sorted(set(trend_days)), 1)

    return [(s, e, "단기 급변") for s, e in spikes] + [(s, e, "추세성 급변") for s, e in trends]


def describe(df: pd.DataFrame, s: int, e: int, kind: str) -> dict:
    base = max(s - 1, 0)  # 구간 시작 전날을 기준값으로 쓴다
    start_val, end_val = df.loc[base, "krw_jpy"], df.loc[e, "krw_jpy"]
    krw = df.loc[base + 1:e, "r_krw"].sum()
    jpy = df.loc[base + 1:e, "r_jpy"].sum()
    total = abs(krw) + abs(jpy)
    return {
        "type": kind,
        "start": df.loc[s, "date"].strftime("%Y-%m-%d"),
        "end": df.loc[e, "date"].strftime("%Y-%m-%d"),
        "days": e - s + 1,
        "start_value": round(start_val, 2),
        "end_value": round(end_val, 2),
        "change_pct": round((end_val / start_val - 1) * 100, 2),
        "max_daily_pct": round(df.loc[s:e, "r"].abs().max() * 100, 2),
        "krw_factor_pct": round(krw * 100, 2),
        "jpy_factor_pct": round(jpy * 100, 2),
        "main_factor": "엔화" if abs(jpy) >= abs(krw) else "원화",
        "main_share_pct": round(max(abs(krw), abs(jpy)) / total * 100) if total else 0,
    }


def main() -> None:
    df = load()
    print_summary(df)

    result = pd.DataFrame([describe(df, s, e, k) for s, e, k in find_periods(df)])
    result = result.sort_values("change_pct", key=abs, ascending=False)
    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 50)
    print(f"급변동 구간 {len(result)}개  (단기 {sum(result['type'] == '단기 급변')} / 추세성 {sum(result['type'] == '추세성 급변')})")
    print("=" * 50)
    cols = ["type", "start", "end", "start_value", "end_value", "change_pct", "main_factor", "main_share_pct"]
    print(result[cols].head(30).to_string(index=False))
    print("\n저장 완료:", OUT_PATH.relative_to(BACKEND_DIR))


if __name__ == "__main__":
    main()
