"""기사 평가기.

리팩토링됨: sentence-transformers / chromadb / 임베딩 모두 제거.
이제 Claude CLI Haiku 한 번 호출로 relevant 판정 + 점수 + 요약 + 키워드 통합.
"""
import json
import logging
import re
import traceback
import requests
from typing import Optional

from config import (
    CLAUDE_CLI_MODEL,
    CLAUDE_CLI_TIMEOUT_SEC,
    DISCORD_WEBHOOK_URL,
    LLM_SCORE_THRESHOLD,
    REFERENCE_SAMPLE_SIZE,
    TOP_N_REPORT,
)
from prompts import build_scoring_prompt
from reference_loader import sample_reference_titles

logger = logging.getLogger(__name__)

_llm_instance = None
_error_notify_count: int = 0
_ERROR_NOTIFY_LIMIT: int = 3


def _extract_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # ```json ... ``` 같은 펜스 제거 시도
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    # 가장 큰 { ... } 블록
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _notify_error(stage: str, exc: Exception) -> None:
    global _error_notify_count
    if not DISCORD_WEBHOOK_URL:
        return
    if _error_notify_count >= _ERROR_NOTIFY_LIMIT:
        if _error_notify_count == _ERROR_NOTIFY_LIMIT:
            try:
                requests.post(
                    DISCORD_WEBHOOK_URL,
                    json={"content": f"⚠️ 에러 {_ERROR_NOTIFY_LIMIT}회 이상 반복 — 이후 알림 생략"},
                    timeout=10,
                )
            except Exception:
                pass
        _error_notify_count += 1
        return
    _error_notify_count += 1
    try:
        tb = traceback.format_exc()[:1200]
        msg = (
            f"⚠️ **kor_fin_news 에러 #{_error_notify_count}/{_ERROR_NOTIFY_LIMIT}** ({stage})\n"
            f"```\n{type(exc).__name__}: {exc}\n\n{tb}\n```"
        )
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=10)
    except Exception as notify_exc:
        logger.error("Discord 에러 알림 전송 실패: %s", notify_exc)


def _get_llm():
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance
    from llm.claude_cli_chat import ClaudeCLIChat
    logger.info("Claude CLI 초기화 (model=%s)", CLAUDE_CLI_MODEL)
    _llm_instance = ClaudeCLIChat(
        model=CLAUDE_CLI_MODEL,
        timeout_sec=CLAUDE_CLI_TIMEOUT_SEC,
    )
    return _llm_instance


def _call_llm(prompt: str) -> Optional[dict]:
    from langchain_core.messages import SystemMessage, HumanMessage
    system_msg = (
        "당신은 한국 금융 뉴스 평가 전문가입니다. "
        "주어진 기사를 분석하고 반드시 JSON 형식으로만 응답하세요."
    )
    try:
        llm = _get_llm()
        result = llm.invoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=prompt),
        ])
        raw = result.content or ""
        return _extract_json(raw)
    except Exception as e:
        logger.error("LLM 호출 실패: %s", e)
        msg_lower = str(e).lower()
        if any(k in msg_lower for k in ("로그인", "login", "타임아웃", "timeout", "차단", "blocked", "auth")):
            _notify_error("LLM 호출 실패 (인증/세션 점검 필요)", e)
        return None


def score_article(title: str, body: str, reference_titles: list[str]) -> Optional[dict]:
    prompt = build_scoring_prompt(title, body, reference_titles)
    result = _call_llm(prompt)
    if result is None:
        logger.warning("JSON 파싱 실패 — 1회 재시도")
        result = _call_llm(prompt)
    if result is None:
        logger.warning("LLM 파싱 최종 실패, 스킵: %.60s", title)
    return result


def _final_score(relevant: bool, llm_score: float, kw_score: float) -> float:
    """복합 점수: relevance gate + LLM 점수 + 키워드 점수.

    Old (sim*0.4 + llm*0.4 + kw*0.2) 에서
    sim 을 relevant (0/1) 로 대체:
      relevant=True → 0.4 (만점)
      relevant=False → 0.0
    """
    if not relevant:
        return 0.0
    kw_norm = min(kw_score / 10.0, 1.0)
    return 0.4 + (llm_score / 10.0) * 0.4 + kw_norm * 0.2


def evaluate_articles_with_fallback(
    articles: list[dict],
) -> tuple[list[dict], list[dict]]:
    passing: list[dict] = []
    scored_candidates: list[dict] = []

    relevant_count = 0
    llm_passed = 0

    # reference 제목 샘플 1회 추출 (모든 기사가 같은 reference 셋과 비교)
    reference_titles = sample_reference_titles(n=REFERENCE_SAMPLE_SIZE)
    logger.info("Reference titles loaded: %d", len(reference_titles))

    for art in articles:
        kw_score = art.get("kw_score", 0.0)

        # 단일 LLM 호출 (relevant + score + summary + keywords)
        llm_result = score_article(art["title"], art["body"], reference_titles)
        if llm_result is None:
            continue

        relevant = bool(llm_result.get("relevant", True))
        llm_score = float(llm_result.get("score", 0))
        summary = llm_result.get("summary", [])
        keywords = llm_result.get("keywords", [])

        art["relevant"] = relevant
        art["similarity"] = 1.0 if relevant else 0.0  # 하위호환: storage/report 가 참조
        art["score"] = llm_score
        art["summary"] = summary if isinstance(summary, list) else [summary]
        art["keywords"] = keywords if isinstance(keywords, list) else [keywords]
        art["final_score"] = _final_score(relevant, llm_score, kw_score)

        if not relevant:
            logger.debug("[RELEVANT FAIL] kw=%.1f | %.60s", kw_score, art["title"])
            continue

        relevant_count += 1
        scored_candidates.append(art)
        logger.info(
            "[RELEVANT] llm=%.1f kw=%.1f final=%.3f | %.60s",
            llm_score, kw_score, art["final_score"], art["title"]
        )

        if llm_score < LLM_SCORE_THRESHOLD:
            continue

        llm_passed += 1
        passing.append(art)

    passing.sort(key=lambda x: x["final_score"], reverse=True)
    scored_candidates.sort(key=lambda x: x["final_score"], reverse=True)
    fallback_reports = scored_candidates[:TOP_N_REPORT]

    logger.info(
        "평가 완료 — relevant=%d / llm_passed=%d / total=%d (fallback=%d)",
        relevant_count, llm_passed, len(articles), len(scored_candidates)
    )
    return passing, fallback_reports


def evaluate_articles(articles: list[dict]) -> list[dict]:
    passing, _ = evaluate_articles_with_fallback(articles)
    return passing
