"""Data API: 환율 데이터 CRUD 4개 + 요약 1개."""
from datetime import date
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Path, Query, Response

from app.schemas.data import DataCreate, DataList, DataOut, DataUpdate, SummaryOut
from app.services import data_service, summary_service

router = APIRouter(prefix="/api/data", tags=["data"])

DateId = Annotated[str, Path(pattern=r"^\d{4}-\d{2}-\d{2}$", description="문서 ID = 날짜 (YYYY-MM-DD)", examples=["2026-11-06"])]


# summary를 {data_id} 경로보다 먼저 선언한다
@router.get("/summary", response_model=SummaryOut, summary="데이터 요약 (AI 프롬프트 주입용)")
def read_summary():
    """기간, 개수, 평균·최고·최저, 추세, 1년 백분위, 급변동 상위 5개와 이유, 여행 점수를 돌려준다."""
    return summary_service.get_summary()


@router.post("", response_model=DataOut, status_code=201, summary="데이터 추가")
def create_data(body: DataCreate):
    item = data_service.create(body)
    summary_service.invalidate()
    return item


@router.get("", response_model=DataList, summary="데이터 목록 조회")
def list_data(
    start: Optional[date] = Query(None, description="시작일 (포함)"),
    end: Optional[date] = Query(None, description="종료일 (포함)"),
    limit: int = Query(50, ge=1, le=500, description="한 번에 받을 개수"),
    order: Literal["desc", "asc"] = Query("desc", description="desc = 최신순"),
    cursor: Optional[str] = Query(None, description="이전 응답의 next_cursor"),
):
    return data_service.list_items(
        start.isoformat() if start else None,
        end.isoformat() if end else None,
        limit, order, cursor,
    )


@router.put("/{data_id}", response_model=DataOut, summary="데이터 수정 (value, memo)")
def update_data(data_id: DateId, body: DataUpdate):
    item = data_service.update(data_id, body)
    summary_service.invalidate()
    return item


@router.delete("/{data_id}", status_code=204, summary="데이터 삭제")
def delete_data(data_id: DateId):
    data_service.delete(data_id)
    summary_service.invalidate()
    return Response(status_code=204)
