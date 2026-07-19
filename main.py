"""
KorFinNews Monitor — entry point + scheduler
Usage:
  python main.py          # run on schedule (08:00 KST daily, machine local clock)
  python main.py --now    # run pipeline immediately
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

import requests
import schedule

from config import (
    CLAUDE_CLI_MODEL,
    DISCORD_WEBHOOK_URL,
    SCHEDULE_HOUR,
    SCHEDULE_MINUTE,
    TOP_N_REPORT,
)

# Configure logging
import io
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")),
        logging.FileHandler("logs/pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


def check_llm() -> bool:
    """Claude CLI 헬스체크."""
    import shutil
    cli = shutil.which("claude")
    if cli:
        logger.info("Claude CLI OK (model=%s, path=%s)", CLAUDE_CLI_MODEL, cli)
        return True
    logger.warning("Claude CLI를 PATH에서 찾지 못함. npm install -g @anthropic-ai/claude-code 필요.")
    return False


def check_webhook():
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK env var not set — reports will be skipped")
    else:
        logger.info("Discord webhook configured")


def run_pipeline():
    from crawler import fetch_articles
    from evaluator import evaluate_articles_with_fallback
    from storage import article_exists, save_article
    from reporter import send_daily_report

    logger.info("=" * 60)
    logger.info("Pipeline started at %s", datetime.now(KST).isoformat())

    # Fetch
    try:
        articles = fetch_articles()
    except Exception as e:
        logger.error("Crawler failed: %s", e)
        articles = []
    logger.info("FETCH: %d articles retrieved", len(articles))

    # Filter already-seen
    new_articles = [a for a in articles if not article_exists(a["url"])]
    logger.info("DEDUP: %d new (unseen) articles", len(new_articles))

    # Evaluate
    try:
        passing, fallback_reports = evaluate_articles_with_fallback(new_articles)
    except Exception as e:
        logger.error("Evaluator failed: %s", e)
        passing = []
        fallback_reports = []

    # Save
    saved = 0
    for art in passing:
        try:
            save_article(
                art,
                score=art.get("score", 0.0),
                summary=art.get("summary", []),
                keywords=art.get("keywords", []),
            )
            saved += 1
        except Exception as e:
            logger.error("Failed to save article '%s': %s", art.get("title", ""), e)

    # Report
    try:
        report_articles = passing[:TOP_N_REPORT] if passing else fallback_reports[:TOP_N_REPORT]
        if not passing and report_articles:
            logger.info("No passing articles — sending fallback top %d by score", len(report_articles))
        send_daily_report(report_articles)
    except Exception as e:
        logger.error("Reporter failed: %s", e)

    logger.info(
        "Pipeline complete -- fetched=%d | new=%d | passed=%d | saved=%d | reported=%d",
        len(articles), len(new_articles), len(passing), saved, len(report_articles),
    )
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="KorFinNews Monitor")
    parser.add_argument("--now", action="store_true", help="Run pipeline immediately")
    args = parser.parse_args()

    logger.info("KorFinNews Monitor starting up")

    # Startup checks
    from storage import init_collections
    try:
        init_collections()
    except Exception as e:
        logger.error("ChromaDB init failed: %s", e)

    check_llm()
    check_webhook()

    if args.now:
        logger.info("--now flag detected, running pipeline immediately")
        try:
            run_pipeline()
        except Exception as e:
            logger.exception("Pipeline crashed with unhandled exception: %s", e)
        return

    # Schedule daily run — KST 명시 (서버 timezone이 UTC여도 KST 08:00 실행)
    schedule_time = f"{SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}"
    schedule.every().day.at(schedule_time, "Asia/Seoul").do(run_pipeline)
    logger.info("Scheduled daily run at %s KST. Waiting...", schedule_time)

    # 주간 인사이트 리포트 — 매주 월요일 08:30 KST
    from weekly_reporter import run_weekly_report
    schedule.every().monday.at("08:30", "Asia/Seoul").do(run_weekly_report)
    logger.info("Scheduled weekly report on Monday 08:30 KST")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Shutdown requested — exiting gracefully")


if __name__ == "__main__":
    main()
