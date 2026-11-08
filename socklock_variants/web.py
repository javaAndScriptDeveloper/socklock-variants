"""FastAPI app: one static page + a small JSON API.

Run:  uv run uvicorn socklock_variants.web:create_app --factory --port 8000
"""

import csv
import io
from pathlib import Path

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, load_settings
from .generator import extract_json, generate, revise
from .llm import LLM, make_llm
from .models import Variant
from .script import Script, parse_script
from .sessions import Session, SessionStore

STATIC = Path(__file__).parent / "static"
NOT_FOUND = "Variant not found — generate again"


class GenerateIn(BaseModel):
    script: str
    count: int = Field(20, ge=1, le=50)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def full_script(script: Script, v: Variant) -> list[dict]:
    """The whole script with this variant applied, marking what changed."""
    rows = [
        {"name": s.name, "start": s.start, "end": s.end, "vo": s.vo, "onscreen": s.onscreen,
         "highlight_vo": None, "highlight_onscreen": None}
        for s in script.segments
    ]
    idx = 1 if v.element == "FIRSTLINE" and len(rows) > 1 else 0
    field = "onscreen" if v.element == "ONSCREEN" else "vo"
    rows[idx][field] = v.text
    rows[idx][f"highlight_{field}"] = "new"
    if v.adjacent:
        for r in rows:
            if r["name"] == v.adjacent.get("segment"):
                f = "onscreen" if v.adjacent.get("field") == "onscreen" else "vo"
                r[f] = v.adjacent["text"]
                r[f"highlight_{f}"] = "adjacent"
    return rows


def view(session: Session, v: Variant) -> dict:
    return v.to_dict() | {"full_script": full_script(session.script, v)}


def chat_view(history: list[dict]) -> list[dict]:
    """LLM messages -> what the designer sees (their comment, the model's reply)."""
    out = []
    for m in history:
        if m["role"] == "user":
            text = m["content"].split("Designer's comment: ", 1)[-1].split("\n\n", 1)[0]
            out.append({"role": "designer", "text": text})
        else:
            try:
                text = extract_json(m["content"]).get("reply", "")
            except ValueError:
                text = ""
            out.append({"role": "assistant", "text": text})
    return out


def create_app(llm: LLM | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    llm = llm or make_llm(settings)
    store = SessionStore()
    app = FastAPI(title="SockLock Variants")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def session_or_404(sid: str | None) -> Session:
        session = store.get(sid)
        if session is None:
            raise HTTPException(404, NOT_FOUND)
        return session

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.post("/api/generate")
    def api_generate(body: GenerateIn, response: Response):
        if not body.script.strip():
            raise HTTPException(400, "Paste a winning script first")
        script = parse_script(body.script)
        try:
            variants = generate(script, body.count, llm, settings)
        except Exception as e:  # LLM/CLI failure: show it, don't hide it
            raise HTTPException(502, f"Generation failed: {e}") from e
        session = store.create(script, variants)
        response.set_cookie("sid", session.id, httponly=True, samesite="lax")
        return {
            "winner": script.winner_id,
            "title": script.title,
            "parsed": script.segments[0].name != "SCRIPT",
            "variants": [view(session, v) for v in variants],
        }

    @app.post("/api/variants/{name}/chat")
    def api_chat(name: str, body: ChatIn, sid: str | None = Cookie(None)):
        session = session_or_404(sid)
        with session.lock:  # one chat turn at a time per session
            base = session.variants.get(name)
            if base is None:
                raise HTTPException(404, NOT_FOUND)
            history = session.chats.setdefault(name, [])
            try:
                reply, new = revise(session.script, base, history, body.message, llm, settings,
                                    set(session.variants))
            except Exception as e:
                raise HTTPException(502, f"Revision failed: {e}") from e
            session.variants[new.name] = new
            # the revision continues the same chat thread
            session.chats[new.name] = history
        return {"reply": reply, "variant": view(session, new), "history": chat_view(history)}

    @app.get("/api/export.csv")
    def api_export(sid: str | None = Cookie(None)):
        session = session_or_404(sid)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["name", "element", "angle", "text", "adjacent", "issues"])
        for v in session.variants.values():
            adj = f"{v.adjacent['segment']}: {v.adjacent['text']}" if v.adjacent else ""
            w.writerow([v.name, v.element, v.angle, v.text, adj, " ".join(v.issues)])
        return Response(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{session.script.winner_id}_variants.csv"'},
        )

    return app
