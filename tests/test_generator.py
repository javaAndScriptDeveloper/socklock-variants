import json

import pytest

from socklock_variants.config import Settings
from socklock_variants.generator import extract_json, generate, revise
from socklock_variants.script import parse_script
from tests.fakes import FakeLLM, variants_json

SCRIPT = parse_script('''W12 · Washer thief
HOOK 0-2.5s | VO: "Lost another sock?" | ON-SCREEN: "Your washer eats socks"
PROBLEM 2.5-7s | VO: "Every wash, one goes missing..."
CTA 7-12s | VO: "Get your first pack"
''')
S = Settings()


def test_extract_json_from_fences_and_prose():
    text = 'Here you go:\n```json\n{"variants": []}\n```\nEnjoy'
    assert extract_json(text) == {"variants": []}
    assert extract_json('noise {"a": {"b": 1}} trailing') == {"a": {"b": 1}}
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_generate_names_and_checks():
    llm = FakeLLM([variants_json(
        ("HOOK", "pain", "Washer ate one again?"),
        ("ONSCREEN", "humor", "Socks breaking up"),
        ("FIRSTLINE", "number", "One in five socks vanish"),
    )])
    out = generate(SCRIPT, 3, llm, S)
    assert [v.name for v in out] == ["W12_HOOK_pain_v01", "W12_ONSCREEN_humor_v02", "W12_FIRSTLINE_number_v03"]
    assert all(v.issues == [] for v in out)
    assert len(llm.calls) == 1
    assert "3" in llm.calls[0]["messages"][0]["content"]


def test_failures_and_shortfall_regenerated_once():
    first = variants_json(
        ("HOOK", "pain", "one two three four five six seven eight"),  # timing fail
        ("HOOK", "humor", "Socks breaking up?"),
    )
    second = variants_json(
        ("HOOK", "pain", "Washer thief strikes again"),
        ("HOOK", "demo", "Watch this sock click"),
    )
    llm = FakeLLM([first, second])
    out = generate(SCRIPT, 3, llm, S)
    assert len(llm.calls) == 2
    assert [v.text for v in out] == ["Washer thief strikes again", "Socks breaking up?", "Watch this sock click"]
    assert all(v.issues == [] for v in out)
    follow_up = llm.calls[1]["messages"][-1]["content"]
    assert "#1" in follow_up and "timing" in follow_up and "1 more" in follow_up


def test_still_failing_is_kept_with_issues():
    bad = variants_json(("HOOK", "proof", "Guaranteed to never lose socks"))
    llm = FakeLLM([bad, bad])
    out = generate(SCRIPT, 1, llm, S)
    assert len(llm.calls) == 2
    assert len(out) == 1
    assert "risky:guaranteed" in out[0].issues


def test_invalid_json_then_valid():
    llm = FakeLLM(["sorry, no", variants_json(("HOOK", "pain", "Lost one again?"))])
    out = generate(SCRIPT, 1, llm, S)
    assert [v.text for v in out] == ["Lost one again?"]


def test_revise_returns_revision_and_extends_history():
    base = generate(SCRIPT, 1, FakeLLM([variants_json(("HOOK", "proof", "Pairs that stay pairs"))]), S)[0]
    reply = json.dumps({"reply": "Removed the guarantee.", "variant": {
        "element": "HOOK", "angle": "proof", "text": "50,000 pairs, zero lost", "adjacent": None, "why": "x"}})
    llm = FakeLLM([reply])
    history = []
    msg, new = revise(SCRIPT, base, history, "remove guaranteed", llm, S, {base.name})
    assert msg == "Removed the guarantee."
    assert new.name == "W12_HOOK_proof_v01b"
    assert new.issues == []
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert "remove guaranteed" in llm.calls[0]["messages"][-1]["content"]
