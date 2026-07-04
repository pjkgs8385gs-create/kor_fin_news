"""DeepSeek-R1 chat을 Playwright 브라우저 자동화로 wrapping.

API 키 없음 — chat.deepseek.com 무료 웹 채팅을 자동화.
launch_persistent_context로 사용자 프로필 재사용 (1회 수동 로그인 후 자동 복원).

사용 예:
    llm = DeepSeekPlaywrightChat(
        model="deepseek-reasoner",
        profile_dir="logs/playwright_profiles/deepseek",
        headless=True,
    )
    result = llm.invoke([SystemMessage("..."), HumanMessage("...")])

최초 1회: `python tools/setup_deepseek_login.py`로 수동 로그인.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any, Iterator, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict

from .base import LLMUsage, merge_to_single_prompt
from .model_catalog import normalize_model


# DeepSeek 웹 인터페이스 셀렉터 (chat.deepseek.com, 2026-05 한국어/영어 UI).
# UI 변경 시 이곳만 수정.
DEEPSEEK_URL = "https://chat.deepseek.com/"
SELECTORS = {
    # 입력 textarea
    "input_box": (
        'textarea#chat-input, '
        'textarea[placeholder*="DeepSeek"], '
        'textarea[placeholder*="메시지"], '
        'div[contenteditable="true"]'
    ),
    # 전송 버튼 (입력 후 Enter로도 가능)
    "send_button": 'div[role="button"][aria-label*="Send"], button[aria-label*="send" i]',
    # 모드 토글: "빠른"(Fast) / "전문가"(Expert/Pro/V4 Pro)
    # V4 Pro = 한국어 "전문가", 영어 "Expert" 또는 "Pro"
    "expert_mode_toggle": (
        'button:has-text("전문가"), '
        'div[role="button"]:has-text("전문가"), '
        'button:has-text("Expert"), '
        'button:has-text("Pro")'
    ),
    "fast_mode_toggle": (
        'button:has-text("빠른"), '
        'div[role="button"]:has-text("빠른"), '
        'button:has-text("Fast"), '
        'button:has-text("Quick")'
    ),
    # 추론 트레이스 토글: "깊은 생각" / "DeepThink"
    "deep_think_toggle": (
        'button:has-text("깊은 생각"), '
        'div[role="button"]:has-text("깊은 생각"), '
        'button:has-text("DeepThink"), '
        'button:has-text("Deep Think"), '
        'button:has-text("R1")'
    ),
    # 검색 토글 — quant 분석엔 OFF 권장
    "search_toggle": (
        'button:has-text("검색"), '
        'div[role="button"]:has-text("검색"), '
        'button:has-text("Search")'
    ),
    # 응답 컨테이너 (markdown body)
    "response": 'div.ds-markdown, div[class*="markdown"]',
    # 응답 진행 중 표시 (이게 사라지면 완료)
    "stop_indicator": 'div[class*="stop"], div[role="button"][aria-label*="Stop"]',
    # 로그인 필요 화면
    "login_required": 'button:has-text("Log in"), button:has-text("로그인")',
}

# 모델 매핑:
#   "빠른"(Fast)        ← V3 / chat / V4 base
#   "전문가"(Expert/Pro) ← V4 Pro 등 최상위
EXPERT_MODE_MODELS = {
    "deepseek-v4-pro", "deepseek-v4", "deepseek-reasoner",
    "v4-pro", "v4", "pro", "r1", "reasoner", "expert",
}
# "깊은 생각" 토글 활성화 대상 (reasoning trace 원할 때)
DEEP_THINK_MODELS = {
    "deepseek-v4-pro", "deepseek-reasoner", "v4-pro", "r1", "reasoner",
}

# 응답에서 reasoning trace 제거용 마커
REASONING_MARKERS = [
    "</think>",
    "</thinking>",
    "**최종 답변**",
    "**Final Answer**",
]


class DeepSeekPlaywrightChat(BaseChatModel):
    """DeepSeek 웹 채팅 (chat.deepseek.com) → BaseChatModel.

    인증: launch_persistent_context로 user_data_dir(Chrome 프로필) 재사용.
    최초 1회 `python tools/setup_deepseek_login.py`로 수동 로그인 필요.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str = "deepseek-reasoner"   # deepseek-chat | deepseek-reasoner (R1)
    timeout_sec: int = 300             # R1 reasoning이 길어질 수 있음
    profile_dir: Optional[str] = None  # 기본: logs/playwright_profiles/deepseek
    headless: bool = True              # 운영 true, 디버깅 false
    poll_interval: float = 1.0         # 응답 완료 폴링 주기(초)
    response_idle_sec: float = 3.0     # 응답 텍스트가 N초 변화 없으면 완료로 판단

    last_usage: Optional[LLMUsage] = None

    @property
    def _llm_type(self) -> str:
        return "deepseek-playwright"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        prompt = merge_to_single_prompt(messages)
        text, usage = asyncio.run(self._call_browser(prompt))
        self.last_usage = usage
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=text))],
            llm_output={"usage": usage.to_dict() if usage else None},
        )

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGeneration]:
        result = self._generate(messages, stop, run_manager, **kwargs)
        for gen in result.generations:
            yield gen

    def _resolve_profile_dir(self) -> Path:
        if self.profile_dir:
            p = Path(self.profile_dir)
        else:
            p = Path("logs/playwright_profiles/deepseek")
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()

    async def _call_browser(self, prompt: str) -> tuple[str, Optional[LLMUsage]]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright not installed. Run: pip install playwright && playwright install chromium"
            ) from exc

        # AWS WAF 우회: Stealth + 정식 chromium + 한국어 locale + Chrome UA
        # 데이터센터 IP에서 chat.deepseek.com 접속 시 필요. 로컬 Windows에선 옵션이지만
        # ARM/Linux 서버에선 거의 필수.
        try:
            from playwright_stealth import Stealth
            stealth_ctx = Stealth().use_async(async_playwright())
        except ImportError:
            # fallback: stealth 미설치 시 일반 모드 (로컬 dev에선 종종 충분)
            stealth_ctx = async_playwright()

        # 진짜 Chrome User-Agent (headless 감지 회피)
        REAL_UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )

        model_arg = normalize_model("deepseek", self.model)
        profile = self._resolve_profile_dir()
        t0 = time.time()

        async with stealth_ctx as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=self.headless,
                channel="chromium",  # 정식 chromium 빌드 (headless-shell 아님)
                viewport={"width": 1920, "height": 1080},
                user_agent=REAL_UA,
                locale="ko-KR",
                timezone_id="Asia/Seoul",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--lang=ko-KR",
                ],
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(DEEPSEEK_URL, timeout=30_000, wait_until="domcontentloaded")

                # 로그인 체크
                try:
                    await page.wait_for_selector(SELECTORS["input_box"], timeout=10_000)
                except Exception as exc:
                    if await page.query_selector(SELECTORS["login_required"]):
                        raise RuntimeError(
                            "DeepSeek 로그인 필요. `python tools/setup_deepseek_login.py` 실행 후 다시 시도."
                        ) from exc
                    raise RuntimeError(
                        f"DeepSeek 입력창을 찾을 수 없음 (UI 변경 가능성, 셀렉터 점검 필요): {exc}"
                    ) from exc

                model_lower = model_arg.lower()

                # 1) 전문가 모드 (V4 Pro 등) — 빠른/전문가 토글 중 전문가 선택
                if model_lower in EXPERT_MODE_MODELS:
                    try:
                        expert = await page.query_selector(SELECTORS["expert_mode_toggle"])
                        if expert:
                            # aria-pressed 또는 active 클래스로 활성 여부 판단
                            pressed = await expert.get_attribute("aria-pressed")
                            cls = (await expert.get_attribute("class")) or ""
                            is_active = (pressed == "true") or "active" in cls.lower() or "selected" in cls.lower()
                            if not is_active:
                                await expert.click()
                                await page.wait_for_timeout(400)
                    except Exception:
                        pass  # 토글 실패해도 기본 모드로 계속

                # 2) 깊은 생각 (DeepThink/R1 reasoning) — V4 Pro / R1 계열만
                if model_lower in DEEP_THINK_MODELS:
                    try:
                        deep = await page.query_selector(SELECTORS["deep_think_toggle"])
                        if deep:
                            pressed = await deep.get_attribute("aria-pressed")
                            cls = (await deep.get_attribute("class")) or ""
                            is_active = (pressed == "true") or "active" in cls.lower() or "selected" in cls.lower()
                            if not is_active:
                                await deep.click()
                                await page.wait_for_timeout(400)
                    except Exception:
                        pass

                # 3) 검색은 끄기 (quant 분석에 노이즈) — 활성 상태면 토글
                try:
                    search = await page.query_selector(SELECTORS["search_toggle"])
                    if search:
                        pressed = await search.get_attribute("aria-pressed")
                        cls = (await search.get_attribute("class")) or ""
                        is_active = (pressed == "true") or "active" in cls.lower() or "selected" in cls.lower()
                        if is_active:
                            await search.click()
                            await page.wait_for_timeout(300)
                except Exception:
                    pass

                # 메시지 전송
                input_el = await page.query_selector(SELECTORS["input_box"])
                if not input_el:
                    raise RuntimeError("DeepSeek 입력창 핸들을 못 얻음")
                await input_el.click()
                await input_el.fill(prompt)
                await page.keyboard.press("Enter")

                # 응답 대기 (idle 기반)
                response_text = await self._wait_for_response(page)

            finally:
                try:
                    await context.close()
                except Exception:
                    pass

        elapsed_ms = int((time.time() - t0) * 1000)

        # reasoning trace 제거
        cleaned = self._clean_response(response_text)

        # 토큰 사용량 추정 (실제 값 없음 — 길이 기반)
        usage = LLMUsage(
            provider="deepseek-playwright",
            model=model_arg,
            input_tokens=len(prompt) // 4,
            output_tokens=len(cleaned) // 4,
            duration_ms=elapsed_ms,
            cost_usd=0.0,  # 무료
        )
        return cleaned, usage

    async def _wait_for_response(self, page) -> str:
        """응답 컨테이너의 마지막 메시지가 N초 동안 변화 없으면 완료로 판단."""
        deadline = time.time() + self.timeout_sec
        last_text = ""
        last_change = time.time()

        while time.time() < deadline:
            try:
                # 마지막 응답 컨테이너 찾기
                elements = await page.query_selector_all(SELECTORS["response"])
                if not elements:
                    await asyncio.sleep(self.poll_interval)
                    continue
                last_el = elements[-1]
                current = (await last_el.inner_text()) or ""
            except Exception:
                await asyncio.sleep(self.poll_interval)
                continue

            if current and current != last_text:
                last_text = current
                last_change = time.time()

            # idle 시간이 충분하고 텍스트가 있으면 완료
            if last_text and (time.time() - last_change) >= self.response_idle_sec:
                # stop 인디케이터가 사라졌는지 추가 확인
                try:
                    stop_el = await page.query_selector(SELECTORS["stop_indicator"])
                    if stop_el is None:
                        return last_text
                except Exception:
                    return last_text

            await asyncio.sleep(self.poll_interval)

        if last_text:
            return last_text  # 타임아웃이지만 텍스트가 있으면 반환
        raise RuntimeError(f"DeepSeek 응답 타임아웃 ({self.timeout_sec}s)")

    @staticmethod
    def _clean_response(text: str) -> str:
        """reasoning trace를 제거하고 final answer만 추출."""
        if not text:
            return ""
        s = text.strip()

        # </think> 같은 마커 뒤만 사용
        for marker in REASONING_MARKERS:
            idx = s.lower().rfind(marker.lower())
            if idx >= 0:
                s = s[idx + len(marker):].strip()
                break

        # 코드 펜스 제거 (JSON 응답 케이스)
        s = re.sub(r"^```(?:json|javascript|js)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)

        return s.strip()
