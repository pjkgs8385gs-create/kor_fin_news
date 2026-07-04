import logging
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

import requests

from config import DISCORD_WEBHOOK_URL, TOP_N_REPORT
from storage import get_top_articles

logger = logging.getLogger(__name__)

EMBED_COLOR = 0x2B82CB


def _build_embed(articles: list[dict], date_str: str) -> dict:
    title = f"📊 오늘의 기업 거버넌스 뉴스 브리핑 — {date_str}"

    if not articles:
        return {
            "embeds": [{
                "title": title,
                "description": "오늘 기준 통과 기사 없음",
                "color": EMBED_COLOR,
                "footer": {"text": "총 0개 기사 분석 완료"},
            }]
        }

    fields = []
    for art in articles:
        summary_lines = art.get("summary", [])
        summary_text  = "\n".join(f"• {line}" for line in summary_lines) if summary_lines else "요약 없음"

        keywords     = art.get("keywords", [])
        keyword_text = " ".join(f"`{kw}`" for kw in keywords) if keywords else ""

        matched_kws      = art.get("matched_keywords", [])
        matched_kw_text  = " ".join(f"`{kw}`" for kw in matched_kws) if matched_kws else ""

        llm_score   = art.get("score", 0)
        sim         = art.get("similarity", 0)
        kw_score    = art.get("kw_score", 0)
        final_score = art.get("final_score", 0)

        pub_date = art.get("published_date", "")
        if pub_date:
            try:
                pub_date = pub_date[:16].replace("T", " ")
            except Exception:
                pass

        fields.append({
            "name": f"**[{art['title']}]({art['url']})**",
            "value": (
                f"🔍 **요약:**\n{summary_text}\n\n"
                f"🏷️ **LLM 키워드:** {keyword_text}\n"
                f"🔑 **매칭 키워드:** {matched_kw_text}\n\n"
                f"📈 **점수:** LLM `{llm_score:.1f}/10` | 유사도 `{sim:.3f}` | KW `{kw_score:.1f}` | 종합 `{final_score:.3f}`\n"
                f"📰 **출처:** {art.get('source', '')} | {pub_date}"
            ),
            "inline": False,
        })

    return {
        "embeds": [{
            "title": title,
            "color": EMBED_COLOR,
            "fields": fields,
            "footer": {"text": f"총 {len(articles)}개 기사 분석 완료"},
        }]
    }


def send_daily_report(articles: list[dict] = None):
    webhook_url = DISCORD_WEBHOOK_URL
    if not webhook_url:
        logger.warning("DISCORD_WEBHOOK env var not set — skipping Discord report")
        return

    date_str = datetime.now(KST).strftime("%Y-%m-%d")

    if articles is None:
        articles = get_top_articles(date_str, TOP_N_REPORT)

    # final_score 기준 정렬 (storage에서 온 경우 대비)
    articles = sorted(articles, key=lambda x: x.get("final_score", 0), reverse=True)

    payload = _build_embed(articles, date_str)

    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            logger.info("Discord report sent — %d articles", len(articles))
        else:
            logger.error(
                "Discord webhook returned %d: %s", resp.status_code, resp.text[:200]
            )
    except Exception as e:
        logger.error("Failed to send Discord report: %s", e)