"""Deterministic checks on generated variants. No LLM here, so results are explainable."""

import math
import re
from difflib import SequenceMatcher

from .config import Settings
from .models import Variant
from .script import Script

# Claims Meta review or our legal would push back on. Extend freely.
RISKY_TERMS = [
    "guaranteed", "guarantee", "100%", "forever", "never lose", "never again",
    "cure", "cures", "clinically", "doctor", "medical", "best in the world",
    "#1", "number one", "risk-free",
]

# Which segment each element lives in.
ELEMENT_SEGMENT = {"HOOK": 0, "ONSCREEN": 0, "FIRSTLINE": 1}

NEAR_DUPLICATE_RATIO = 0.85


def _words(text: str) -> list[str]:
    return re.findall(r"[\w'’%#$-]+", text)


def _norm(text: str) -> str:
    return " ".join(w.lower() for w in re.findall(r"[\w'’]+", text))


def _segment_index(element: str, script: Script) -> int:
    return min(ELEMENT_SEGMENT.get(element, 0), len(script.segments) - 1)


def _risky(text: str) -> list[str]:
    low = text.lower()
    found = []
    for term in RISKY_TERMS:
        if term[0].isalnum() and term[-1].isalnum():
            hit = re.search(rf"\b{re.escape(term)}\b", low)
        else:
            hit = term in low
        if hit:
            found.append(term)
    return found


def check_variant(v: Variant, script: Script, settings: Settings) -> list[str]:
    """Return issue codes; also fills v.words / v.seconds. Does not mutate v.issues."""
    issues: list[str] = []
    n = len(_words(v.text))
    v.words = n

    if v.element == "ONSCREEN":
        v.seconds = None
        if n > settings.onscreen_max_words:
            issues.append("timing")
    else:
        v.seconds = round(n / settings.words_per_second, 1)
        seg = script.segments[_segment_index(v.element, script)]
        slot = seg.seconds or settings.default_hook_seconds
        if n > math.floor(slot * settings.words_per_second + 1e-9):
            issues.append("timing")

    issues += [f"risky:{t}" for t in _risky(v.text)]
    if v.adjacent:
        issues += [f"risky:{t}" for t in _risky(v.adjacent.get("text", ""))
                   if f"risky:{t}" not in issues]

    if v.adjacent:
        names = [s.name for s in script.segments]
        target = v.adjacent.get("segment", "")
        own = _segment_index(v.element, script)
        if target not in names or abs(names.index(target) - own) > 1:
            issues.append("scope")

    return issues


def check_diversity(variants: list[Variant]) -> dict[str, list[str]]:
    """Flag later variants that repeat an earlier opening or are near-copies."""
    result: dict[str, list[str]] = {v.name: [] for v in variants}
    seen: list[tuple[str, str]] = []  # (normalized text, first 3 words)
    for v in variants:
        norm = _norm(v.text)
        opening = " ".join(norm.split()[:3])
        if any(opening == o for _, o in seen):
            result[v.name].append("duplicate_opening")
        if any(SequenceMatcher(None, norm, t).ratio() > NEAR_DUPLICATE_RATIO for t, _ in seen):
            result[v.name].append("near_duplicate")
        seen.append((norm, opening))
    return result
