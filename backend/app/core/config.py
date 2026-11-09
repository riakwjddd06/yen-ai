"""환경변수를 한곳에서 읽어 settings 객체로 제공한다."""
import os

from dotenv import load_dotenv

load_dotenv()  # backend/.env 파일을 읽어 환경변수로 등록 (Render에서는 파일 없이 환경변수를 바로 씀)


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"환경변수 {name}가 없습니다. backend/.env 또는 배포 환경변수를 확인하세요.")
    return value


class Settings:
    def __init__(self) -> None:
        # AI (코디세이 OpenAI 호환 API)
        self.openai_api_key = _required("OPENAI_API_KEY")
        self.openai_base_url = _required("OPENAI_BASE_URL")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
        self.max_completion_tokens = int(os.getenv("OPENAI_MAX_COMPLETION_TOKENS", "1500"))
        self.reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT")  # 선택: low 등. 비우면 보내지 않음
        self.chat_rate_limit = int(os.getenv("CHAT_RATE_LIMIT_PER_MIN", "10"))  # IP당 분당 채팅 횟수

        # Firebase: 로컬은 파일 경로, 배포는 JSON 문자열 (4단계에서 사용)
        self.firebase_credentials_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
        self.firebase_service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

        # CORS: 쉼표로 구분된 주소 목록을 리스트로 바꾼다
        origins = os.getenv("ALLOWED_ORIGINS", "")
        self.allowed_origins = [o.strip().rstrip("/") for o in origins.split(",") if o.strip()]


settings = Settings()
