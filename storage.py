"""기사 저장소.

리팩토링: ChromaDB → SQLite. 임베딩 검색 없음.
단일 테이블 articles. URL이 PK라 dedup 가능.
"""
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))

from config import SQLITE_PATH

logger = logging.getLogger(__name__)

_DB_PATH = Path(SQLITE_PATH)
_initialized = False


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def init_collections():
    """이름은 하위호환 (옛 ChromaDB 시절). 실제로는 SQLite 테이블 생성."""
    global _initialized
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                url               TEXT PRIMARY KEY,
                title             TEXT,
                source            TEXT,
                published_date    TEXT,
                score             REAL,
                similarity        REAL,
                kw_score          REAL,
                final_score       REAL,
                matched_keywords  TEXT,
                summary           TEXT,
                keywords          TEXT,
                saved_date        TEXT,
                body              TEXT
            )
            """
        )
        # 기존 DB 마이그레이션: body 컬럼 없으면 추가
        try:
            con.execute("ALTER TABLE articles ADD COLUMN body TEXT")
        except sqlite3.OperationalError:
            pass  # 이미 존재
        con.execute("CREATE INDEX IF NOT EXISTS idx_saved_date ON articles(saved_date)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_final_score ON articles(final_score DESC)")
        count = con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    logger.info("SQLite ready -- articles: %d rows (%s)", count, _DB_PATH)
    _initialized = True


def _ensure_init():
    if not _initialized:
        init_collections()


def article_exists(url: str) -> bool:
    _ensure_init()
    with _conn() as con:
        row = con.execute("SELECT 1 FROM articles WHERE url = ? LIMIT 1", (url,)).fetchone()
    return row is not None


def save_article(article: dict, score: float, summary: list, keywords: list):
    _ensure_init()
    with _conn() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO articles (
                url, title, source, published_date, score, similarity,
                kw_score, final_score, matched_keywords, summary, keywords, saved_date, body
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article["url"],
                article["title"],
                article.get("source", ""),
                article.get("published_date", ""),
                float(score),
                float(article.get("similarity", 0.0)),
                float(article.get("kw_score", 0.0)),
                float(article.get("final_score", 0.0)),
                ", ".join(article.get("matched_keywords", [])),
                " | ".join(summary) if isinstance(summary, list) else str(summary),
                ", ".join(keywords) if isinstance(keywords, list) else str(keywords),
                datetime.now(KST).strftime("%Y-%m-%d"),
                (article.get("body") or "")[:3000],
            ),
        )
    logger.info("Saved article: %.60s (score=%.1f)", article["title"], score)


def get_articles_since(days: int = 7) -> list[dict]:
    """최근 N일 저장 기사 전체 (final_score 순). 주간 리포트용."""
    _ensure_init()
    since = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    with _conn() as con:
        rows = con.execute(
            """
            SELECT title, url, source, saved_date, score, final_score,
                   summary, keywords, body
            FROM articles
            WHERE saved_date >= ?
            ORDER BY final_score DESC
            """,
            (since,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_top_articles(date_str: str, n: int) -> list[dict]:
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT title, url, source, published_date, score, similarity,
                   kw_score, final_score, matched_keywords, summary, keywords
            FROM articles
            WHERE saved_date = ?
            ORDER BY final_score DESC
            LIMIT ?
            """,
            (date_str, n),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        out.append({
            "title": r["title"] or "",
            "url": r["url"] or "",
            "source": r["source"] or "",
            "published_date": r["published_date"] or "",
            "score": float(r["score"] or 0),
            "similarity": float(r["similarity"] or 0),
            "kw_score": float(r["kw_score"] or 0),
            "final_score": float(r["final_score"] or 0),
            "matched_keywords": (r["matched_keywords"] or "").split(", "),
            "summary": (r["summary"] or "").split(" | "),
            "keywords": (r["keywords"] or "").split(", "),
        })
    return out
