import json

from fastapi.testclient import TestClient

from socklock_variants.config import Settings
from socklock_variants.web import create_app
from tests.fakes import FakeLLM, variants_json

SCRIPT = '''W12 · Washer thief
HOOK 0-2.5s | VO: "Lost another sock?" | ON-SCREEN: "Your washer eats socks"
PROBLEM 2.5-7s | VO: "Every wash, one goes missing..."
CTA 7-12s | VO: "Get your first pack"
'''

TWO = variants_json(("HOOK", "pain", "Washer ate one again?"), ("ONSCREEN", "humor", "Socks breaking up"))


def client(*responses):
    llm = FakeLLM(list(responses))
    return TestClient(create_app(llm=llm, settings=Settings())), llm


def test_index_served():
    c, _ = client()
    r = c.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_generate_sets_cookie_and_returns_variants():
    c, _ = client(TWO)
    r = c.post("/api/generate", json={"script": SCRIPT, "count": 2})
    assert r.status_code == 200
    assert "sid" in r.cookies
    body = r.json()
    assert [v["name"] for v in body["variants"]] == ["W12_HOOK_pain_v01", "W12_ONSCREEN_humor_v02"]
    full = body["variants"][0]["full_script"]
    assert full[0]["vo"] == "Washer ate one again?" and full[0]["highlight_vo"] == "new"
    assert full[1]["highlight_vo"] is None


def test_adjacent_highlight():
    resp = json.dumps({"variants": [{"element": "HOOK", "angle": "number", "text": "One sock lost weekly",
                                     "adjacent": {"segment": "PROBLEM", "field": "vo", "text": "Yours could be next"},
                                     "why": ""}]})
    c, _ = client(resp)
    full = c.post("/api/generate", json={"script": SCRIPT, "count": 1}).json()["variants"][0]["full_script"]
    assert full[1]["vo"] == "Yours could be next" and full[1]["highlight_vo"] == "adjacent"


def test_sessions_are_isolated():
    llm = FakeLLM([TWO, variants_json(("HOOK", "demo", "Watch the click"))])
    app = create_app(llm=llm, settings=Settings())
    a, b = TestClient(app), TestClient(app)
    a.post("/api/generate", json={"script": SCRIPT, "count": 2})
    b.post("/api/generate", json={"script": SCRIPT, "count": 1})
    assert "W12_HOOK_pain_v01" in a.get("/api/export.csv").text
    assert "W12_HOOK_pain_v01" not in b.get("/api/export.csv").text


def test_chat_creates_revision():
    reply = json.dumps({"reply": "Shorter now.", "variant": {"element": "HOOK", "angle": "pain",
                                                             "text": "Washer ate one?", "adjacent": None}})
    c, _ = client(TWO, reply)
    c.post("/api/generate", json={"script": SCRIPT, "count": 2})
    r = c.post("/api/variants/W12_HOOK_pain_v01/chat", json={"message": "shorter"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "Shorter now."
    assert body["variant"]["name"] == "W12_HOOK_pain_v01b"
    assert [m["role"] for m in body["history"]] == ["designer", "assistant"]
    assert "W12_HOOK_pain_v01b" in c.get("/api/export.csv").text


def test_chat_unknown_variant_and_no_session():
    c, _ = client(TWO)
    assert c.post("/api/variants/X/chat", json={"message": "hi"}).status_code == 404
    c.post("/api/generate", json={"script": SCRIPT, "count": 2})
    r = c.post("/api/variants/NOPE/chat", json={"message": "hi"})
    assert r.status_code == 404
    assert r.json()["detail"] == "Variant not found — generate again"


def test_export_csv_header():
    c, _ = client(TWO)
    c.post("/api/generate", json={"script": SCRIPT, "count": 2})
    first = c.get("/api/export.csv").text.splitlines()[0]
    assert first == "name,element,angle,text,adjacent,issues"


def test_bad_input():
    c, _ = client()
    assert c.post("/api/generate", json={"script": "  ", "count": 2}).status_code == 400
    assert c.post("/api/generate", json={"script": SCRIPT, "count": 0}).status_code == 422
    assert c.post("/api/generate", json={"script": SCRIPT, "count": 51}).status_code == 422


def test_llm_failure_is_502():
    class Boom:
        def complete(self, system, messages):
            raise RuntimeError("claude -p failed: not logged in")

    c = TestClient(create_app(llm=Boom(), settings=Settings()))
    r = c.post("/api/generate", json={"script": SCRIPT, "count": 2})
    assert r.status_code == 502 and "not logged in" in r.json()["detail"]
