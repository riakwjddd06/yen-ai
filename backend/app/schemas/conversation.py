"""대화 기록 API의 요청·응답 모양과 검증 규칙."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    role: Literal["user", "assistant"] = Field(..., description="user = 사용자, assistant = AI")
    content: str = Field(..., min_length=1, max_length=4000)
    created_at: Optional[str] = Field(None, description="ISO 시각. 저장할 때 비어 있으면 서버가 채움")
    tool_calls: Optional[list[dict]] = Field(None, description="(보너스) AI가 호출한 도구 기록")

    @field_validator("content")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("빈 메시지는 저장할 수 없습니다.")
        return v.strip()


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=50, description="비우면 첫 질문 앞 30자로 자동 생성")
    messages: list[Message] = Field(..., min_length=1, description="최소 1개")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "title": "테스트 대화",
                "messages": [
                    {"role": "user", "content": "지금 엔화 싸?"},
                    {"role": "assistant", "content": "최근 1년 중 하위 8% 수준으로 싼 편이에요."},
                ],
            }]
        }
    }


class ConversationSummary(BaseModel):
    """목록용: messages를 빼서 가볍게 보낸다."""
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class ConversationDetail(BaseModel):
    """불러오기용: 전체 messages를 포함한다."""
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    messages: list[Message]
