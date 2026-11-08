"""한국은행 ECOS에서 원/엔(100엔), 원/달러 일별 환율을 받아 CSV로 저장한다.

실행 위치: backend 폴더
실행 명령: python scripts/fetch_ecos.py
결과 파일: data/raw/krw_jpy.csv, data/raw/krw_usd.csv  (ECOS 원본)
          data/processed/rates.csv                   (분석용으로 합친 파일)
"""
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ECOS_API_KEY")

BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
STAT_CODE = "731Y001"  # 주요국 통화의 대원화환율 (일별)
ITEMS = {
    "krw_jpy": "0000002",  # 원/일본엔(100엔)
    "krw_usd": "0000001",  # 원/미국달러
}
START_YEAR = 2015

BACKEND_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BACKEND_DIR / "data" / "raw"
OUT_PATH = BACKEND_DIR / "data" / "processed" / "rates.csv"


def fetch_year(item_code: str, year: int) -> list[dict]:
    """한 항목의 1년 치 데이터를 받는다. 1년은 약 250영업일이라 1000건이면 충분하다."""
    start = f"{year}0101"
    end = min(date(year, 12, 31), date.today()).strftime("%Y%m%d")
    url = f"{BASE_URL}/{API_KEY}/json/kr/1/1000/{STAT_CODE}/D/{start}/{end}/{item_code}"

    res = requests.get(url, timeout=30)
    res.raise_for_status()
    body = res.json()

    # 데이터가 없거나 키가 틀리면 ECOS는 StatisticSearch 대신 RESULT만 돌려준다
    if "StatisticSearch" not in body:
        result = body.get("RESULT", {})
        print(f"  ! {year}년: {result.get('CODE')} {result.get('MESSAGE')}")
        return []
    return body["StatisticSearch"]["row"]


def fetch_item(name: str, item_code: str) -> pd.DataFrame:
    """2015년부터 올해까지 연도별로 받아서 하나로 합친다."""
    print(f"\n[{name}] 수집 시작")
    rows = []
    for year in range(START_YEAR, date.today().year + 1):
        year_rows = fetch_year(item_code, year)
        print(f"  {year}년: {len(year_rows)}건")
        rows.extend(year_rows)
        time.sleep(0.3)  # 서버에 부담을 주지 않도록 잠깐 쉰다

    if not rows:
        sys.exit(f"{name} 데이터를 하나도 받지 못했습니다. ECOS_API_KEY를 확인하세요.")

    print(f"  항목명 확인: {rows[0]['ITEM_NAME1']}  (단위: {rows[0]['UNIT_NAME']})")

    raw = pd.DataFrame(rows)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw.to_csv(RAW_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")

    df = pd.DataFrame({
        "date": pd.to_datetime(raw["TIME"], format="%Y%m%d"),
        name: pd.to_numeric(raw["DATA_VALUE"].astype(str).str.replace(",", ""), errors="coerce"),
    })
    return df.dropna().drop_duplicates("date")


def main() -> None:
    if not API_KEY:
        sys.exit(".env에 ECOS_API_KEY가 없습니다.")

    frames = [fetch_item(name, code) for name, code in ITEMS.items()]

    # 두 환율이 모두 있는 날만 남긴다
    rates = frames[0].merge(frames[1], on="date", how="inner").sort_values("date")
    # 엔/달러 = 원/달러 ÷ (원/100엔 ÷ 100)
    rates["jpy_usd"] = (rates["krw_usd"] * 100 / rates["krw_jpy"]).round(4)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rates["date"] = rates["date"].dt.strftime("%Y-%m-%d")
    rates.to_csv(OUT_PATH, index=False)

    print("\n저장 완료:", OUT_PATH.relative_to(BACKEND_DIR))
    print(f"기간: {rates['date'].iloc[0]} ~ {rates['date'].iloc[-1]}")
    print(f"건수: {len(rates)}개")
    print("\n최근 5일:")
    print(rates.tail().to_string(index=False))


if __name__ == "__main__":
    main()
