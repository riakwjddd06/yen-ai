"""data 컬렉션 CRUD. 문서 ID는 날짜(YYYY-MM-DD)."""
from typing import Optional

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.errors import ConflictError, NotFoundError
from app.core.firebase import get_db
from app.schemas.data import DataCreate, DataUpdate

COLLECTION = "data"


def _col():
    return get_db().collection(COLLECTION)


def _to_out(snapshot) -> dict:
    d = snapshot.to_dict()
    return {"id": snapshot.id, "date": d["date"], "value": d["value"], "memo": d.get("memo", "")}


def create(body: DataCreate) -> dict:
    day = body.date.isoformat()
    ref = _col().document(day)
    try:
        ref.create({
            "date": day,
            "value": body.value,
            "memo": body.memo,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
    except AlreadyExists:
        raise ConflictError(f"{day} 데이터가 이미 있습니다. 수정하려면 PUT /api/data/{day}를 쓰세요.")
    return _to_out(ref.get())


def list_items(start: Optional[str], end: Optional[str], limit: int, order: str, cursor: Optional[str]) -> dict:
    query = _col()
    if start:
        query = query.where(filter=FieldFilter("date", ">=", start))
    if end:
        query = query.where(filter=FieldFilter("date", "<=", end))
    total = query.count().get()[0][0].value

    direction = firestore.Query.DESCENDING if order == "desc" else firestore.Query.ASCENDING
    page = query.order_by("date", direction=direction)
    if cursor:
        page = page.start_after({"date": cursor})
    docs = list(page.limit(limit + 1).stream())  # 한 개 더 읽어서 다음 페이지가 있는지 확인

    items = [_to_out(d) for d in docs[:limit]]
    next_cursor = items[-1]["date"] if len(docs) > limit else None
    return {"items": items, "total": total, "next_cursor": next_cursor}


def update(data_id: str, body: DataUpdate) -> dict:
    ref = _col().document(data_id)
    if not ref.get().exists:
        raise NotFoundError(f"{data_id} 데이터가 없습니다.")
    patch = body.model_dump(exclude_none=True)
    patch["updated_at"] = firestore.SERVER_TIMESTAMP
    ref.update(patch)
    return _to_out(ref.get())


def delete(data_id: str) -> None:
    ref = _col().document(data_id)
    if not ref.get().exists:
        raise NotFoundError(f"{data_id} 데이터가 없습니다.")
    ref.delete()


def all_values() -> list[tuple[str, float]]:
    """요약 계산용: 전체 (날짜, 값)을 날짜순으로. 문서 수만큼 읽기가 발생하므로 캐시와 함께 쓴다."""
    docs = _col().select(["date", "value"]).order_by("date").stream()
    return [(d.get("date"), float(d.get("value"))) for d in docs]
