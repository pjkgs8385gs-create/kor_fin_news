"""주간 인사이트 리포트 — 매주 월요일 08:30 KST.

지난 7일 통과 기사를 Opus 한 번에 넣고 흐름/인사이트 분석 → Discord 전송.
상위 20건은 본문(있으면), 나머지는 요약만 → 입력 ~70K 토큰 이내.
"""
import logging
from datetime import datetime, timezone, timedelta

import requests

from config import DISCORD_WEBHOOK_URL, CLAUDE_CLI_TIMEOUT_SEC
from storage import get_articles_since

KST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)

TOP_N_WITH_BODY = 20
BODY_CHARS = 3000

WEEKLY_PROMPT = """당신은 20년차 ESG/기업 거버넌스 전문가입니다. 기관투자자 자문과 스튜어드십 코드 설계 경험이 있으며, 뉴스 나열이 아니라 "그래서 무엇을 생각해야 하는가"를 짚어주는 것이 당신의 역할입니다.

아래는 지난 7일간 수집된 관련 뉴스 기사들입니다 (점수 높은 순).

{articles_block}

== 작업 ==
주간 거버넌스 인사이트 리포트를 한국어로 작성하세요. 기사 번호 인용([1] 등)은 쓰지 마세요.

아래 양식을 정확히 따르세요 (Discord 메시지 — 마크다운 헤더 금지, 굵은글씨/이모지/불릿만):

🔥 **이번 주 빅이슈** (2~3개)
각 이슈마다 3줄 고정:
▪ 무슨 일: (1줄 사실)
▪ 왜 중요: (거버넌스 관점에서 의미)
▪ 시사점: (기업/투자자/정책 중 누가 무엇을 준비해야 하는가)

📡 **구조적 변화 시그널**
이번 주 기사들이 가리키는 중장기 방향 2~3줄. 규제·행동주의·기관투자자 축에서 무엇이 바뀌고 있는가.

🤔 **전문가의 질문**
이번 주 흐름이 던지는 본질적 질문 1~2개. (예: "자사주 소각 의무화는 주주가치 제고인가, 경영권 방어 무력화인가?") 각 질문에 당신의 관점 1줄.

👀 **다음 주 체크리스트** (2~3개)
▪ 날짜/이벤트가 특정되면 명시, 무엇을 확인해야 하는지 1줄씩.

총 1800자 이내. 문장은 짧게. 형용사보다 구체적 사실과 숫자."""


def _build_articles_block(articles: list[dict]) -> str:
    parts = []
    for i, a in enumerate(articles):
        head = f"[{i+1}] ({a['saved_date']}, score={a['final_score']:.2f}) {a['title']}"
        if i < TOP_N_WITH_BODY and a.get("body"):
            parts.append(f"{head}\n본문: {a['body'][:BODY_CHARS]}")
        else:
            parts.append(f"{head}\n요약: {a.get('summary', '')}")
    return "\n\n".join(parts)


def _send_discord(text: str):
    # webhook 일반 메시지는 2000자 제한 → 분할 전송
    for i in range(0, len(text), 1900):
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": text[i:i + 1900]},
            timeout=15,
        )
        if resp.status_code not in (200, 204):
            logger.error("Discord weekly report %d: %s", resp.status_code, resp.text[:200])
            return
    logger.info("Weekly report sent (%d chars)", len(text))


def run_weekly_report():
    logger.info("Weekly report started at %s", datetime.now(KST).isoformat())
    articles = get_articles_since(days=7)
    if not articles:
        logger.warning("Weekly report: no articles in last 7 days — skipping")
        return
    logger.info("Weekly report: %d articles loaded", len(articles))

    from langchain_core.messages import HumanMessage
    from llm.claude_cli_chat import ClaudeCLIChat

    prompt = WEEKLY_PROMPT.format(articles_block=_build_articles_block(articles))
    llm = ClaudeCLIChat(model="opus", timeout_sec=max(CLAUDE_CLI_TIMEOUT_SEC, 600))
    try:
        result = llm.invoke([HumanMessage(content=prompt)])
        report = (result.content or "").strip()
    except Exception as e:
        logger.error("Weekly report LLM failed: %s", e)
        return
    if not report:
        logger.error("Weekly report: empty LLM response")
        return

    date_str = datetime.now(KST).strftime("%Y-%m-%d")
    header = f"📈 **주간 거버넌스 인사이트** — {date_str} (지난 7일 {len(articles)}건 분석)\n\n"
    _send_discord(header + report)


if __name__ == "__main__":
    import io, sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace"))],
    )
    run_weekly_report()
