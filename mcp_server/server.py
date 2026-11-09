"""엔화 환율 AI 비서 MCP 서버 (보너스 A 멀티채널).

Claude 데스크톱 같은 MCP 클라이언트에서 우리 환율 데이터를 물어볼 수 있게 한다.
도구 정의와 실행은 모두 배포된 백엔드(Render)의 /api/tools가 맡는다.
그래서 채팅 AI(Function Calling)와 이 MCP 서버는 같은 도구 6개를 쓰고, 이 파일에는 키가 필요 없다.

실행 확인:  python server.py --check
Claude 데스크톱 연결: README의 "MCP 서버" 항목 참고
"""
import asyncio
import json
import os
import sys

import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server, ServerRequestContext

API_BASE = os.getenv("YEN_API_BASE_URL", "https://yen-ai-api.onrender.com").rstrip("/")
TIMEOUT = httpx.Timeout(90.0)  # Render 무료 서버가 잠들어 있으면 깨어나는 데 1분쯤 걸린다

_schemas: list[dict] | None = None


async def _fetch_schemas() -> list[dict]:
    """백엔드에서 도구 목록을 한 번 받아 둔다."""
    global _schemas
    if _schemas is None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{API_BASE}/api/tools")
            resp.raise_for_status()
            _schemas = resp.json()
    return _schemas


async def _run(name: str, arguments: dict) -> tuple[dict | str, bool]:
    """백엔드에서 도구를 실행한다. (결과, 오류 여부)"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(f"{API_BASE}/api/tools/{name}", json=arguments or {})
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        return f"백엔드 오류 {resp.status_code}: {detail}", True
    result = resp.json()["result"]
    return result, isinstance(result, dict) and "error" in result


async def handle_list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
    schemas = await _fetch_schemas()
    return types.ListToolsResult(tools=[
        types.Tool(
            name=s["function"]["name"],
            description=s["function"]["description"],
            input_schema=s["function"]["parameters"],
        )
        for s in schemas
    ])


async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    try:
        result, is_error = await _run(params.name, params.arguments or {})
    except httpx.HTTPError as e:
        result, is_error = f"백엔드({API_BASE})에 연결하지 못했어요: {e}", True
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content=result if isinstance(result, dict) else None,
        is_error=is_error,
    )


server = Server("yen-ai", on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)


async def run() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def check() -> None:
    """MCP 없이 백엔드 연결만 확인한다: 도구 목록 + 도구 2개 실행."""
    print(f"백엔드: {API_BASE}  (잠들어 있으면 1분쯤 걸려요)")
    schemas = await _fetch_schemas()
    print("도구 목록:", ", ".join(s["function"]["name"] for s in schemas))
    for name, args in [("get_period_stats", {"start_date": "2022-01-01", "end_date": "2022-12-31"}),
                       ("get_events", {"start_date": "2024-07-01", "end_date": "2024-08-31"})]:
        result, is_error = await _run(name, args)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        print(f"\n[{name}] {'오류' if is_error else '성공'}\n{text[:300]}")


if __name__ == "__main__":
    asyncio.run(check() if "--check" in sys.argv else run())
