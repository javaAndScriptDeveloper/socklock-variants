"""In-memory sessions: one per Generate, identified by the `sid` cookie.

Each designer's browser holds its own cookie, so generations and chats never mix.
State is lost on restart by design (MVP, no database).
"""

import secrets
import threading
from dataclasses import dataclass, field

from .models import Variant
from .script import Script


@dataclass
class Session:
    id: str
    script: Script
    variants: dict[str, Variant] = field(default_factory=dict)  # insertion order = table order
    chats: dict[str, list[dict]] = field(default_factory=dict)  # variant name -> LLM messages
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionStore:
    def __init__(self, max_sessions: int = 500):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self.max_sessions = max_sessions

    def create(self, script: Script, variants: list[Variant]) -> Session:
        session = Session(secrets.token_urlsafe(16), script, {v.name: v for v in variants})
        with self._lock:
            if len(self._sessions) >= self.max_sessions:  # drop the oldest
                self._sessions.pop(next(iter(self._sessions)))
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        with self._lock:
            return self._sessions.get(session_id)
