# SockLock Hook Variants — MVP design

## Intent

Motion designers at SockLock spend about half a day rewriting winning scripts by hand:
new hooks, first lines, on-screen text. That caps output at ~240 modifications/month while
$800k spend needs ~500. The MVP is an internal web page that turns one winning script into
N ready-to-use text variants in about a minute, so the text part of a modification drops
from ~1.5 h to ~10 min (designer review). Business case lives in the Claude Doc
(https://claude.ai/artifact/BDwp6yfmSbLkZw4kj7aw8f): base scenario ≈430 mods, +$67k EGP/month.

Assignment constraints: standalone utility, no access to Meta/Airtable/backend, text or file
in, result out; must work from day one; code must be explainable → keep it small.

## Goals

- Paste a script or drop a `.txt`/`.csv` file, choose count (default 20), click Generate.
- Table of variants with tags: element changed, angle, length/timing, risk warnings.
- Expand a row → full script with the new text and any adjusted neighbour phrase highlighted.
- Open a chat on one variant → comment what to fix → system returns a revised variant.
- Copy one / copy all, export CSV with UA naming (`W12_HOOK_pain_v07`).
- Independent sessions per designer; one designer's work never touches another's.
- Evals that show variants are usable, runnable locally via `claude -p` at no token cost.

## Non-goals

- No Claude skill (designers use only the web page). No autorender, no video.
- No login, no database: sessions live in server memory.
- No learning from Meta results (naming makes it possible later; distant and uncertain).

## Anti-goals

- Variants that drift off product/pain, or exceed the slot timing, shown as "fine".
- Silent changes to the script outside the chosen element and its neighbour.
- Hidden failures: a variant that fails checks is shown with a red tag, never dropped silently.

## Decisions (user)

- Web only, on Claude API, model **Claude Sonnet 5.5** (`claude-sonnet-5-5`), budget ≤ $100/month.
- Non-strict mode: may adjust the adjacent phrase so the new hook flows; adjustment highlighted.
- Naming convention now, Meta feedback loop later.
- Sessions in memory are fine. Example scripts: invent 8–10 SockLock winners.
- `.env` configuration; local tests/evals through `claude -p`.
- UI: single page as in mockup `layout-v2` — Apple-like frosted glass, input card,
  count stepper + Generate, variants table, expandable full view, chat side sheet.
- No "what to vary" selector in the form: the tool mixes hooks, first lines and on-screen
  text; tags show what changed; designer can narrow via chat/comment.

## How it works

### Input script format (builder's call, documented in README)

```
W12 · Washer thief
HOOK 0-2.5s | VO: "Lost another sock?" | ON-SCREEN: "Your washer eats socks"
PROBLEM 2.5-7s | VO: "Every wash, one goes missing..."
PRODUCT 7-15s | VO: "SockLock magnets keep pairs together"
CTA 15-20s | VO: "Get your first pack — 30% off"
```

First line: optional winner id (`W\d+`) and title. Segment lines: `NAME start-end[s] | VO: "…" | ON-SCREEN: "…"`.
Unparseable text is still accepted: the whole text goes to the model as one segment, timing
checks fall back to defaults (hook 2.5 s), winner id falls back to `W00`.

### Elements

- `HOOK` — VO of the first segment.
- `FIRSTLINE` — first VO line of the second segment (the line right after the hook).
- `ONSCREEN` — on-screen text of the first segment.

### Generation

One Messages API call with a cached system prompt (`prompts/system.md`). The model returns JSON:
`{"variants":[{"element","angle","text","adjacent":{"segment","field","text"}|null,"why"}]}`.
Angles: pain, curiosity, humor, demo, social_proof, contrarian, number, question.

Code checks each variant (`checks.py`):
- **timing** — VO ≤ floor(slot_seconds × 2.5) words; on-screen ≤ 7 words;
- **risky claims** — configurable list (guaranteed, 100%, forever, never lose, cure, #1…);
- **diversity** — no two variants share first 3 words; no near-duplicates (similarity > 0.85);
- **scope** — only the element and at most one adjacent phrase changed.

Failed variants are regenerated once (one follow-up call naming the failures); still failing →
shown with red tags.

### Chat on a variant

Per-variant message history in the session. Comment → model returns one revised variant →
same checks → named with a suffix (`v11b`, `v11c`).

### Naming

`{winner}_{ELEMENT}_{angle}_v{NN}`, e.g. `W12_HOOK_pain_v07`.

## Architecture

```
socklock_variants/
  config.py      .env → settings (LLM_BACKEND=api|cli, ANTHROPIC_API_KEY, MODEL, limits)
  script.py      parse script text → Script/Segment
  llm.py         LLM protocol; ApiLLM (anthropic SDK), CliLLM (claude -p), FakeLLM in tests
  prompts/system.md
  generator.py   build prompts, parse JSON, run checks, regenerate, name
  checks.py      deterministic checks
  naming.py
  sessions.py    in-memory SessionStore keyed by cookie, lock per session
  web.py         FastAPI app + routes
  static/        index.html, app.js, styles.css (no build step)
evals/
  scripts/       8–10 invented SockLock winners
  run.py         generate via configured backend, deterministic metrics + LLM judge, report
tests/           pytest, FakeLLM, no network
```

Stack (builder's call): Python 3.12, uv, FastAPI + uvicorn, anthropic SDK, python-dotenv, pytest.

API:
- `POST /api/generate` `{script, count}` → `{session variants}`
- `POST /api/variants/{name}/chat` `{message}` → `{reply, variant}`
- `GET /api/export.csv`
- Cookie `sid` identifies the session; new session per Generate.

## Evals

Deterministic (per variant, aggregated): JSON valid, timing pass rate, risky-claim count,
distinct angles, duplicate-opening count, scope violations.
LLM judge (1–5): on product & pain, specific (not generic), sounds natural aloud.
Target for MVP: 100% valid JSON, ≥95% timing pass, 0 risky claims unflagged, ≥6 angles per 20,
judge mean ≥4.

## Success metrics (README)

Share of variants designers use without edits (target ≥50% in 2-week pilot), minutes of text
work per modification (90 → ≤10), modifications/month (240 → ≈430 within 1–2 months),
ROMI of modifications ≥125%.

## Left to the builder

Prompt wording, exact risky-claim list, CSS details, eval script contents.
