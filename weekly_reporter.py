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

WEEKLY_PROMPT = """당신은 20년차 ESG/기업 거버넌스 전문가입니다. 기관투자자 자문과 스튜어드십 코드 설계 경험이 있으며, 뉴스 나열이 아니라 "그래서 무엇을 생각해야 하는가"를 짚는 것이 당신의 역할입니다.

아래는 지난 7일간 수집된 관련 뉴스 기사들입니다 (점수 높은 순).

{articles_block}

== 작업 ==
기사를 개별적으로 다루지 말고, 여러 기사를 관통하는 흐름(테마)으로 묶어서 해석하세요.
기사 번호 인용([1] 등)은 쓰지 마세요. 한국어로 작성하세요.

아래 양식을 정확히 따르세요 (Discord 메시지 — 마크다운 헤더 금지, 굵은글씨/이모지/불릿만):

🔥 **이번 주 핵심 테마** (2~3개)
각 테마마다:
▪ 흐름: 어떤 기사들이 하나의 방향을 가리키는가 (구체적 기업명·숫자 포함, 2~3줄)
▪ 표면 아래: 뉴스가 말하지 않는 배경·이해관계. 누가 이득이고 누가 손해인가 (2~3줄)
▪ 2차 효과: 이 흐름이 이어지면 3~6개월 내 무엇이 벌어지는가 (1~2줄)
▪ 반론: 이 해석이 틀렸다면 그 이유는 무엇인가 (1줄)

📡 **컨센서스와 다른 한 가지**
시장/언론의 지배적 해석 중 당신이 동의하지 않는 것 하나. 근거 2줄.

🔗 **연결고리**
이번 주 서로 무관해 보이는 두 사건이 실제로 연결되는 지점 하나. 2~3줄.

👀 **다음 주 체크리스트** (2~3개)
▪ 날짜/이벤트가 특정되면 명시, 무엇을 확인하고 그 결과가 무엇을 의미하는지 1줄씩.

총 3000자 이내. 문장은 짧게. 형용사보다 구체적 사실과 숫자. 확실하지 않은 것은 "확인 필요"로 표시하고 지어내지 마세요."""


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
