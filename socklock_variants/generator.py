"""Script -> variants: prompt the model, parse JSON, check, regenerate failures once, name."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
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


CHUNK_SIZE = 5  # variants per parallel call
STRONG_ANGLES = ["pain", "number", "demo", "humor", "curiosity", "question"]
WEAK_ANGLES = ["contrarian", "social_proof"]  # hard in a few seconds: at most once per batch
ELEMENT_CYCLE = ["HOOK", "HOOK", "FIRSTLINE", "ONSCREEN"]  # 50% / 25% / 25%


def plan_slots(count: int) -> list[tuple[str, str]]:
    """Decide up front which element and angle each variant gets.

    Diversity is guaranteed by code, which also lets the batch be split into
    independent parallel calls without them repeating each other's angles.
    """
    angles: list[str] = []
    strong = 0
    for i in range(count):
        if count >= 8 and i in (6, 7):
            angles.append(WEAK_ANGLES[i - 6])
        else:
            angles.append(STRONG_ANGLES[strong % len(STRONG_ANGLES)])
            strong += 1
    return [(ELEMENT_CYCLE[i % len(ELEMENT_CYCLE)], a) for i, a in enumerate(angles)]


def _slot_lines(slots: list[tuple[int, str, str]]) -> str:
    return "\n".join(f"{n}. {e} — {a}" for n, e, a in slots)


def _write_chunk(script: Script, slots: list[tuple[int, str, str]], llm: LLM) -> list[Variant]:
    request = (
        f"Winning script:\n\n{script.to_text()}\n\n"
        f"Write exactly {len(slots)} variants, one per line of this plan, in this order "
        f"(element — angle):\n{_slot_lines(slots)}\n\nJSON only."
    )
    answer = llm.complete(SYSTEM_PROMPT, [{"role": "user", "content": request}], schema=VARIANTS_SCHEMA)
    return _parse_variants(answer)[: len(slots)]


def generate(script: Script, count: int, llm: LLM, settings: Settings) -> list[Variant]:
    plan = plan_slots(count)
    numbered = [(i + 1, e, a) for i, (e, a) in enumerate(plan)]
    chunks = [numbered[i:i + CHUNK_SIZE] for i in range(0, count, CHUNK_SIZE)]

    slots: list[Variant | None] = [None] * count
    with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
        for chunk, got in zip(chunks, pool.map(lambda c: _write_chunk(script, c, llm), chunks)):
            for (n, _, _), v in zip(chunk, got):
                slots[n - 1] = v

    present = [v for v in slots if v]
    _check_all(present, script, settings)
    redo = [i for i, v in enumerate(slots) if v is None or v.issues]
    if redo:
        # One follow-up call for everything that failed or is missing, aware of the rest.
        keep = "\n".join(f"- {v.text}" for v in slots if v and not v.issues)
        lines = []
        for i in redo:
            e, a = plan[i]
            why = f"failed: {', '.join(slots[i].issues)} (\"{slots[i].text}\")" if slots[i] else "missing"
            lines.append(f"#{i + 1} {e} — {a}: {why}")
        missing = sum(slots[i] is None for i in redo)
        request = (
            f"Winning script:\n\n{script.to_text()}\n\n"
            + (f"Already accepted (do not repeat their openings or ideas):\n{keep}\n\n" if keep else "")
            + "These slots need a new variant:\n" + "\n".join(lines) + "\n\n"
            + (f"That is {len(redo) - missing} replacement(s) and {missing} more new variant(s). " if missing
               else "")
            + f"Write exactly {len(redo)} variants in the order listed. "
            "Timing: voice-over 2.5 words per second; on-screen max 7 words. No risky claims. JSON only."
        )
        answer = llm.complete(SYSTEM_PROMPT, [{"role": "user", "content": request}], schema=VARIANTS_SCHEMA)
        fresh = _parse_variants(answer)
        for i in redo:
            if fresh:
                slots[i] = fresh.pop(0)

    variants = [v for v in slots if v]
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
