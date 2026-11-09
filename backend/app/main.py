"""FastAPI 앱의 시작점. 실행: backend 폴더에서 uvicorn app.main:app --reload"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import register_error_handlers
from app.routers import chat, conversations, data

app = FastAPI(
    title="엔화 환율 AI 비서 API",
    description="원/엔 환율 데이터를 관리하고, 데이터 요약을 바탕으로 AI가 답하는 API입니다.",
    version="0.4.0",
)

# CORS: 허용한 주소(프론트엔드)에서 온 브라우저 요청만 받는다
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)
app.include_router(data.router)
app.include_router(conversations.router)
app.include_router(chat.router)


@app.get("/", include_in_schema=False)
def root():
    return {"message": "엔화 환율 AI 비서 API", "docs": "/docs"}


@app.get("/health", tags=["system"], summary="서버 상태 확인")
def health():
    """서버가 살아 있는지 확인한다. 프론트엔드가 Render 서버를 깨울 때도 쓴다."""
    return {"status": "ok"}
