"""모델 alias → 정식 모델명 변환 + provider 매칭."""

from __future__ import annotations


# Claude CLI
_CLAUDE_ALIASES = {
    "opus": "opus",
    "sonnet": "sonnet",
    "haiku": "haiku",
    "claude-opus-4.7": "opus",
    "claude-opus-4-7": "opus",
    "claude-sonnet-4.6": "sonnet",
    "claude-sonnet-4-6": "sonnet",
}

# Codex CLI (gpt-5.4 / gpt-5.4-mini / gpt-5.5 등)
_CODEX_ALIASES = {
    "gpt-5.4": "gpt-5.4",
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt-5.4-nano": "gpt-5.4-nano",
    "gpt-5.5": "gpt-5.5",
    "gpt-5-mini": "gpt-5.4-mini",   # 호환
    "5.4": "gpt-5.4",
    "5.4-mini": "gpt-5.4-mini",
    "mini": "gpt-5.4-mini",
}

# Gemini
_GEMINI_ALIASES = {
    "gemini-2.5-flash": "gemini-2.5-flash",
    "gemini-2.5-pro": "gemini-2.5-pro",
    "gemini-flash": "gemini-2.5-flash",
    "flash": "gemini-2.5-flash",
}

# DeepSeek (Playwright 무료 웹 채팅)
# V3 (chat) → R1 (reasoner) → V3.1 → V3.2/R2 → V4 → V4 Pro
_DEEPSEEK_ALIASES = {
    # V3 계열 (일반 대화)
    "deepseek-chat": "deepseek-chat",
    "v3": "deepseek-chat",
    "chat": "deepseek-chat",
    # R1 계열 (추론)
    "deepseek-reasoner": "deepseek-reasoner",
    "deepseek-r1": "deepseek-reasoner",
    "r1": "deepseek-reasoner",
    "reasoner": "deepseek-reasoner",
    # V4 계열 (2026 최신)
    "deepseek-v4": "deepseek-v4",
    "v4": "deepseek-v4",
    # V4 Pro (최상위 추론, 권장)
    "deepseek-v4-pro": "deepseek-v4-pro",
    "v4-pro": "deepseek-v4-pro",
    "v4pro": "deepseek-v4-pro",
    "pro": "deepseek-v4-pro",
}


def normalize_model(provider: str, model: str) -> str:
    """provider별 alias를 정식 모델명으로 변환."""
    p = (provider or "").lower().strip()
    m = (model or "").lower().strip()
    if p in ("claude", "anthropic", "claude-cli"):
        return _CLAUDE_ALIASES.get(m, m or "opus")
    if p in ("codex", "openai", "codex-cli"):
        return _CODEX_ALIASES.get(m, m or "gpt-5.4-mini")
    if p in ("gemini", "google", "google-genai"):
        return _GEMINI_ALIASES.get(m, m or "gemini-2.5-flash")
    if p in ("deepseek", "deepseek-playwright"):
        return _DEEPSEEK_ALIASES.get(m, m or "deepseek-reasoner")
    return model
