"""Claude Code CLI(`claude -p`)를 langchain BaseChatModel로 wrapping.

API 키 결제 없음 — Max 5x OAuth 세션 사용.
기존 decision_engine/claude_cli.py 로직 재활용.

`--output-format json` 사용해서 응답 + 토큰 usage + cost 동시 획득.
"""

from __future__ import annotations

import asyncio
import json as _json
import shutil
import time
from typing import Any, Iterator, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict

from .base import LLMUsage, merge_to_single_prompt
from .model_catalog import normalize_model


# 시스템 프롬프트 오버헤드 최소화
# 기본 Claude Code 시스템 프롬프트(24K 토큰, 도구/MCP/CLAUDE.md 등)를 이걸로 대체.
# 평가 도메인 가이드는 user prompt(build_scoring_prompt)에 이미 포함되어 있음.
MINIMAL_SYSTEM_PROMPT = (
    "You are a financial news scoring assistant. "
    "Respond with a single valid JSON object only — "
    "no markdown, no commentary, no code fences."
)


class ClaudeCLIChat(BaseChatModel):
    """Claude Code CLI subprocess wrapper. API key 없음, OAuth 사용.

    사용 예:
        llm = ClaudeCLIChat(model="opus", timeout_sec=240)
        result = llm.invoke([SystemMessage("..."), HumanMessage("...")])
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str = "opus"               # opus | sonnet | haiku
    timeout_sec: int = 240
    cli_path: Optional[str] = None    # None이면 PATH에서 자동 탐지

    # 마지막 호출 사용량 (외부에서 읽기 위함).
    last_usage: Optional[LLMUsage] = None

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        prompt = merge_to_single_prompt(messages)
        text, usage = asyncio.run(self._call_subprocess(prompt))
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
        # 단순 fallback: 한 번에 generate한 결과를 yield
        result = self._generate(messages, stop, run_manager, **kwargs)
        for gen in result.generations:
            yield gen

    async def _call_subprocess(self, prompt: str) -> tuple[str, Optional[LLMUsage]]:
        cli = self.cli_path or shutil.which("claude")
        if not cli:
            raise RuntimeError("Claude CLI not found on PATH (set cli_path)")

        model_arg = normalize_model("claude", self.model)
        # --output-format json으로 응답 + 토큰 usage + cost 동시 획득
        # 추가 플래그 5종으로 시스템 프롬프트 오버헤드 99% 제거 (OAuth/Max 구독은 유지):
        #   --system-prompt:                          기본 시스템 프롬프트 교체 (24K → 30 토큰)
        #   --tools "":                                도구 정의 제거 (~5K 토큰)
        #   --disable-slash-commands:                  skill 정의 제거 (~1K 토큰)
        #   --strict-mcp-config:                       MCP 정의 무시
        #   --exclude-dynamic-system-prompt-sections:  cwd/env/git 동적 부분 제거
        cmd = [
            cli,
            "-p",
            "--output-format", "json",
            "--no-session-persistence",
            "--model", model_arg,
            "--system-prompt", MINIMAL_SYSTEM_PROMPT,
            "--tools", "",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--exclude-dynamic-system-prompt-sections",
        ]

        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=self.timeout_sec,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            await proc.wait()
            raise RuntimeError(f"Claude CLI timeout after {self.timeout_sec}s (model={model_arg})")
        elapsed_ms = int((time.time() - t0) * 1000)

        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            raise RuntimeError(
                f"Claude CLI exit {proc.returncode} (model={model_arg}): {stderr or '(no stderr)'}"
            )
        if not stdout.strip():
            raise RuntimeError(f"Claude CLI empty output (model={model_arg}, stderr: {stderr})")

        # JSON 응답 파싱
        try:
            payload = _json.loads(stdout.strip())
        except _json.JSONDecodeError:
            # JSON 모드인데 파싱 실패 → 원문 반환 (usage 없음)
            return stdout, LLMUsage(provider="claude-cli", model=model_arg, duration_ms=elapsed_ms)

        text = str(payload.get("result") or payload.get("response") or "")
        usage_block = payload.get("usage") or {}
        usage = LLMUsage(
            provider="claude-cli",
            model=model_arg,
            input_tokens=int(usage_block.get("input_tokens", 0)),
            output_tokens=int(usage_block.get("output_tokens", 0)),
            cache_read_tokens=int(usage_block.get("cache_read_input_tokens", 0)),
            cache_creation_tokens=int(usage_block.get("cache_creation_input_tokens", 0)),
            total_tokens=int(usage_block.get("input_tokens", 0)) + int(usage_block.get("output_tokens", 0)),
            cost_usd=float(payload.get("total_cost_usd", 0.0) or 0.0),
            duration_ms=int(payload.get("duration_ms", elapsed_ms) or elapsed_ms),
        )
        return text, usage
