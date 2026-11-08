"""Firebase Admin SDK 초기화와 Firestore 클라이언트 제공.

- 배포(Render): FIREBASE_SERVICE_ACCOUNT_JSON 환경변수에 JSON 내용 전체
- 로컬: FIREBASE_CREDENTIALS_PATH 환경변수에 키 파일 경로 (backend 폴더 기준)
"""
import json
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _load_credentials() -> credentials.Certificate:
    if settings.firebase_service_account_json:
        return credentials.Certificate(json.loads(settings.firebase_service_account_json))

    if settings.firebase_credentials_path:
        path = Path(settings.firebase_credentials_path)
        if not path.is_absolute():
            path = BACKEND_DIR / path  # 어느 폴더에서 실행해도 backend 기준으로 찾는다
        if not path.exists():
            raise RuntimeError(f"Firebase 키 파일이 없습니다: {path}")
        return credentials.Certificate(str(path))

    raise RuntimeError(
        "Firebase 키가 설정되지 않았습니다. "
        "FIREBASE_SERVICE_ACCOUNT_JSON 또는 FIREBASE_CREDENTIALS_PATH를 확인하세요."
    )


def get_db():
    """Firestore 클라이언트를 돌려준다. 앱이 처음 부를 때 한 번만 초기화한다."""
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(_load_credentials())
    return firestore.client()
