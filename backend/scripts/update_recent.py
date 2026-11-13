"""최근 환율만 ECOS에서 받아 덧붙인다 (전체 다시 수집·적재 없이).

1) rates.csv의 마지막 날짜 다음 날부터 --until 날짜까지 ECOS에서 원/엔, 원/달러를 받는다.
2) data/processed/rates.csv 끝에 덧붙인다.
3) 배포된 백엔드의 POST /api/data로 하루씩 추가한다.
   → Firestore에 쓰이고, 서버가 요약·그래프 캐시에 그 날짜만 반영한다 (전체 다시 읽기 없음).

실행 위치: backend 폴더
미리 보기: python scripts/update_recent.py --until 20261112 --dry-run
실제 반영: python scripts/update_recent.py --until 20261112
로컬 서버에 넣기: ... --api http://127.0.0.1:8000
"""
import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(BACKEND_DIR / ".env")

from fetch_ecos import API_KEY, BASE_URL, ITEMS, OUT_PATH, STAT_CODE  # noqa: E402

DEFAULT_API = "https://yen-ai-api.onrender.com"
KST = timezone(timedelta(hours=9))


def fetch_range(item_code: str, start: str, end: str) -> pd.Series:
    """start~end(YYYYMMDD) 일별 값. 날짜(YYYY-MM-DD) → 값"""
    url = f"{BASE_URL}/{API_KEY}/json/kr/1/1000/{STAT_CODE}/D/{start}/{end}/{item_code}"
    res = requests.get(url, timeout=30)
    res.raise_for_status()
    body = res.json()
    if "StatisticSearch" not in body:
        result = body.get("RESULT", {})
        print(f"  ECOS 응답: {result.get('CODE')} {result.get('MESSAGE')}")
        return pd.Series(dtype=float)
    rows = body["StatisticSearch"]["row"]
    return pd.Series(
        {datetime.strptime(r["TIME"], "%Y%m%d").strftime("%Y-%m-%d"): float(str(r["DATA_VALUE"]).replace(",", ""))
         for r in rows}
    )


def wake(api: str) -> None:
    """Render 무료 서버가 잠들어 있으면 깨운다 (최대 약 2분)."""
    for attempt in range(1, 13):
        try:
            if requests.get(f"{api}/health", timeout=15).ok:
                print(f"서버 연결됨: {api}")
                return
        except requests.RequestException:
            pass
        print(f"  서버 깨우는 중 ({attempt}/12)...")
        time.sleep(10)
    sys.exit(f"서버({api})에 연결하지 못했습니다.")


def main() -> None:
    yesterday = (datetime.now(KST).date() - timedelta(days=1)).strftime("%Y%m%d")
    parser = argparse.ArgumentParser()
    parser.add_argument("--until", default=yesterday, help="마지막 날짜 YYYYMMDD (기본: 어제)")
    parser.add_argument("--api", default=DEFAULT_API, help="백엔드 주소")
    parser.add_argument("--dry-run", action="store_true", help="받아 오기만 하고 저장·전송하지 않음")
    args = parser.parse_args()

    if not API_KEY:
        sys.exit(".env에 ECOS_API_KEY가 없습니다.")

    rates = pd.read_csv(OUT_PATH, dtype={"date": str})
    last = rates["date"].iloc[-1]
    start = (date.fromisoformat(last) + timedelta(days=1)).strftime("%Y%m%d")
    if start > args.until:
        sys.exit(f"이미 최신이에요. rates.csv 마지막 날짜: {last}")
    print(f"rates.csv 마지막 날짜: {last} → {start} ~ {args.until} 수집")

    jpy = fetch_range(ITEMS["krw_jpy"], start, args.until)
    usd = fetch_range(ITEMS["krw_usd"], start, args.until)
    days = sorted(set(jpy.index) & set(usd.index))  # 두 환율이 모두 있는 날만 (기존과 같은 기준)
    if not days:
        sys.exit("새 데이터가 없어요. 주말·공휴일이거나 ECOS에 아직 올라오지 않았을 수 있어요.")

    new = pd.DataFrame({
        "date": days,
        "krw_jpy": [jpy[d] for d in days],
        "krw_usd": [usd[d] for d in days],
    })
    new["jpy_usd"] = (new["krw_usd"] * 100 / new["krw_jpy"]).round(4)
    bad = new[(new["krw_jpy"] <= 300) | (new["krw_jpy"] >= 3000)]
    if not bad.empty:
        sys.exit(f"원/엔 값이 이상해요. 확인이 필요합니다:\n{bad}")

    print("\n새로 받은 데이터:")
    print(new.to_string(index=False))
    if args.dry_run:
        print("\n--dry-run이라 저장·전송하지 않았어요.")
        return

    # 1) CSV에 덧붙이기 (다음에 analyze.py를 돌릴 때도 최신 데이터를 쓰도록)
    pd.concat([rates, new], ignore_index=True).to_csv(OUT_PATH, index=False)
    print(f"\nrates.csv에 {len(new)}건 추가 → 마지막 날짜 {days[-1]}")

    # 2) 배포 서버에 하루씩 추가 (서버가 Firestore 저장과 캐시 갱신을 함께 한다)
    api = args.api.rstrip("/")
    wake(api)
    added = skipped = 0
    for row in new.itertuples():
        res = requests.post(f"{api}/api/data", json={"date": row.date, "value": row.krw_jpy, "memo": ""}, timeout=60)
        if res.status_code == 201:
            added += 1
            print(f"  추가: {row.date} {row.krw_jpy}")
        elif res.status_code == 409:
            skipped += 1
            print(f"  이미 있음: {row.date}")
        else:
            print(f"  실패 {res.status_code}: {row.date} {res.text[:200]}")
    print(f"\n완료: 추가 {added}건, 이미 있음 {skipped}건")


if __name__ == "__main__":
    main()
