from dataclasses import asdict, dataclass, field

ELEMENTS = ("HOOK", "FIRSTLINE", "ONSCREEN")


@dataclass
class Variant:
    name: str
    element: str  # HOOK | FIRSTLINE | ONSCREEN
    angle: str
    text: str
    adjacent: dict | None = None  # {"segment": "PROBLEM", "field": "vo", "text": "..."}
    why: str = ""
    issues: list[str] = field(default_factory=list)
    words: int = 0
    seconds: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)
