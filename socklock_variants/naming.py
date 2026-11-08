"""UA naming convention: {winner}_{ELEMENT}_{angle}_v{NN}[revision letter]."""

import re
import string


def _slug(angle: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", angle.lower()).strip("_") or "misc"


def make_name(winner: str, element: str, angle: str, index: int) -> str:
    return f"{winner}_{element}_{_slug(angle)}_v{index:02d}"


def revision_name(name: str, existing: set[str]) -> str:
    base = re.sub(r"(_v\d+)[a-z]$", r"\1", name)
    for letter in string.ascii_lowercase[1:]:
        candidate = f"{base}{letter}"
        if candidate not in existing:
            return candidate
    raise ValueError(f"too many revisions of {base}")
