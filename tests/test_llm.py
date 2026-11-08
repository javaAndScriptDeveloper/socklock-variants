import json
import subprocess

from socklock_variants.config import Settings
from socklock_variants.generator import REVISION_SCHEMA, VARIANTS_SCHEMA, generate, revise
from socklock_variants.llm import CliLLM
from socklock_variants.script import parse_script
from tests.fakes import FakeLLM, variants_json

SCRIPT = parse_script('W1\nHOOK 0-2.5s | VO: "Lost a sock?"\nCTA 2.5-6s | VO: "Buy"')


def test_generate_and_revise_request_structured_output():
    llm = FakeLLM([variants_json(("HOOK", "pain", "Sock gone again?"))])
    v = generate(SCRIPT, 1, llm, Settings())[0]
    assert llm.calls[0]["schema"] == VARIANTS_SCHEMA
    reply = json.dumps({"reply": "ok", "variant": {"element": "HOOK", "angle": "pain", "text": "Gone again?",
                                                   "adjacent": None, "why": ""}})
    llm2 = FakeLLM([reply])
    revise(SCRIPT, v, [], "shorter", llm2, Settings(), {v.name})
    assert llm2.calls[0]["schema"] == REVISION_SCHEMA


def test_schemas_require_variant_fields():
    item = VARIANTS_SCHEMA["properties"]["variants"]["items"]
    assert set(item["required"]) == {"element", "angle", "text", "adjacent", "why"}
    assert item["properties"]["element"]["enum"] == ["HOOK", "FIRSTLINE", "ONSCREEN"]


def test_cli_passes_schema_and_returns_structured_output(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        out = {"is_error": False, "result": "prose", "structured_output": {"variants": []}}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    text = CliLLM(Settings()).complete("sys", [{"role": "user", "content": "hi"}], schema={"type": "object"})
    assert json.loads(text) == {"variants": []}
    i = seen["cmd"].index("--json-schema")
    assert json.loads(seen["cmd"][i + 1]) == {"type": "object"}


def test_cli_uses_configured_effort(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"is_error": False, "result": "x"}), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    CliLLM(Settings(effort="medium")).complete("sys", [{"role": "user", "content": "hi"}])
    i = seen["cmd"].index("--effort")
    assert seen["cmd"][i + 1] == "medium"
