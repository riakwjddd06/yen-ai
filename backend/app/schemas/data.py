"""Data API의 요청·응답 모양과 검증 규칙(Pydantic)."""
from datetime import date as Date
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

VALUE_RULE = dict(gt=300, lt=3000, description="100엔당 원화 매매기준율 (300 초과 3000 미만)")


# ── 요청 ───────────────────────────────────────────
class DataCreate(BaseModel):
    date: Date = Field(..., description="날짜 (YYYY-MM-DD)", examples=["2026-11-09"])
    value: float = Field(..., examples=[852.31], **VALUE_RULE)
    memo: str = Field("", max_length=200, description="메모 (최대 200자)", examples=["여행 경비 환전함"])

    @field_validator("date")
    @classmethod
    def not_in_future(cls, v: Date) -> Date:
        if v > Date.today():
            raise ValueError("미래 날짜는 넣을 수 없습니다.")
        return v

    @field_validator("memo")
    @classmethod
    def strip_memo(cls, v: str) -> str:
        return v.strip()


class DataUpdate(BaseModel):
    """날짜는 문서 ID라서 바꿀 수 없다. 날짜를 바꾸려면 삭제 후 다시 추가한다."""
    value: Optional[float] = Field(None, examples=[855.0], **VALUE_RULE)
    memo: Optional[str] = Field(None, max_length=200, examples=["수정한 메모"])

    @model_validator(mode="after")
    def at_least_one(self):
        if self.value is None and self.memo is None:
            raise ValueError("value와 memo 중 하나 이상을 보내야 합니다.")
        if self.memo is not None:
            self.memo = self.memo.strip()
        return self


# ── 응답 ───────────────────────────────────────────
class DataOut(BaseModel):
    id: str = Field(..., examples=["2026-11-06"])
    date: str = Field(..., examples=["2026-11-06"])
    value: float = Field(..., examples=[852.31])
    memo: str = Field("", examples=[""])


class DataList(BaseModel):
    items: list[DataOut]
    total: int = Field(..., description="조건에 맞는 전체 건수")
    next_cursor: Optional[str] = Field(None, description="다음 페이지를 받을 때 cursor로 보낼 값. 없으면 마지막 페이지")


class DatedValue(BaseModel):
    date: str
    value: float


class Metrics(BaseModel):
    latest: DatedValue
    average: float
    max: DatedValue
    min: DatedValue
    avg_1y: float
    change_1m_pct: float
    change_1y_pct: float


class Position(BaseModel):
    percentile_1y: float = Field(..., description="최근 1년 중 현재 값보다 낮았던 날의 비율(%). 낮을수록 엔화가 싼 편")
    percentile_5y: float
    label: str


class VolatilePeriodOut(BaseModel):
    type: str
    start: str
    end: str
    change_pct: float
    main_factor: str
    main_share_pct: float
    krw_factor_pct: float
    jpy_factor_pct: float
    reasons: list[str] = []


class EventBrief(BaseModel):
    start_date: str
    end_date: str
    title: str
    direction: str = Field(..., description="원/엔 기준 상승(엔화 강세) / 하락(엔화 약세) / 혼조")
    category: str


class MonthlyTravel(BaseModel):
    month: int
    crowd: int
    score: int
    note: str


class Travel(BaseModel):
    rate_score: int = Field(..., description="지금 환전하기 좋은 정도 0~100 (100 - 1년 백분위)")
    rate_label: str
    monthly: list[MonthlyTravel] = Field(..., description="여행 월별 종합 점수 = 환율 70% + 시즌 30%")
    note: str


class SummaryOut(BaseModel):
    version: int = 1
    period: str
    count: int
    unit: str = "원/100엔"
    metrics: Metrics
    trend: str
    position: Position
    volatile_periods: list[VolatilePeriodOut]
    events: list[EventBrief] = Field([], description="기사로 확인한 급변동 이유 전체 (날짜순)")
    travel: Travel
    computed_at: str


class SeriesOut(BaseModel):
    range: str = Field(..., description="3m, 1y, 5y, all")
    start: str
    end: str
    count: int = Field(..., description="기간 안의 실제 데이터 수 (그래프 점은 최대 400개로 줄여서 보냄)")
    average: float
    max: DatedValue
    min: DatedValue
    dates: list[str]
    values: list[float]
    ma20: list[Optional[float]] = Field(..., description="20영업일 이동평균 (dates와 같은 위치)")
    events: list[EventBrief]


class MovingAverage(BaseModel):
    value: float
    gap_pct: float = Field(..., description="지금 환율이 이동평균보다 몇 % 높은지 (음수면 낮음)")


class MonthlyStat(BaseModel):
    month: str = Field(..., examples=["2026-10"])
    average: float
    diff_pct: float = Field(..., description="기간 평균 대비 % (양수 = 비싼 달)")
    days: int


class YearlyStat(BaseModel):
    year: int
    average: float
    max: DatedValue
    min: DatedValue
    change_pct: float = Field(..., description="그해 첫 영업일 대비 마지막 영업일 변동률")


class StatisticsOut(BaseModel):
    range: str
    start: str
    end: str
    count: int
    latest: DatedValue
    change_pct: float = Field(..., description="기간 첫날 대비 마지막 날 변동률 (%)")
    average: float
    volatility_pct: Optional[float] = Field(None, description="기간 변동성 (하루 변동의 표준편차를 1년 기준으로 환산, %)")
    volatility_20d_pct: Optional[float] = Field(None, description="최근 20영업일 변동성 (연율, %)")
    ma20: Optional[MovingAverage]
    ma60: Optional[MovingAverage]
    percentile_1y: float
    percentile_5y: float
    monthly: list[MonthlyStat]
    yearly: list[YearlyStat]
