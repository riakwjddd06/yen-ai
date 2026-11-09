"""AI 채팅 API의 요청·응답."""
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500, description="사용자 질문 (500자 이하)",
                         examples=["지금 엔화 싼 편이야? 내년 3월에 도쿄 가려는데 언제 환전할까?"])
    conversation_id: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$",
                                           description="이어서 대화할 때 넣는다. 비우면 새 대화를 만든다")

    model_config = {
        "json_schema_extra": {"examples": [{"message": "지금 엔화 싼 편이야? 내년 3월에 도쿄 가려는데 언제 환전할까?"}]}
    }

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("질문을 입력하세요.")
        return v.strip()


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    title: str
    tool_calls: Optional[list[dict]] = Field(None, description="(보너스) AI가 호출한 도구 기록")
