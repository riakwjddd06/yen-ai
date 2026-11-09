"""분석 결과를 Firestore에 적재한다.

실행 위치: backend 폴더
미리 보기: python scripts/seed_firestore.py --dry-run   (DB에 쓰지 않고 건수만 확인)
실제 적재: python scripts/seed_firestore.py

적재 대상
- data              : 날짜별 원/엔 환율 (문서 ID = 날짜, 다시 실행해도 중복 없음)
- events            : 급변동 이유 (실행할 때마다 지우고 새로 씀)
- volatile_periods  : 급변동 구간 (실행할 때마다 지우고 새로 씀)

무료 한도(하루 쓰기 2만 건) 안에서 한 번에 약 3,000건을 쓴다. 하루 5번 이상 반복하지 않는다.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))  # app 패키지를 불러오기 위해

DATA_DIR = BACKEND_DIR / "data"
RATES_PATH = DATA_DIR / "processed" / "rates.csv"
PERIODS_PATH = DATA_DIR / "processed" / "volatile_periods.csv"
EVENTS_PATH = DATA_DIR / "events.json"
BATCH_SIZE = 400  # Firestore 배치 한도는 500


def build_memos(rates: pd.DataFrame, events: list[dict]) -> dict[str, str]:
    """이벤트마다 기간 안에서 가장 크게 움직인 하루에만 memo를 단다."""
    memos: dict[str, str] = {}
    change = rates.set_index("date")["krw_jpy"].pct_change().abs()
    for ev in events:
        in_range = change[(change.index >= ev["start_date"]) & (change.index <= ev["end_date"])].dropna()
        if in_range.empty:
            continue
        key_day = in_range.idxmax()
        memos[key_day] = (memos.get(key_day, "") + " / " if key_day in memos else "") + ev["title"]
    return memos


def load_all():
    rates = pd.read_csv(RATES_PATH, dtype={"date": str})
    periods = pd.read_csv(PERIODS_PATH, encoding="utf-8-sig")
    events = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))

    ids = [f"ev-{e['start_date']}" for e in events]
    if len(ids) != len(set(ids)):
        sys.exit("events.json에 시작일이 같은 이벤트가 있습니다. 하나로 합치거나 날짜를 조정하세요.")
    return rates, periods, events


def write_in_batches(db, collection: str, docs: list[tuple[str, dict]]) -> None:
    for i in range(0, len(docs), BATCH_SIZE):
        batch = db.batch()
        for doc_id, body in docs[i:i + BATCH_SIZE]:
            batch.set(db.collection(collection).document(doc_id), body)
        batch.commit()
        print(f"  {collection}: {min(i + BATCH_SIZE, len(docs))}/{len(docs)}")


def clear_collection(db, collection: str) -> None:
    for doc in db.collection(collection).stream():
        doc.reference.delete()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 내용만 확인")
    args = parser.parse_args()

    rates, periods, events = load_all()
    memos = build_memos(rates, events)

    data_docs = [
        (row.date, {"date": row.date, "value": float(row.krw_jpy), "memo": memos.get(row.date, "")})
        for row in rates.itertuples()
    ]
    event_docs = [(f"ev-{e['start_date']}", e) for e in events]
    period_docs = [(f"vp-{r['start']}-{r['type']}", r) for r in periods.to_dict("records")]

    print(f"data {len(data_docs)}건 ({data_docs[0][0]} ~ {data_docs[-1][0]}), memo가 달린 날 {len(memos)}일")
    print(f"events {len(event_docs)}건, volatile_periods {len(period_docs)}건")
    print("memo 예시:")
    for day, memo in list(memos.items())[:5]:
        print(f"  {day}: {memo}")

    if args.dry_run:
        print("\n--dry-run: DB에 쓰지 않았습니다.")
        return

    from firebase_admin import firestore
    from app.core.firebase import get_db

    db = get_db()
    now = firestore.SERVER_TIMESTAMP
    for _, body in data_docs:
        body.update({"created_at": now, "updated_at": now})

    print("\n적재 시작")
    write_in_batches(db, "data", data_docs)
    clear_collection(db, "events")
    write_in_batches(db, "events", event_docs)
    clear_collection(db, "volatile_periods")
    write_in_batches(db, "volatile_periods", period_docs)

    db.collection("meta").document("summary").delete()  # 데이터가 바뀌었으니 요약·그래프 캐시를 지운다
    db.collection("meta").document("series").delete()

    count = db.collection("data").count().get()[0][0].value
    sample = db.collection("data").document(data_docs[-1][0]).get().to_dict()
    print(f"\n완료: data 컬렉션 {count}건")
    print("최근 문서:", {k: sample[k] for k in ("date", "value", "memo")})


if __name__ == "__main__":
    main()
