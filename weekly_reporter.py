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

WEEKLY_PROMPT = """당신은 한국 기업 거버넌스/자본시장 전문 애널리스트입니다.
아래는 지난 7일간 수집된 관련 뉴스 기사들입니다 (점수 높은 순).

{articles_block}

== 작업 ==
위 기사들을 종합해 주간 인사이트 리포트를 한국어로 작성하세요.

1. **이번 주 핵심 흐름** (3~5개): 반복 등장한 이슈, 새로 부상한 이슈. 각각 근거 기사 언급.
2. **시그널 읽기**: 규제/입법 동향(상법개정 등), 행동주의 펀드 움직임, 기관투자자 행보에서 읽히는 방향성.
3. **다음 주 관전 포인트** (2~3개): 이번 주 흐름상 다음 주에 주목할 것.

간결하게. 총 1500자 이내. 마크다운 헤더 대신 굵은 글씨(**) 사용."""


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
