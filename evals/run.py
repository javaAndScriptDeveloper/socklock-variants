"""Evals: run the generator on invented SockLock winners and score the output.

    uv run python evals/run.py              # all scripts, 10 variants each, via `claude -p`
    uv run python evals/run.py --limit 3 --count 20

Deterministic metrics come from the same checks the app uses; an LLM judge scores each
variant 1-5 on: on_brief (same product & pain), specific (concrete, not generic),
natural (sounds right read aloud). Uses LLM_BACKEND from .env (default cli = no API tokens).
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from socklock_variants.config import load_settings  # noqa: E402
from socklock_variants.generator import extract_json, generate  # noqa: E402
from socklock_variants.llm import make_llm  # noqa: E402
from socklock_variants.script import parse_script  # noqa: E402

HERE = Path(__file__).parent

JUDGE = """You review ad copy variants for SockLock (magnetic socks that stay paired in the wash).
For each variant score 1-5:
- on_brief: about this product and the pain of the original script (5 = clearly, 1 = off-topic)
- specific: concrete and visual rather than generic filler (5 = vivid, 1 = could be any product)
- natural: sounds natural read aloud by a real person (5 = natural, 1 = awkward)
Be strict: 5 means you would ship it unchanged.
Answer JSON only: {"scores": [{"name": "...", "on_brief": 1-5, "specific": 1-5, "natural": 1-5}]}"""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"scores": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "on_brief": {"type": "integer"},
                       "specific": {"type": "integer"}, "natural": {"type": "integer"}},
        "required": ["name", "on_brief", "specific", "natural"],
        "additionalProperties": False,
    }}},
    "required": ["scores"],
    "additionalProperties": False,
}

TARGETS = {
    "timing_pass": 0.95, "risky_flags": 0, "distinct_angles": 6,
    "dup_openings": 0, "scope": 0, "judge_mean": 4.0,
}


def judge(llm, script, variants) -> dict[str, dict]:
    listing = "\n".join(f"{v.name} [{v.element}]: {v.text}" for v in variants)
    msg = f"Original script:\n{script.to_text()}\n\nVariants:\n{listing}"
    try:
        data = extract_json(llm.complete(JUDGE, [{"role": "user", "content": msg}], schema=JUDGE_SCHEMA))
        return {s["name"]: s for s in data.get("scores", []) if "name" in s}
    except Exception as e:  # judge failure should not kill the run
        print(f"  judge failed: {e}", file=sys.stderr)
        return {}


def run_one(path: Path, count: int, llm, settings) -> dict:
    script = parse_script(path.read_text(encoding="utf-8"))
    t0 = time.time()
    try:
        variants = generate(script, count, llm, settings)
    except Exception as e:
        return {"script": path.stem, "error": str(e)}
    gen_s = time.time() - t0
    scores = judge(llm, script, variants)
    per = [scores.get(v.name) for v in variants]
    judged = [s for s in per if s]

    def avg(key):
        vals = [float(s[key]) for s in judged if key in s]
        return round(mean(vals), 2) if vals else None

    return {
        "script": path.stem,
        "parsed": script.segments[0].name != "SCRIPT",
        "returned": f"{len(variants)}/{count}",
        "timing_pass": round(sum("timing" not in v.issues for v in variants) / max(len(variants), 1), 2),
        "risky_flags": sum(any(i.startswith("risky:") for i in v.issues) for v in variants),
        "distinct_angles": len({v.angle for v in variants}) if variants else None,
        "dup_openings": sum(("duplicate_opening" in v.issues) or ("near_duplicate" in v.issues) for v in variants),
        "scope": sum("scope" in v.issues for v in variants),
        "on_brief": avg("on_brief"),
        "specific": avg("specific"),
        "natural": avg("natural"),
        "seconds": round(gen_s, 1),
        "variants": [
            {"name": v.name, "text": v.text, "issues": v.issues, "score": scores.get(v.name)}
            for v in variants
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    settings = load_settings()
    if settings.llm_backend not in ("api", "cli"):
        settings = replace(settings, llm_backend="cli")
    llm = make_llm(settings)
    paths = sorted((HERE / "scripts").glob("*.txt"))[: args.limit]
    print(f"Running {len(paths)} scripts x {args.count} variants via {settings.llm_backend} ({settings.model})")

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda p: run_one(p, args.count, llm, settings), paths))

    ok = [r for r in results if "error" not in r]
    cols = ["script", "returned", "timing_pass", "risky_flags", "distinct_angles", "dup_openings",
            "scope", "on_brief", "specific", "natural", "seconds"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in results:
        if "error" in r:
            lines.append(f"| {r['script']} | ERROR: {r['error']} |")
        else:
            lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")

    def agg(key, fn=mean):
        vals = [r[key] for r in ok if r.get(key) is not None]
        return round(fn(vals), 2) if vals else None

    judge_vals = [r[k] for r in ok for k in ("on_brief", "specific", "natural") if r.get(k) is not None]
    summary = {
        "scripts_ok": f"{len(ok)}/{len(results)}",
        "timing_pass": agg("timing_pass"),
        "risky_flags": agg("risky_flags", sum),
        "distinct_angles": agg("distinct_angles", min),
        "dup_openings": agg("dup_openings", sum),
        "scope": agg("scope", sum),
        "judge_mean": round(mean(judge_vals), 2) if judge_vals else None,
    }
    summary_lines = ["| metric | value | target |", "|---|---|---|"] + [
        f"| {k} | {v} | {TARGETS.get(k, '')} |" for k, v in summary.items()
    ]

    report = "\n".join([
        f"# Eval report\n\n{len(paths)} scripts x {args.count} variants, backend `{settings.llm_backend}`, "
        f"model `{settings.model}`.\n",
        "## Summary\n", *summary_lines, "\n## Per script\n", *lines,
        "\nNotes: `risky_flags` counts variants the checks caught (they are shown red in the UI, "
        "so a caught flag is not a leak). `distinct_angles` summary is the minimum across scripts. "
        "`judge_mean` averages on_brief, specific and natural.\n",
    ])
    (HERE / "report.md").write_text(report, encoding="utf-8")
    (HERE / "report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
