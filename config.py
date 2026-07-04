import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트의 .env 로드
load_dotenv(Path(__file__).resolve().parent / ".env")

ROOT = Path(__file__).resolve().parent

# ─── 키워드 가중치 ────────────────────────────────────────────────────────────
# 핵심(3.0): 하나만 매칭돼도 거의 통과 / 중요(2.0) / 보조(1.0): 단독 불가
KEYWORD_WEIGHTS = {
    # 핵심
    "Elliott Management": 3.0,
    "Palliser Capital":   3.0,
    "상법개정":            3.0,
    "행동주의":         3.0,
    "행동주의펀드":         3.0,
    "삼성 지배구조":        3.0,
    "스튜어드십코드":       3.0,

    # 중요
    "삼성물산":            2.0,
    "블랙록":              2.0,
    "소액주주":            2.0,
    "주주제안":            2.0,
    "수탁자책임":          2.0,
    "자본시장법":          2.0,
    "밸류업":              2.0,
    "주주환원":            2.0,
    "자사주":              2.0,

    # 보조
    "헤지펀드":            1.0,
    "기관투자자":          1.0,
    "자산운용사":          1.0,
    "esg투자":             1.0,
    "주주관여":            1.0,
    "연기금":              1.0,
    "의결권자문사":         1.0,
    "국부펀드":            1.0,
    "삼성전자":            1.0,
    "지배구조":            1.0,
    "거버넌스":            1.0,
}

# 이 키워드가 하나라도 매칭되면 점수 무관 즉시 통과
MUST_PASS_KEYWORDS = {
    "Elliott Management",
    "Palliser Capital",
    "상법개정",
    "스튜어드십코드",
}

MIN_KEYWORD_SCORE  = 3.0   # 합산 점수 기준 (MUST_PASS 제외)
MAX_ARTICLES_PER_KEYWORD = 10

# 하위 호환: crawler에서 MIN_KEYWORD_MATCHES 참조하는 곳 있으면 그대로 동작
MIN_KEYWORD_MATCHES = 1

# ─── 네이버 뉴스 API ──────────────────────────────────────────────────────────
NAVER_CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
NAVER_NEWS_URL      = "https://openapi.naver.com/v1/search/news.json"

# ─── RSS ──────────────────────────────────────────────────────────
RSS_FEEDS = [
    "https://www.hankyung.com/feed/economy",
    "https://rss.etnews.com/Section901.xml",
    "https://www.mk.co.kr/rss/30100041/",
]

# ─── LLM ─────────────────────────────────────────────────────────────
# Claude Code OAuth (Max 구독) 사용. API 키 결제 없음. provider 선택 불필요 — claude_cli 만.
LLM_PROVIDER           = "claude_cli"
CLAUDE_CLI_MODEL       = os.environ.get("CLAUDE_CLI_MODEL", "haiku")
CLAUDE_CLI_TIMEOUT_SEC = int(os.environ.get("CLAUDE_CLI_TIMEOUT_SEC", "120"))

# ─── 저장소 (SQLite) ─────────────────────────────────────────────────────────
SQLITE_PATH = str(ROOT / "data" / "kor_fin_news.sqlite")

# ─── Reference / 평가 ────────────────────────────────────────────────────────
# 한 번 LLM 호출 시 프롬프트에 주입할 reference 기사 제목 수
REFERENCE_SAMPLE_SIZE = int(os.environ.get("REFERENCE_SAMPLE_SIZE", "30"))

LLM_SCORE_THRESHOLD = 6.5
TOP_N_REPORT        = 10

# ─── 출력 ────────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_KOR_FIN", "")

# ─── 스케줄 ──────────────────────────────────────────────────────────────────
SCHEDULE_HOUR   = 8
SCHEDULE_MINUTE = 0
