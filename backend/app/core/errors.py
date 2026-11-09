"""서비스 계층에서 쓰는 예외와, 이를 HTTP 응답으로 바꾸는 핸들러."""
import logging

from fastapi import FastAPI, Request
from app.core.responses import UTF8JSONResponse as JSONResponse  # charset=utf-8 붙은 JSON 응답
from google.api_core import exceptions as google_exceptions

from app.core.rate_limit import RateLimitExceeded

logger = logging.getLogger("yen-ai")


class NotFoundError(Exception):
    """요청한 문서가 없을 때"""


class ConflictError(Exception):
    """이미 있는 문서를 또 만들려고 할 때"""


class AIServiceError(Exception):
    """AI API 호출이 실패했거나 쓸 수 있는 답이 오지 않았을 때"""


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(_: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(AIServiceError)
    async def ai_error(_: Request, exc: AIServiceError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(RateLimitExceeded)
    async def too_many(_: Request, exc: RateLimitExceeded):
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    # Firestore 무료 한도(하루 읽기 5만, 쓰기 2만)를 넘었을 때. 아래 일반 DB 오류보다 먼저 잡힌다
    @app.exception_handler(google_exceptions.ResourceExhausted)
    async def quota_exceeded(_: Request, exc: google_exceptions.ResourceExhausted):
        logger.warning("Firestore 무료 한도 초과: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "오늘 데이터베이스 무료 사용량을 다 썼어요. 매일 한국 시간 오후 4~5시쯤 초기화되니 그 뒤에 다시 시도해 주세요."},
        )

    @app.exception_handler(google_exceptions.GoogleAPICallError)
    async def database_error(_: Request, exc: google_exceptions.GoogleAPICallError):
        logger.exception("Firestore 오류: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "데이터베이스에 연결할 수 없습니다. 잠시 후 다시 시도하세요."})
