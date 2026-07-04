"""
참조 기사 ChromaDB 저장 스크립트

사용법:
  python seed_articles.py                  # data/reference/*.txt 파일 기반
  python seed_articles.py --from-urls      # data/reference/urls.txt URL 목록 기반
  python seed_articles.py --from-urls-pattern urls_part_*.txt
                                          # data/reference/urls_part_*.txt URL 목록 기반 (정렬 후 순차 처리)
  python seed_articles.py --list           # 현재 저장된 참조 기사 목록 출력
  python seed_articles.py --clear          # 참조 컬렉션 전체 초기화

urls.txt 형식 (한 줄에 URL 하나, # 으로 주석):
  # 상법 개정 관련
  https://www.hankyung.com/article/xxx
  https://www.mk.co.kr/news/xxx
"""

import argparse
import hashlib
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/seed.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _url_to_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _source_from_url(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    known = {
        "hankyung.com": "한국경제",
        "mk.co.kr": "매일경제",
        "etnews.com": "전자신문",
        "sedaily.com": "서울경제",
        "chosun.com": "조선일보",
        "joongang.co.kr": "중앙일보",
        "donga.com": "동아일보",
        "hani.co.kr": "한겨레",
        "yonhapnews.co.kr": "연합뉴스",
        "yna.co.kr": "연합뉴스",
        "newsis.com": "뉴시스",
        "news1.kr": "뉴스1",
        "bizchosun.com": "비즈조선",
        "fnnews.com": "파이낸셜뉴스",
        "inews24.com": "아이뉴스24",
        "edaily.co.kr": "이데일리",
        "thebell.co.kr": "더벨",
    }
    for domain, name in known.items():
        if domain in host:
            return name
    return host


def _fetch_article(url: str) -> dict | None:
    # 일부 파일이 UTF-8 BOM으로 시작하면 URL 앞에 `\ufeff` 문자가 붙어서
    # requests URL 스키마 인식이 실패할 수 있습니다.
    url = url.lstrip("\ufeff").strip()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 제목 추출
        title = ""
        for sel in ["h1", "h2", ".article-title", ".news-title", "#title", ".tit"]:
            tag = soup.select_one(sel)
            if tag and tag.get_text(strip=True):
                title = tag.get_text(strip=True)
                break
        if not title and soup.title:
            title = soup.title.string or ""

        # 본문 추출
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "figure"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        body = " ".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20)

        if not body:
            logger.warning("  본문 추출 실패 (JavaScript 렌더링 필요할 수 있음): %s", url)
            return None

        return {
            "id": _url_to_id(url),
            "url": url,
            "source": _source_from_url(url),
            "title": title[:100] or url,
            "body": body[:3000],
        }
    except Exception as e:
        logger.error("  크롤링 실패 %s: %s", url, e)
        return None


def load_from_urls(urls_file: Path) -> list[dict]:
    if not urls_file.exists():
        logger.error("파일 없음: %s", urls_file)
        logger.info("아래 형식으로 파일을 만들어주세요:")
        logger.info("  # 주석은 # 으로 시작")
        logger.info("  https://www.hankyung.com/article/xxx")
        logger.info("  https://www.mk.co.kr/news/xxx")
        sys.exit(1)

    lines = urls_file.read_text(encoding="utf-8").splitlines()
    urls = []
    for l in lines:
        t = l.strip().lstrip("\ufeff")
        if not t or t.startswith("#"):
            continue
        urls.append(t)
    logger.info("URL %d개 발견 (urls.txt)", len(urls))

    articles = []
    for i, url in enumerate(urls, 1):
        logger.info("[%d/%d] 크롤링 중: %s", i, len(urls), url)
        art = _fetch_article(url)
        if art:
            logger.info("  OK: %s", art["title"][:60])
            articles.append(art)
        time.sleep(0.5)

    return articles


