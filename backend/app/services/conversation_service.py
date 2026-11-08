"""conversations 컬렉션 CRUD. 대화 하나 = 문서 하나, 메시지는 messages 배열에 저장."""
from datetime import datetime, timezone

from firebase_admin import firestore

from app.core.errors import NotFoundError
from app.core.firebase import get_db
from app.schemas.conversation import ConversationCreate, Message

COLLECTION = "conversations"


def _col():
    return get_db().collection(COLLECTION)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_title(messages: list[Message]) -> str:
    first = next((m.content for m in messages if m.role == "user"), messages[0].content)
    first = " ".join(first.split())  # 줄바꿈·여러 칸 공백 정리
    return first[:30] + ("…" if len(first) > 30 else "")


def _message_dicts(messages: list[Message]) -> list[dict]:
    stamp = now_iso()
    result = []
    for m in messages:
        d = m.model_dump(exclude_none=True)
        d.setdefault("created_at", stamp)
        result.append(d)
    return result


def _to_detail(snapshot) -> dict:
    d = snapshot.to_dict()
    return {
        "id": snapshot.id,
        "title": d["title"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "message_count": d.get("message_count", len(d.get("messages", []))),
        "messages": d.get("messages", []),
    }


def create(body: ConversationCreate) -> dict:
    stamp = now_iso()
    messages = _message_dicts(body.messages)
    ref = _col().document()  # 자동 ID
    ref.set({
        "title": (body.title or "").strip() or make_title(body.messages),
        "created_at": stamp,
        "updated_at": stamp,
        "message_count": len(messages),
        "messages": messages,
    })
    return _to_detail(ref.get())


def list_items(limit: int) -> list[dict]:
    docs = (
        _col()
        .select(["title", "created_at", "updated_at", "message_count"])  # messages는 읽지 않는다
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    return [{"id": d.id, **d.to_dict()} for d in docs]


def get(conversation_id: str) -> dict:
    snap = _col().document(conversation_id).get()
    if not snap.exists:
        raise NotFoundError(f"대화 {conversation_id}가 없습니다.")
    return _to_detail(snap)


def delete(conversation_id: str) -> None:
    ref = _col().document(conversation_id)
    if not ref.get().exists:
        raise NotFoundError(f"대화 {conversation_id}가 없습니다.")
    ref.delete()


def append(conversation_id: str, messages: list[Message]) -> None:
    """(7단계 채팅용) 기존 대화 끝에 메시지를 붙인다."""
    ref = _col().document(conversation_id)
    snap = ref.get()
    if not snap.exists:
        raise NotFoundError(f"대화 {conversation_id}가 없습니다.")
    # ArrayUnion은 똑같은 메시지를 하나로 합쳐 버리므로, 읽어서 이어 붙인 뒤 통째로 저장한다
    merged = snap.to_dict().get("messages", []) + _message_dicts(messages)
    ref.update({"messages": merged, "message_count": len(merged), "updated_at": now_iso()})
