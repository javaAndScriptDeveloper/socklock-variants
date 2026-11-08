# SockLock Hook Variants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Internal web page that turns a winning ad script into N checked, named text variants with per-variant chat revisions.

**Architecture:** Pure-Python core (parse → prompt → LLM → JSON → checks → naming) behind an `LLM` protocol with API, CLI (`claude -p`) and fake backends; FastAPI serves one static glass-style page and a small JSON API with in-memory per-cookie sessions; evals reuse the core with the CLI backend.

**Tech Stack:** Python 3.12, uv, FastAPI, uvicorn, anthropic SDK, python-dotenv, pytest, httpx (TestClient).

**Spec:** `docs/superpowers/specs/2026-11-08-hook-variants-design.md`

## Global Constraints

- Model `claude-sonnet-5-5`; budget ≤ $100/month; no thinking budget params.
- Config only via `.env` (`LLM_BACKEND=api|cli`, `ANTHROPIC_API_KEY`, `MODEL`, `WORDS_PER_SECOND=2.5`, `ONSCREEN_MAX_WORDS=7`, `DEFAULT_HOOK_SECONDS=2.5`).
- Tests never hit network or CLI: `FakeLLM` only.
- Naming `{winner}_{ELEMENT}_{angle}_v{NN}`, ELEMENT ∈ HOOK, FIRSTLINE, ONSCREEN; revisions append `b`, `c`, ….
- Failed checks → red tags, never dropped.
- No skill, no DB, no login, no build step for frontend.

## Review Focus

