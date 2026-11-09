"""AI 도구 API (보너스 A 멀티채널).

채팅 AI가 쓰는 도구 6개를 HTTP로도 연다. MCP 서버(mcp_server/server.py)가 이 API를 불러서
Claude 데스크톱 같은 다른 채널에서도 같은 도구를 쓸 수 있게 한다. 모두 읽기 전용이다.
"""
from typing import Annotated, Any

from fastapi import APIRouter, Body, Path, Request

from app.core import rate_limit
from app.services import tools

router = APIRouter(prefix="/api/tools", tags=["tools"])

ToolName = Annotated[str, Path(
    pattern=r"^(get_summary|get_period_stats|get_volatile_periods|get_events|get_travel_advice|search_conversations)$",
    description="도구 이름 (GET /api/tools 목록의 function.name)",
    examples=["get_period_stats"],
)]
TOOLS_RATE_LIMIT = 30  # IP당 분당 도구 호출 수


@router.get("", summary="AI 도구 목록 (Function Calling과 MCP가 같이 쓰는 정의)")
def list_tools() -> list[dict]:
    """채팅 AI에게 보내는 것과 똑같은 도구 이름, 설명, 인자 스키마를 돌려준다."""
    return tools.SCHEMAS


@router.post("/{name}", summary="도구 실행 (읽기 전용)")
def run_tool(
    name: ToolName,
    request: Request,
    arguments: dict[str, Any] = Body(default={}, examples=[{"start_date": "2022-01-01", "end_date": "2022-12-31"}]),
):
    """본문에 도구 인자를 JSON으로 넣는다. 예: get_period_stats → {"start_date": "2022-01-01", "end_date": "2022-12-31"}"""
    rate_limit.check(request, TOOLS_RATE_LIMIT, bucket="tools")
    result, record = tools.run(name, arguments)
    return {"tool": name, "label": record["label"], "arguments": record["arguments"], "result": result}
