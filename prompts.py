"""LLM 프롬프트.

기존 2단계 (임베딩 유사도 필터 → LLM 점수) 를
통합 1회 호출로 합침: LLM 이 reference 기사 제목들을 함께 보고
관련성(relevant) + 점수 + 요약 + 키워드를 한 번에 반환.
"""

UNIFIED_SCORING_PROMPT = """다음 기사를 분석하여 JSON 으로만 응답하세요. 다른 텍스트 절대 금지.

[참고 분야의 기존 관련 기사 제목 (이런 주제들과 같은 카테고리인지 판단용)]
{reference_titles}

[평가할 기사 제목]
{title}

[평가할 기사 본문]
{body}

== 작업 ==
1. relevant (필수): 위 참고 기사들과 같은 분야(기업 거버넌스 / 상법 개정 / 스튜어드십 코드 / 행동주의 펀드 / 주주권 / 기관투자자) 인가?
   - true: 같은 분야 → 점수 계산 진행
   - false: 다른 분야 (단순 시황, 광고, 기업 이벤트 등) → score 0 으로 표기

2. score (0.0~10.0):
   - 객관성: 사실 기반 균형 보도 (0~3)
   - 분석 깊이: 거버넌스/상법/스튜어드십 심층 분석 (0~4)
   - 핵심 이슈 다룸: 기관투자자/행동주의/주주권 (0~3)

3. summary: 한국어 3줄 요약 (각 줄 50자 이내)

4. keywords: 핵심 키워드 3~5개

== 응답 형식 (JSON 만, 다른 텍스트 없이) ==
{{"relevant": <true|false>, "score": <0.0~10.0>, "summary": ["요약1", "요약2", "요약3"], "keywords": ["키워드1", "키워드2", "키워드3"]}}
"""


def build_scoring_prompt(title: str, body: str, reference_titles: list[str]) -> str:
    refs_block = "\n".join(f"- {t}" for t in reference_titles)
    return UNIFIED_SCORING_PROMPT.format(
        reference_titles=refs_block,
        title=title,
        body=body[:800],
    )
