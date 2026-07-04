import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

from config import (
    KEYWORD_WEIGHTS, MUST_PASS_KEYWORDS,
    MIN_KEYWORD_SCORE, MAX_ARTICLES_PER_KEYWORD,
    RSS_FEEDS,
    NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, NAVER_NEWS_URL,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
FETCH_TIMEOUT = 10
CUTOFF_HOURS  = 24


# ─── 유틸 ─────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return (text or "").lower().replace(" ", "")


def _keyword_score(title: str, body: str) -> tuple[float, list[str]]:
    """
    합산 점수 + 매칭 키워드 반환.
    - 긴 구문 우선 매칭 (Elliott Management > Elliott)
    - 동일 키워드 중복 카운트 방지
    - MUST_PASS 키워드 히트 시 score=999
    """
    combined = _normalize(f"{title} {body}")
    matched: dict[str, float] = {}

    # 긴 키워드 먼저 (부분 중복 방지)
    sorted_kws = sorted(KEYWORD_WEIGHTS.items(), key=lambda x: len(x[0]), reverse=True)

    for kw, weight in sorted_kws:
        norm_kw = _normalize(kw)
        if norm_kw in combined:
            # 이미 매칭된 더 긴 구문의 부분 문자열이면 스킵
            if not any(norm_kw in _normalize(existing) for existing in matched):
                matched[kw] = weight

    matched_kws = list(matched.keys())

    # MUST_PASS 즉시 통과
    if any(kw in MUST_PASS_KEYWORDS for kw in matched_kws):
        return 999.0, matched_kws

    return sum(matched.values()), matched_kws


def _fetch_body(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        text = " ".join(
            p.get_text(strip=True) for p in paragraphs
            if len(p.get_text(strip=True)) > 20
        )
        return text[:3000]
    except Exception as e:
        logger.warning("Failed to fetch body from %s: %s", url, e)
        return ""


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def _make_article(title: str, url: str, body: str, pub_date: Optional[datetime],
                  source: str, score: float, matched_kws: list[str]) -> dict:
    return {
        "title":            title,
        "url":              url,
        "body":             body,
        "published_date":   pub_date.isoformat() if pub_date else datetime.now(timezone.utc).isoformat(),
        "source":           source,
        "matched_keywords": matched_kws,
        "kw_score":         score,
    }


# ─── RSS 수집 ─────────────────────────────────────────────────────────────────

def _fetch_rss(cutoff: datetime, seen_urls: set) -> list[dict]:
    articles = []

    for feed_url in RSS_FEEDS:
        try:
            logger.info("Fetching RSS: %s", feed_url)
            feed = feedparser.parse(feed_url)

            for entry in feed.entries:
                url = getattr(entry, "link", None)
                if not url or url in seen_urls:
                    continue

                pub_date = _parse_date(entry)
                if pub_date and pub_date < cutoff:
                    continue

                title  = getattr(entry, "title", "")
                source = getattr(feed.feed, "title", feed_url)
                body   = _fetch_body(url) or getattr(entry, "summary", "")

                score, matched_kws = _keyword_score(title, body)

                if score < MIN_KEYWORD_SCORE:
                    logger.debug("[SKIP ✗] score=%.1f | %s | %.50s", score, matched_kws, title)
                    continue

                logger.info("[PASS ✓] score=%.1f | %s | %.50s", score, matched_kws, title)
                seen_urls.add(url)
                articles.append(_make_article(title, url, body, pub_date, source, score, matched_kws))
                time.sleep(0.3)

        except Exception as e:
            logger.error("RSS error %s: %s", feed_url, e)

    return articles


# ─── 네이버 뉴스 API 수집 ─────────────────────────────────────────────────────

def _fetch_naver(cutoff: datetime, seen_urls: set) -> list[dict]:
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.warning("Naver API key 없음 — 네이버 수집 스킵")
        return []

    articles = []
    headers  = {
        "X-Naver-Client-Id":     NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    # 핵심·중요 키워드만 네이버 검색 (가중치 2.0 이상)
    search_keywords = [kw for kw, w in KEYWORD_WEIGHTS.items() if w >= 2.0]

    for kw in search_keywords:
        try:
            params = {"query": kw, "display": MAX_ARTICLES_PER_KEYWORD, "sort": "date"}
            resp   = requests.get(NAVER_NEWS_URL, headers=headers, params=params, timeout=FETCH_TIMEOUT)
            resp.raise_for_status()
            items  = resp.json().get("items", [])
            logger.info("Naver [%s] → %d건", kw, len(items))

            for item in items:
                url = item.get("link", item.get("originallink", ""))
                if not url or url in seen_urls:
                    continue

                title = BeautifulSoup(item.get("title", ""), "html.parser").get_text()
                desc  = BeautifulSoup(item.get("description", ""), "html.parser").get_text()
                body  = _fetch_body(url) or desc

                score, matched_kws = _keyword_score(title, body)

                if score < MIN_KEYWORD_SCORE:
                    logger.debug("[SKIP ✗] score=%.1f | %s | %.50s", score, matched_kws, title)
                    continue

                logger.info("[PASS ✓] score=%.1f | %s | %.50s", score, matched_kws, title)
                seen_urls.add(url)
                articles.append(_make_article(title, url, body, None, "Naver", score, matched_kws))
                time.sleep(0.2)

        except Exception as e:
            logger.error("Naver API error [%s]: %s", kw, e)

    return articles


# ─── 메인 진입점 ──────────────────────────────────────────────────────────────

def fetch_articles() -> list[dict]:
    cutoff    = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)
    seen_urls : set[str] = set()

    rss_articles   = _fetch_rss(cutoff, seen_urls)
    naver_articles = _fetch_naver(cutoff, seen_urls)

    articles = rss_articles + naver_articles
    # kw_score 높은 순 정렬
    articles.sort(key=lambda x: x["kw_score"], reverse=True)

    logger.info(
        "최종 수집 %d건 (RSS=%d / Naver=%d)",
        len(articles), len(rss_articles), len(naver_articles),
    )
    return articles