- Model returns JSON wrapped in prose or ```json fences → still parsed (test in Task 3).
- Model returns fewer variants than asked → regenerate the shortfall once, then show what exists (Task 3).
- Script pasted with curly quotes / no quotes / Windows newlines / no timings → still parsed with defaults (Task 1).
- Two designers generating concurrently → sessions isolated by cookie (Task 4).
- Chat on unknown variant name or after server restart → 404 with readable message, UI shows it (Task 4).

---

### Task 1: Project skeleton, config, script parser

**Files:** Create `pyproject.toml`, `.env.example`, `.gitignore`, `socklock_variants/__init__.py`, `socklock_variants/config.py`, `socklock_variants/script.py`, `tests/test_script.py`

**Interfaces — Produces:**
- `Settings` dataclass + `load_settings() -> Settings` (fields above).
- `Segment(name:str, start:float|None, end:float|None, vo:str, onscreen:str)` with `.seconds -> float|None`.
- `Script(winner_id:str, title:str, segments:list[Segment], raw:str)`; `parse_script(text:str) -> Script`.

- [ ] Tests: sample from spec → winner `W12`, 4 segments, hook seconds 2.5, VO/ON-SCREEN extracted; curly quotes and `\r\n` handled; `0–2.5s` en-dash accepted; unparseable text → `W00`, one segment `SCRIPT` with vo=raw, start/end None.
- [ ] Run → fail; implement regex parser; run → pass; commit.

### Task 2: Checks and naming

**Files:** Create `socklock_variants/checks.py`, `socklock_variants/naming.py`, `tests/test_checks.py`, `tests/test_naming.py`

**Interfaces — Produces:**
- `Variant` dataclass in `socklock_variants/models.py`: `name, element, angle, text, adjacent:dict|None, why, issues:list[str], words:int, seconds:float|None`.
- `check_variant(v, script, settings) -> list[str]` (issue codes `timing`, `risky:<word>`, `scope`).
- `check_diversity(variants) -> dict[name, list[str]]` (`duplicate_opening`, `near_duplicate`).
- `make_name(winner, element, angle, index) -> str`; `revision_name(name, existing:set[str]) -> str`.

- [ ] Tests: 6-word hook in 2.5 s slot passes, 7 fails; on-screen 8 words fails; "Guaranteed results" flagged `risky:guaranteed`; adjacent on segment index 0 or 1 ok, on CTA → `scope`; same first 3 words → duplicate; `make_name("W12","HOOK","pain",7)=="W12_HOOK_pain_v07"`; `revision_name("W12_HOOK_pain_v07", {...b})` → `...v07c`.
- [ ] Implement; pass; commit.

### Task 3: LLM backends and generator

**Files:** Create `socklock_variants/llm.py`, `socklock_variants/prompts/system.md`, `socklock_variants/generator.py`, `tests/fakes.py`, `tests/test_generator.py`

**Interfaces:**
- `class LLM(Protocol): def complete(self, system:str, messages:list[dict]) -> str`
- `ApiLLM(settings)` — `anthropic.Anthropic().messages.create(model, max_tokens=8000, system=[{type:text,text,cache_control:{type:ephemeral}}], messages, output_config={"effort":"low"})`, join text blocks.
- `CliLLM(settings)` — `claude -p --model <MODEL> --system-prompt <system> --output-format json --tools "" --no-session-persistence --strict-mcp-config`, transcript of messages on stdin, return `json["result"]`.
- `make_llm(settings) -> LLM`.
- `extract_json(text) -> dict` (fences / prose tolerant, raises `ValueError`).
- `generate(script, count, llm, settings) -> list[Variant]`; `revise(script, variant, history:list[dict], comment, llm, settings, existing_names:set[str]) -> tuple[str, Variant]`.

- [ ] Tests with `FakeLLM(responses:list[str])`: generate 3 → names v01..v03 with checks run; fenced JSON parsed; first answer has 1 failing (timing) + shortfall → exactly one follow-up call, replaced; still failing → kept with issues; revise returns `v01b` and reply text.
- [ ] Implement; pass; commit.

### Task 4: Sessions and web API

**Files:** Create `socklock_variants/sessions.py`, `socklock_variants/web.py`, `tests/test_web.py`

**Interfaces:**
- `Session(id, script, variants:dict[str,Variant], chats:dict[str,list[dict]])`; `SessionStore.create(script) / get(id)`, `threading.Lock` per store.
- `create_app(llm:LLM|None=None, settings=None) -> FastAPI`. Routes: `GET /` static, `POST /api/generate {script,count}` (count 1–50) sets cookie `sid`, `POST /api/variants/{name}/chat {message}`, `GET /api/export.csv`, `POST /api/upload` not needed (file read client-side).
- Variant JSON: dataclass fields + `full_script` list of segments with `highlight: "new"|"adjacent"|None`.

- [ ] Tests (TestClient + FakeLLM): generate returns N variants and sets cookie; two clients isolated; chat appends `v01b`; unknown name → 404 `{"detail":"Variant not found — generate again"}`; no cookie → 404; CSV header `name,element,angle,text,adjacent,issues`.
- [ ] Implement; pass; commit.

### Task 5: Frontend

**Files:** Create `socklock_variants/static/index.html`, `app.js`, `styles.css`

Single page per mockup `layout-v2` (frosted glass, SF font stack, gradient background, dark mode via `prefers-color-scheme`): drop zone + textarea (FileReader for .txt/.csv), count stepper (default 20), Generate with spinner, results list with tags (element, angle colour, words·seconds, red issues), expand full view with highlights, chat side sheet, copy (clipboard) per row / all, CSV link, error toast.

- [ ] Manual check: run `uv run uvicorn socklock_variants.web:app` with `LLM_BACKEND=cli`, generate on sample, expand, chat, copy, export; screenshot via browser. Commit.

### Task 6: Evals, sample scripts, README

**Files:** Create `evals/scripts/*.txt` (9 invented SockLock winners, varied: VO-only, on-screen only, 2 s / 3 s hooks, UK spelling), `evals/run.py`, `README.md`

- `run.py [--count 10] [--limit N]`: for each script `generate`, aggregate deterministic metrics (valid JSON, timing pass %, risky flagged, distinct angles, duplicate openings, scope violations), then one judge call per script scoring each variant 1–5 on on-brief / specific / natural; print table + write `evals/report.md`. Uses configured backend (default cli).
- README (Ukrainian): what/why (link to doc), setup (`uv sync`, `.env`), run web, run tests, run evals, input format, success metrics + targets, next iteration.

- [ ] Run `uv run pytest` → all pass; run `uv run python evals/run.py --limit 3` → report written; commit.
