"""AI 채팅: 요약 조회 → 시스템 프롬프트에 주입 → AI 호출(필요하면 도구 실행 반복) → 대화 자동 저장."""
import json
import logging

import openai
from openai import OpenAI

from app.core.config import settings
from app.core.errors import AIServiceError
from app.schemas.chat import ChatRequest
from app.schemas.conversation import ConversationCreate, Message
from app.services import conversation_service, summary_service, tools
from app.services.prompt import build_system_prompt

logger = logging.getLogger("yen-ai")
HISTORY_LIMIT = 10  # 이전 메시지는 최근 10개만 함께 보낸다 (토큰 절약)
MAX_TOOL_ROUNDS = 3  # 도구를 부르고 다시 묻는 횟수 상한 (무한 반복 방지)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,  # 코디세이 OpenAI 호환 주소
            timeout=40,
            max_retries=1,
        )
    return _client


def _ask_ai(messages: list[dict]):
    """AI를 한 번 부른다. 도구 목록을 함께 보내고, 응답 메시지(choices[0])를 돌려준다."""
    params = {
        "model": settings.openai_model,
        "messages": messages,
        "max_completion_tokens": settings.max_completion_tokens,
        "tools": tools.SCHEMAS,
    }
    if settings.reasoning_effort:
        params["reasoning_effort"] = settings.reasoning_effort
    try:
        resp = _get_client().chat.completions.create(**params)
    except openai.RateLimitError:
        raise AIServiceError("AI 사용량 한도에 걸렸어요. 잠시 후 다시 시도하세요.")
    except openai.APITimeoutError:
        raise AIServiceError("AI 응답이 너무 오래 걸려요. 다시 시도하세요.")
    except openai.APIError as e:
        logger.exception("AI API 오류: %s", e)
        raise AIServiceError("AI 서버와 통신하지 못했어요. 잠시 후 다시 시도하세요.")
    if resp.usage:
        logger.info("AI 사용량: %s", resp.usage)
    return resp.choices[0]


def _answer(messages: list[dict]) -> tuple[str, list[dict]]:
    """도구 호출 루프. AI가 도구를 고르면 실행해서 결과를 붙이고 다시 묻는다 (최대 MAX_TOOL_ROUNDS번).
    (최종 답, 사용한 도구 기록)을 돌려준다."""
    used: list[dict] = []
    for _ in range(MAX_TOOL_ROUNDS + 1):
        choice = _ask_ai(messages)
        msg = choice.message
        if msg.tool_calls:
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                result, record = tools.run(tc.function.name, tc.function.arguments)
                used.append(record)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)})
            continue

        reply = (msg.content or "").strip()
        if reply:
            return reply, used
        if choice.finish_reason == "length":
            raise AIServiceError("답변이 길어져 끝까지 만들지 못했어요. OPENAI_MAX_COMPLETION_TOKENS를 늘려 주세요.")
        raise AIServiceError("AI가 빈 답변을 보냈어요. 다시 시도하세요.")
    raise AIServiceError("AI가 도구를 너무 여러 번 불러서 답을 마치지 못했어요. 질문을 조금 좁혀서 다시 물어보세요.")


def chat(req: ChatRequest) -> dict:
    # 1) 데이터 요약 조회 (캐시 우선)
    summary = summary_service.get_summary()

    # 2) 요약을 시스템 프롬프트에 넣는다
    messages = [{"role": "system", "content": build_system_prompt(summary)}]

    # 3) 이어지는 대화면 이전 메시지를 붙인다 (질문과 답 글만, 도구 결과는 다시 보내지 않는다)
    if req.conversation_id:
        history = conversation_service.get(req.conversation_id)["messages"][-HISTORY_LIMIT:]
        messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": req.message})

    # 4) AI 호출 + 필요하면 도구 실행
    reply, used = _answer(messages)

    # 5) 대화 자동 저장 (어떤 도구를 썼는지도 함께)
    new_messages = [
        Message(role="user", content=req.message),
        Message(role="assistant", content=reply, tool_calls=used or None),
    ]
    if req.conversation_id:
        conversation_service.append(req.conversation_id, new_messages)
        conv = conversation_service.get(req.conversation_id)
    else:
        conv = conversation_service.create(ConversationCreate(messages=new_messages))

    return {"reply": reply, "conversation_id": conv["id"], "title": conv["title"], "tool_calls": used or None}
