"""LLM wrapper 공통 헬퍼."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)


@dataclass
class LLMUsage:
    """단일 LLM 호출의 토큰 사용량 + 비용.

    제공자별 의미:
    - Claude CLI: --output-format json의 usage 필드. cache_* 토큰 별도 추적.
    - Codex CLI: turn.completed.usage에서 input/output/reasoning 토큰.
    - Gemini API: response.usage_metadata에서 prompt/candidates 토큰.
    """
    provider: str = ""           # "claude-cli" | "codex-cli" | "gemini"
    model: str = ""              # 정식 모델명
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0   # Claude/Codex만
    cache_creation_tokens: int = 0  # Claude만
    reasoning_tokens: int = 0    # Codex/o-series만
    total_tokens: int = 0        # input + output (캐시 포함 안 함)
    cost_usd: float = 0.0        # Claude CLI는 직접 제공
    duration_ms: int = 0         # 응답 시간

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens or (self.input_tokens + self.output_tokens),
            "cost_usd": round(self.cost_usd, 6),
            "duration_ms": self.duration_ms,
        }


def format_messages_to_text(messages: Iterable[BaseMessage]) -> tuple[str, str]:
    """langchain messages를 (system_prompt, user_prompt) 튜플로 변환.

    CLI subprocess는 single-shot prompt만 받으므로 messages를
    하나의 system + 하나의 user로 압축한다.

    여러 SystemMessage가 있으면 줄바꿈으로 합치고, AIMessage도 user 영역에
    "이전 답변:" 라벨로 포함한다.
    """
    system_parts: list[str] = []
    user_parts: list[str] = []

    for msg in messages:
        content = _content_to_text(msg.content)
        if isinstance(msg, SystemMessage):
            system_parts.append(content)
        elif isinstance(msg, AIMessage):
            user_parts.append(f"[이전 응답]\n{content}")
        else:  # HumanMessage 등
            user_parts.append(content)

    system_prompt = "\n\n".join(p.strip() for p in system_parts if p.strip())
    user_prompt = "\n\n".join(p.strip() for p in user_parts if p.strip())
    return system_prompt, user_prompt


def merge_to_single_prompt(messages: Iterable[BaseMessage]) -> str:
    """system + user를 하나의 텍스트로 (CLI에 stdin으로 줄 때)."""
    system, user = format_messages_to_text(messages)
    if system and user:
        return f"{system}\n\n---\n\n{user}"
    return system or user


def _content_to_text(content) -> str:
    """OpenAI/Google list-typed content blocks를 평면 텍스트로 정규화."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif "text" in block:
                    parts.append(block["text"])
        return "\n".join(p for p in parts if p)
    return str(content)
