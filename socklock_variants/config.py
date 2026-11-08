"""Settings loaded from environment / .env."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    llm_backend: str = "cli"  # "api" (Claude API) or "cli" (local `claude -p`)
    anthropic_api_key: str = ""
    model: str = "claude-sonnet-5-5"
    words_per_second: float = 2.5
    onscreen_max_words: int = 7
    default_hook_seconds: float = 2.5
    effort: str = "low"  # low | medium | high — same value for API and `claude -p`


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        llm_backend=os.getenv("LLM_BACKEND", "cli").strip().lower(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        model=os.getenv("MODEL", "claude-sonnet-5-5"),
        words_per_second=float(os.getenv("WORDS_PER_SECOND", "2.5")),
        onscreen_max_words=int(os.getenv("ONSCREEN_MAX_WORDS", "7")),
        default_hook_seconds=float(os.getenv("DEFAULT_HOOK_SECONDS", "2.5")),
        effort=os.getenv("EFFORT", "low").strip().lower(),
    )
