"""reference_list.txt 파서.

포맷 (3줄 1엔트리):
    [hash] 기사 제목  (출처)
        URL
    (빈 줄)

여기서 제목만 추출해서 LLM 프롬프트에 주입하는 용도로 사용.
"""
import random
import re
from pathlib import Path

_TITLE_RE = re.compile(r"^\s*\[[0-9a-f]+\]\s+(.+?)\s*\([^()]+\)\s*$")

_cached: list[str] | None = None


def load_reference_titles(path: Path | str | None = None) -> list[str]:
    """제목 리스트를 한 번 로드해 메모리 캐시. 호출자가 신경 안 써도 됨."""
    global _cached
    if _cached is not None:
        return _cached
    if path is None:
        path = Path(__file__).resolve().parent / "reference_list.txt"
    path = Path(path)
    titles: list[str] = []
    if not path.exists():
        _cached = titles
        return titles
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _TITLE_RE.match(line)
        if m:
            title = m.group(1).strip()
            # 노이즈 제거 (메뉴, 페이지명 등)
            if len(title) < 8:
                continue
            if title in {"많이 본 뉴스", "상단영역", "정치", "60나만의 AI 비서"}:
                continue
            titles.append(title)
    _cached = titles
    return titles


def sample_reference_titles(n: int = 30, seed: int | None = None) -> list[str]:
    """전체 reference 중 n 개 무작위 샘플 (LLM 프롬프트 주입용)."""
    titles = load_reference_titles()
    if len(titles) <= n:
        return list(titles)
    rng = random.Random(seed)
    return rng.sample(titles, n)
