"""Parse a winning ad script into timed segments.

Expected format (one segment per line, first line optional header):

    W12 · Washer thief
    HOOK 0-2.5s | VO: "Lost another sock?" | ON-SCREEN: "Your washer eats socks"
    PROBLEM 2.5-7s | VO: "Every wash, one goes missing..."

Anything that does not match is still accepted as a single SCRIPT segment.
"""

import re
from dataclasses import dataclass, field

QUOTES = "\"'“”‘’«»"

SEGMENT_RE = re.compile(
    r"^\s*(?P<name>[A-Z][A-Z_ ]*?)\s+(?P<start>\d+(?:[.,]\d+)?)\s*[-–—]\s*(?P<end>\d+(?:[.,]\d+)?)\s*s?\s*\|(?P<rest>.*)$"
)
WINNER_RE = re.compile(r"\b(W\d+)\b")
FIELD_RE = re.compile(r"^\s*(VO|ON[- ]?SCREEN)\s*:\s*(.*)$", re.IGNORECASE)


@dataclass
class Segment:
    name: str
    start: float | None
    end: float | None
    vo: str = ""
    onscreen: str = ""

    @property
    def seconds(self) -> float | None:
        if self.start is None or self.end is None:
            return None
        return round(self.end - self.start, 2)


@dataclass
class Script:
    winner_id: str
    title: str
    segments: list[Segment] = field(default_factory=list)
    raw: str = ""

    def to_text(self) -> str:
        """Canonical text form, used in prompts."""
        lines = [f"{self.winner_id} · {self.title}".strip(" ·")]
        for s in self.segments:
            timing = f" {s.start:g}-{s.end:g}s" if s.seconds is not None else ""
            parts = [f"{s.name}{timing}"]
            if s.vo:
                parts.append(f'VO: "{s.vo}"')
            if s.onscreen:
                parts.append(f'ON-SCREEN: "{s.onscreen}"')
            lines.append(" | ".join(parts))
        return "\n".join(lines)


def _clean(value: str) -> str:
    return value.strip().strip(QUOTES).strip()


def _num(value: str) -> float:
    return float(value.replace(",", "."))


def parse_script(text: str) -> Script:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line for line in text.split("\n") if line.strip()]

    segments: list[Segment] = []
    header_lines: list[str] = []
    for line in lines:
        m = SEGMENT_RE.match(line)
        if not m:
            if not segments:
                header_lines.append(line)
            continue
        seg = Segment(m["name"].strip(), _num(m["start"]), _num(m["end"]))
        for part in m["rest"].split("|"):
            f = FIELD_RE.match(part)
            if not f:
                continue
            if f[1].upper() == "VO":
                seg.vo = _clean(f[2])
            else:
                seg.onscreen = _clean(f[2])
        segments.append(seg)

    header = " ".join(header_lines)
    w = WINNER_RE.search(header) if segments else None
    winner = w[1] if w else "W00"

    if not segments:
        return Script("W00", "", [Segment("SCRIPT", None, None, vo=text)], raw=text)

    title = header.replace(winner, "", 1) if w else header
    title = title.strip().strip("·-–—:|").strip()
    return Script(winner, title, segments, raw=text)
