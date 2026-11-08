"""대화 기록 API: 저장, 목록, 불러오기, 삭제.

불러오기 방식은 미션의 (A)안을 택했다.
- GET /api/conversations        → 목록 (messages 제외, 가볍게)
- GET /api/conversations/{id}   → 특정 대화의 전체 messages
"""
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from app.schemas.conversation import ConversationCreate, ConversationDetail, ConversationSummary
from app.services import conversation_service

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

ConversationId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$", description="대화 ID (Firestore 자동 생성)")]


@router.post("", response_model=ConversationDetail, status_code=201, summary="대화 저장")
def create_conversation(body: ConversationCreate):
    return conversation_service.create(body)


@router.get("", response_model=list[ConversationSummary], summary="대화 목록 조회 (최근 순, messages 제외)")
def list_conversations(limit: int = Query(20, ge=1, le=100, description="가져올 대화 수")):
    return conversation_service.list_items(limit)


@router.get("/{conversation_id}", response_model=ConversationDetail, summary="특정 대화 불러오기 (전체 messages)")
def get_conversation(conversation_id: ConversationId):
    return conversation_service.get(conversation_id)


@router.delete("/{conversation_id}", status_code=204, summary="대화 삭제")
def delete_conversation(conversation_id: ConversationId):
    conversation_service.delete(conversation_id)
    return Response(status_code=204)