def load_from_txt(ref_dir: Path) -> list[dict]:
    txt_files = [f for f in ref_dir.glob("*.txt") if f.name != "urls.txt"]
    if not txt_files:
        logger.error("data/reference/ 에 .txt 파일이 없습니다.")
        sys.exit(1)

    logger.info("txt 파일 %d개 발견", len(txt_files))
    articles = []
    for path in txt_files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) < 3:
                logger.warning("건너뜀 (내용 부족): %s", path.name)
                continue
            articles.append({
                "id": path.stem,
                "url": lines[0].strip(),
                "source": lines[1].strip(),
                "title": path.stem,
                "body": "\n".join(lines[2:]).strip(),
            })
            logger.info("  로드: %s", path.name)
        except Exception as e:
            logger.error("  오류 %s: %s", path.name, e)

    return articles


def cmd_list():
    from storage import init_collections, _reference_col
    init_collections()
    col = _reference_col()
    result = col.get(include=["metadatas"])
    metas = result.get("metadatas", [])
    ids = result.get("ids", [])
    if not metas:
        print("저장된 참조 기사 없음")
        return
    print(f"\n=== 참조 기사 {len(metas)}개 ===")
    for doc_id, meta in zip(ids, metas):
        print(f"  [{doc_id}] {meta.get('title','')[:50]}  ({meta.get('source','')})")
    print()


def cmd_clear():
    from storage import _get_client
    import chromadb
    from config import CHROMA_COLLECTION_REFERENCE
    client = _get_client()
    client.delete_collection(CHROMA_COLLECTION_REFERENCE)
    logger.info("참조 컬렉션 초기화 완료")


def _sort_urls_part_paths(paths: list[Path]) -> list[Path]:
    """
    urls_part_001.txt처럼 숫자 suffix가 있으면 숫자 순으로,
    없으면 파일명 기준으로 정렬합니다.
    """

    def key(p: Path):
        m = re.search(r"(\d+)", p.stem)
        if m:
            return (int(m.group(1)), p.name)
        return (10**12, p.name)

    return sorted(paths, key=key)


def main():
    parser = argparse.ArgumentParser(description="참조 기사 ChromaDB 저장")
    parser.add_argument("--from-urls", action="store_true", help="urls.txt URL 목록으로 자동 크롤링")
    parser.add_argument(
        "--from-urls-pattern",
        type=str,
        default="",
        help="data/reference 아래에서 glob 패턴으로 URL 파일들을 불러옴 (예: urls_part_*.txt)",
    )
    parser.add_argument("--list", action="store_true", help="저장된 참조 기사 목록 출력")
    parser.add_argument("--clear", action="store_true", help="참조 컬렉션 초기화")
    args = parser.parse_args()

    if args.list:
        cmd_list()
        return

    if args.clear:
        cmd_clear()
        return

    from storage import init_collections, add_reference_articles
    from evaluator import embed_text

    init_collections()
    ref_dir = Path("data/reference")

    if args.from_urls_pattern:
        part_paths = _sort_urls_part_paths(list(ref_dir.glob(args.from_urls_pattern)))
        if not part_paths:
            logger.error("해당 패턴으로 URL 파일이 없습니다: %s", args.from_urls_pattern)
            sys.exit(1)

        for idx, urls_file in enumerate(part_paths, 1):
            logger.info("[%d/%d] URL 파일 처리: %s", idx, len(part_paths), urls_file.name)
            articles = load_from_urls(urls_file)
            if not articles:
                logger.warning("처리된 기사가 없습니다(건너뜀): %s", urls_file.name)
                continue

            logger.info("임베딩 시작 (%d개)...", len(articles))
            for art in articles:
                art["embedding"] = embed_text(art["title"] + " " + art["body"][:500])
                logger.info("  임베딩 완료: %s", art["title"][:50])

            add_reference_articles(articles)
            logger.info("=== 완료: %d개 기사 ChromaDB 저장 ===", len(articles))

        return

    if args.from_urls:
        articles = load_from_urls(ref_dir / "urls.txt")
    else:
        articles = load_from_txt(ref_dir)

    if not articles:
        logger.error("처리된 기사가 없습니다.")
        sys.exit(1)

    # 임베딩
    logger.info("임베딩 시작 (%d개)...", len(articles))
    for art in articles:
        art["embedding"] = embed_text(art["title"] + " " + art["body"][:500])
        logger.info("  임베딩 완료: %s", art["title"][:50])

    add_reference_articles(articles)
    logger.info("=== 완료: %d개 기사 ChromaDB 저장 ===", len(articles))


if __name__ == "__main__":
    main()
