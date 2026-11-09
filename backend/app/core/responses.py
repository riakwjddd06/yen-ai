"""JSON 응답에 charset=utf-8을 붙인다.

FastAPI 기본 응답은 'application/json'만 보내서, 사파리처럼 브라우저 주소창에서 바로 열면
한글이 깨져 보일 수 있다(크롬과 우리 프론트는 원래 UTF-8로 읽어서 문제없음).
"""
from fastapi.responses import JSONResponse


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"
