"""Script -> variants: prompt the model, parse JSON, check, regenerate failures once, name."""

import json
import logging
from pathlib import Path

from .checks import check_diversity, check_variant
from .config import Settings
from .llm import LLM
from .models import ELEMENTS, Variant
from .naming import make_name, revision_name
from .script import Script

log = logging.getLogger(__name__)

# Structured output: the model is constrained to this shape, so answers always parse.
_ADJACENT = {
    "anyOf": [
        {"type": "null"},
        {
            "type": "object",
            "properties": {
                "segment": {"type": "string"},
                "field": {"type": "string", "enum": ["vo", "onscreen"]},
                "text": {"type": "string"},
            },
            "required": ["segment", "field", "text"],
            "additionalProperties": False,
        },
    ]
}
_VARIANT = {
    "type": "object",
    "properties": {
        "element": {"type": "string", "enum": list(ELEMENTS)},
        "angle": {"type": "string"},
        "text": {"type": "string"},
        "adjacent": _ADJACENT,
        "why": {"type": "string"},
    },
    "required": ["element", "angle", "text", "adjacent", "why"],
    "additionalProperties": False,
}
VARIANTS_SCHEMA = {
    "type": "object",
    "properties": {"variants": {"type": "array", "items": _VARIANT}},
    "required": ["variants"],
    "additionalProperties": False,
}
REVISION_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, "variant": _VARIANT},
    "required": ["reply", "variant"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")


def extract_json(text: str) -> dict:
    """Parse the first JSON object in `text`, tolerating ```json fences and prose around it."""
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("no JSON object in model answer")


def _to_variant(item: dict) -> Variant | None:
    if not isinstance(item, dict) or not str(item.get("text", "")).strip():
        return None
    element = str(item.get("element", "HOOK")).upper().replace("-", "").replace("_", "")
    element = element if element in ELEMENTS else "HOOK"
    adjacent = item.get("adjacent")
    if not (isinstance(adjacent, dict) and adjacent.get("text")):
        adjacent = None
    return Variant(
        name="",
        element=element,
        angle=str(item.get("angle") or "misc").lower(),
        text=str(item["text"]).strip(),
        adjacent=adjacent,
        why=str(item.get("why", "")),
    )


def _parse_variants(answer: str) -> list[Variant]:
    try:
        items = extract_json(answer).get("variants", [])
    except ValueError:
        items = []
    if not items:
        log.warning("no variants parsed from model answer (%d chars): %r", len(answer), answer[:500])
        return []
    return [v for v in (_to_variant(i) for i in items if isinstance(items, list)) if v]


def _check_all(variants: list[Variant], script: Script, settings: Settings) -> None:
    for v in variants:
        v.issues = check_variant(v, script, settings)
    # diversity needs stable keys; use positions until real names exist
    for i, v in enumerate(variants):
        v.name = v.name or f"#{i + 1}"
    for v in variants:
        v.issues += check_diversity(variants)[v.name]


def generate(script: Script, count: int, llm: LLM, settings: Settings) -> list[Variant]:
    request = (
        f"Winning script:\n\n{script.to_text()}\n\n"
        f"Write {count} variants. JSON only."
    )
    messages = [{"role": "user", "content": request}]
    answer = llm.complete(SYSTEM_PROMPT, messages, schema=VARIANTS_SCHEMA)
    variants = _parse_variants(answer)[:count]
    _check_all(variants, script, settings)

    failing = [i for i, v in enumerate(variants) if v.issues]
    missing = count - len(variants)
    if failing or missing:
        lines = []
        if not variants:
            lines.append("Your answer could not be parsed as the JSON shape asked for.")
        for i in failing:
            lines.append(f"#{i + 1} \"{variants[i].text}\" failed: {', '.join(variants[i].issues)}")
        ask = []
        if failing:
            ask.append(f"replacements for {', '.join(f'#{i + 1}' for i in failing)} in that order")
        if missing:
            ask.append(f"{missing} more new variants")
        lines.append("Write " + " and ".join(ask) + ". Same JSON shape, only the new variants.")
        lines.append("Timing: voice-over 2.5 words per second; on-screen max 7 words. No risky claims.")
        messages += [{"role": "assistant", "content": answer}, {"role": "user", "content": "\n".join(lines)}]

        fresh = _parse_variants(llm.complete(SYSTEM_PROMPT, messages, schema=VARIANTS_SCHEMA))
        for i in failing:
            if fresh:
                variants[i] = fresh.pop(0)
        variants += fresh[:missing]

    for v in variants:
        v.name = ""
    _check_all(variants, script, settings)
    for i, v in enumerate(variants, start=1):
        v.name = make_name(script.winner_id, v.element, v.angle, i)
    return variants


def revise(
    script: Script,
    variant: Variant,
    history: list[dict],
    comment: str,
    llm: LLM,
    settings: Settings,
    existing_names: set[str],
) -> tuple[str, Variant]:
    """One chat turn on a variant. Appends the turn to `history` (the per-variant chat)."""
    if not history:
        content = (
            f"Winning script:\n\n{script.to_text()}\n\n"
            f"Variant {variant.name}:\n{json.dumps(_public(variant), ensure_ascii=False)}\n\n"
            f"Designer's comment: {comment}\n\nRevise this one variant. JSON only."
        )
    else:
        content = f"Designer's comment: {comment}\n\nRevise the latest version. JSON only."
    messages = history + [{"role": "user", "content": content}]
    answer = llm.complete(SYSTEM_PROMPT, messages, schema=REVISION_SCHEMA)

    try:
        data = extract_json(answer)
        new = _to_variant(data.get("variant") or {})
        reply = str(data.get("reply", "")).strip()
    except ValueError:
        new, reply = None, ""
    if new is None:
        raise ValueError("The model did not return a revised variant — try rephrasing the comment.")

    new.issues = check_variant(new, script, settings)
    new.name = revision_name(variant.name, existing_names)
    history += [{"role": "user", "content": content}, {"role": "assistant", "content": answer}]
    return reply or "Updated.", new


def _public(v: Variant) -> dict:
    return {k: v.to_dict()[k] for k in ("element", "angle", "text", "adjacent", "why")}
