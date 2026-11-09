"""AI 채팅 API."""
from fastapi import APIRouter, Request

from app.core import rate_limit
from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, summary="AI 채팅 (데이터 요약 주입 + 대화 자동 저장)")
def chat(body: ChatRequest, request: Request):
    """요약 조회 → 시스템 프롬프트 주입 → AI 호출 → conversations에 자동 저장.
    conversation_id를 비우면 새 대화를 만들고, 넣으면 그 대화에 이어서 저장한다."""
    rate_limit.check(request, settings.chat_rate_limit)
    return chat_service.chat(body)
