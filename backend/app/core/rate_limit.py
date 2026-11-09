"""IP별 분당 요청 수 제한 (서버 메모리 기반, 서버 1대 기준의 간단한 방식)."""
import time
from collections import defaultdict, deque

from fastapi import Request

_hits: dict[str, deque] = defaultdict(deque)


class RateLimitExceeded(Exception):
    pass


def client_ip(request: Request) -> str:
    # Render 같은 프록시 뒤에서는 실제 IP가 X-Forwarded-For 첫 번째 값에 들어 있다
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(request: Request, limit_per_minute: int) -> None:
    now = time.monotonic()
    q = _hits[client_ip(request)]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit_per_minute:
        raise RateLimitExceeded(f"요청이 너무 많습니다. 1분에 {limit_per_minute}번까지 질문할 수 있어요.")
    q.append(now)
