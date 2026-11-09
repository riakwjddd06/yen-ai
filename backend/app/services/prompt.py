"""데이터 요약을 시스템 프롬프트 문장으로 바꾼다 (컨텍스트 주입의 핵심).

비용과 트레이드오프 (자세한 표는 README "컨텍스트 주입의 비용과 트레이드오프"):
- 이 프롬프트(약 3,700자, 약 2,000토큰)는 질문마다 통째로 다시 보낸다. 도구를 부르면 한 번 더 보내므로 입력 비용이 2~4배가 된다.
- 원본 2,918건을 넣으면 약 2만 토큰 이상이라 쓰지 않는다. 대신 대표 숫자와 급변동 상위 5개만 자세히, 나머지 이유는 제목만 넣는다.
- 자세한 설명, 다른 기간 값, 예산 계산은 도구(tools.py)로 필요할 때만 가져온다.
- 요약은 summary_service가 캐시하므로 프롬프트를 만들 때 Firestore를 거의 읽지 않는다. 다만 서버가 막 깨어난 첫 질문은 캐시를 다시 채우느라 느리다.
"""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def _won(v: float) -> str:
    return f"{v:,.2f}원"


def build_system_prompt(s: dict) -> str:
    m, pos, t = s["metrics"], s["position"], s["travel"]
    today = datetime.now(KST).strftime("%Y-%m-%d")

    periods = []
    for i, p in enumerate(s["volatile_periods"], 1):
        reasons = " / ".join(p["reasons"]) if p["reasons"] else "기록된 이유 없음"
        periods.append(
            f"{i}. {p['start']} ~ {p['end']} ({p['type']}): {p['change_pct']:+.2f}%, "
            f"주된 요인 {p['main_factor']} {p['main_share_pct']:.0f}% "
            f"(원화 요인 {p['krw_factor_pct']:+.2f}%, 엔화 요인 {p['jpy_factor_pct']:+.2f}%)\n"
            f"   기록된 이유: {reasons}"
        )

    events = "\n".join(
        f"- {e['start_date']} ~ {e['end_date']} [{e['direction']}] {e['title']}" for e in s.get("events", [])
    ) or "- 없음"

    months = "\n".join(
        f"- {x['month']}월: {x['score']}점 (혼잡도 {x['crowd']}/5, {x['note']})" for x in t["monthly"]
    )

    return f"""당신은 '엔화 환율 AI 비서'입니다. 사용자의 원/엔 환율 데이터를 근거로 한국어로 답합니다.
오늘 날짜(한국 시간): {today}

[데이터 요약] (단위: 100엔당 원화, 출처: 한국은행 매매기준율)
- 데이터 기간: {s['period']} / 총 {s['count']:,}개 영업일
- 최신 값: {m['latest']['date']} {_won(m['latest']['value'])}
- 전체 평균 {_won(m['average'])} / 최고 {_won(m['max']['value'])}({m['max']['date']}) / 최저 {_won(m['min']['value'])}({m['min']['date']})
- 최근 1년 평균 {_won(m['avg_1y'])}, 1개월 변동 {m['change_1m_pct']:+.2f}%, 1년 변동 {m['change_1y_pct']:+.2f}%
- 최근 추세: {s['trend']}
- 현재 위치: 최근 1년 백분위 {pos['percentile_1y']} ({pos['label']}), 최근 5년 백분위 {pos['percentile_5y']}

[주요 급변동 구간] (변동폭 상위 5개)
{chr(10).join(periods)}

[기록된 급변동 이유 전체] (기사로 확인한 사건, 날짜순. 대괄호는 원/엔 방향)
{events}

[여행 환전 점수]
- 지금 환전 점수: {t['rate_score']}점 ({t['rate_label']}) = 100 - 최근 1년 백분위
- 여행 월별 종합 점수 (환율 70% + 혼잡도 30%):
{months}

[답변 규칙]
1. 원/엔 값이 낮을수록 엔화가 싸다(일본 여행에 유리). 값이 오르면 엔화 강세, 내리면 엔화 약세다.
2. 숫자는 위 요약이나 도구 결과에 있는 값만 쓴다. 요약에 없는 기간·날짜는 get_period_stats 도구로 조회하고, 도구에도 없으면 "그 날짜 데이터가 없다"고 말한다. 숫자를 지어내지 않는다.
3. 급변동 이유는 '기록된 이유', '기록된 급변동 이유 전체', get_events 도구 결과에 있는 내용만 말한다. 자세한 설명이 필요하면 get_events를 부른다. 기록이 없는 시기는 "기록된 이유가 없다"고 답하고 추측하지 않는다.
4. 미래 환율은 예측하지 않는다. 환전 조언은 과거 대비 위치와 나눠서 환전하기 같은 일반 원칙까지만 하고, 최종 판단은 사용자 몫이라고 덧붙인다.
5. 환전 금액을 계산할 때는 매매기준율 기준이며 실제 은행 환전은 수수료와 우대율에 따라 다르다고 알린다.
6. 답변은 3~5문장으로, 핵심 숫자를 먼저 말한다. 표는 쓰지 않는다.
7. 도구는 요약만으로 답할 수 없을 때만 부른다: 특정 기간·날짜 값(get_period_stats), 큰 변동 순위(get_volatile_periods), 이유의 자세한 설명과 출처(get_events), 여행 달·예산 계산(get_travel_advice), 지난 대화 찾기(search_conversations). 요약으로 충분하면 바로 답한다.
"""
