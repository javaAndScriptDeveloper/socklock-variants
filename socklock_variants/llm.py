"""LLM backends.

- ApiLLM: Claude API via the official SDK (what the web version uses in production).
- CliLLM: local `claude -p` (headless Claude Code) so tests/evals run on a subscription
  instead of API tokens.
Both expose the same `complete(system, messages) -> str`.
"""

import json
import subprocess
from typing import Protocol

from .config import Settings


class LLM(Protocol):
    def complete(self, system: str, messages: list[dict], schema: dict | None = None) -> str: ...


class ApiLLM:
    def __init__(self, settings: Settings):
        import anthropic

        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
        self.model = settings.model

    def complete(self, system: str, messages: list[dict], schema: dict | None = None) -> str:
        output_config: dict = {"effort": "low"}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            # The system prompt is identical for every call: cache it.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_config=output_config,
        )
        return "".join(b.text for b in response.content if b.type == "text")


class CliLLM:
    def __init__(self, settings: Settings, timeout: int = 300):
        self.model = settings.model
        self.timeout = timeout

    @staticmethod
    def transcript(messages: list[dict]) -> str:
        """`claude -p` takes one prompt, so earlier turns are replayed as a transcript."""
        if len(messages) == 1:
            return messages[0]["content"]
        parts = []
        for m in messages[:-1]:
            who = "DESIGNER" if m["role"] == "user" else "YOU (earlier answer)"
            parts.append(f"<{who}>\n{m['content']}\n</{who}>")
        parts.append(f"Now answer this latest message:\n{messages[-1]['content']}")
        return "\n\n".join(parts)

    def complete(self, system: str, messages: list[dict], schema: dict | None = None) -> str:
        cmd = [
            "claude", "-p",
            "--model", self.model,
            "--system-prompt", system,
            "--output-format", "json",
            "--tools", "",
            "--no-session-persistence",
            "--strict-mcp-config",
        ]
        if schema:
            cmd += ["--json-schema", json.dumps(schema)]
        proc = subprocess.run(
            cmd, input=self.transcript(messages), capture_output=True, text=True, timeout=self.timeout
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude -p failed: {proc.stderr.strip() or proc.stdout.strip()}")
        data = json.loads(proc.stdout)
        if data.get("is_error"):
            raise RuntimeError(f"claude -p error: {data.get('result')}")
        if data.get("structured_output") is not None:
            return json.dumps(data["structured_output"])
        return data["result"]


def make_llm(settings: Settings) -> LLM:
    if settings.llm_backend == "api":
        return ApiLLM(settings)
    if settings.llm_backend == "cli":
        return CliLLM(settings)
    raise ValueError(f"Unknown LLM_BACKEND={settings.llm_backend!r} (use api or cli)")
