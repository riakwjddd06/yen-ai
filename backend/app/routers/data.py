"""Data API: 환율 데이터 CRUD 4개 + 요약, 그래프, 통계, 내보내기."""
from datetime import date
from typing import Annotated, Literal, Optional

import csv
import io
import json

from fastapi import APIRouter, Path, Query, Response

from app.schemas.data import DataCreate, DataList, DataOut, DataUpdate, SeriesOut, StatisticsOut, SummaryOut
from app.services import data_service, stats_service, summary_service

router = APIRouter(prefix="/api/data", tags=["data"])

DateId = Annotated[str, Path(pattern=r"^\d{4}-\d{2}-\d{2}$", description="문서 ID = 날짜 (YYYY-MM-DD)", examples=["2026-11-06"])]


# summary를 {data_id} 경로보다 먼저 선언한다
@router.get("/summary", response_model=SummaryOut, summary="데이터 요약 (AI 프롬프트 주입용)")
def read_summary():
    """기간, 개수, 평균·최고·최저, 추세, 1년 백분위, 급변동 상위 5개와 이유, 여행 점수를 돌려준다."""
    return summary_service.get_summary()


@router.get("/series", response_model=SeriesOut, summary="그래프용 시계열 (기간별, 최대 400점)")
def read_series(range: Literal["3m", "1y", "5y", "all"] = Query("1y", description="3m = 3개월, 1y = 1년, 5y = 5년, all = 전체")):
    """기간 안의 날짜·값 배열과 평균·최고·최저, 그 기간에 걸친 급변동 이유를 돌려준다."""
    return summary_service.get_series(range)


@router.get("/statistics", response_model=StatisticsOut, summary="통계 (이동평균, 변동성, 백분위, 월별·연도별)")
def read_statistics(range: Literal["3m", "1y", "5y", "all"] = Query("1y", description="3m = 3개월, 1y = 1년, 5y = 5년, all = 전체")):
    """기간 변동률, 20·60일 이동평균, 변동성(연율), 1년·5년 중 위치, 월별 평균(기간 평균 대비), 연도별 최고·최저를 돌려준다.
    캐시된 시계열로 계산하므로 Firestore 읽기가 거의 없다."""
    return stats_service.get_statistics(range)


@router.get("/export", summary="데이터 내보내기 (CSV 또는 JSON 다운로드)")
def export_data(format: Literal["csv", "json"] = Query("csv")):
    rows = summary_service.export_records()  # 캐시에서 만든다 (전체 읽기 없음)
    if format == "json":
        body = json.dumps(rows, ensure_ascii=False, indent=2)
        return Response(body, media_type="application/json; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="yen_rates.json"'})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["date", "value", "memo"])
    writer.writeheader()
    writer.writerows(rows)
    # utf-8-sig(BOM): 엑셀에서 한글 메모가 깨지지 않게 한다
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="yen_rates.csv"'})


@router.post("", response_model=DataOut, status_code=201, summary="데이터 추가")
def create_data(body: DataCreate):
    item = data_service.create(body)
    summary_service.apply_change(item["date"], value=item["value"], memo=item["memo"])
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
    summary_service.apply_change(item["date"], value=item["value"], memo=item["memo"])
    return item


@router.delete("/{data_id}", status_code=204, summary="데이터 삭제")
def delete_data(data_id: DateId):
    data_service.delete(data_id)
    summary_service.apply_change(data_id, deleted=True)
    return Response(status_code=204)
