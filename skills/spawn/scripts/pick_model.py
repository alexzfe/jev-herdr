#!/usr/bin/env python3
"""Ask Jev which Claude model and effort should handle a subtask.

Never fails: if Jev is unreachable or answers oddly, it returns FALLBACK with
"fallback": true and the error, so spawning is never blocked on routing.

Usage:
  python pick_model.py "task description"
  python pick_model.py --json "task description"   # machine-readable output
"""
import json
import os
import sys
import time
from pathlib import Path

from jev import JevError, ask

TIERS = ["haiku", "sonnet", "opus"]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
FALLBACK = {"model": "sonnet", "effort": "medium"}
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "jev-herdr"
LOG = STATE / "decisions.jsonl"


def log_event(event, **fields):
    """Append one routing event to decisions.jsonl; logging must never break routing."""
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **fields}) + "\n")
    except OSError:
        pass


QUESTIONS = {
    "model": {
        "type": "choice",
        "instructions": "Which model tier should a coding agent use to complete `task`?",
        "criteria": {
            "haiku": "Small, mechanical, well-specified work: renames, formatting, simple "
                     "lookups, boilerplate, running a command and reporting output.",
            "sonnet": "Typical engineering work: implementing a feature with clear "
                      "requirements, writing tests, moderate refactors, routine bug fixes.",
            "opus": "Hard or open-ended work: subtle or concurrency bugs, architecture and "
                    "design decisions, large cross-cutting refactors, security review, "
                    "anything where the approach is unclear.",
        },
    },
    "effort": {
        "type": "score",
        "instructions": "How much careful thinking does `task` need before and during the "
                        "work, independent of how long it takes?",
        "criteria": [
            "Low: obvious steps, nothing to reason about; just do it.",
            "Medium: a few straightforward decisions; little risk of getting it wrong.",
            "High: several interacting parts or edge cases worth thinking through.",
            "Extra high: subtle problem where a wrong hypothesis wastes a lot of time, "
            "such as intermittent or concurrency bugs or careful security reasoning.",
            "Max: hard, novel problem with no clear approach, where getting the design "
            "right matters more than speed.",
        ],
    },
}


def pick(task):
    try:
        resp = ask({"state": {"task": task}, "questions": QUESTIONS}, timeout=10)
        ans = resp["answers"]
        m, e = ans["model"], ans["effort"]
        return {
            "model": m["choice"],
            "effort": EFFORTS[min(max(round(e["score"]), 0), len(EFFORTS) - 1)],
            "effort_score": e["score"],
            "confidence": m["confidence"],
            "probabilities": m["probabilities"],
            "input_tokens": (resp.get("usage") or {}).get("input_tokens"),
            "fallback": False,
        }
    except (JevError, KeyError, TypeError, ValueError) as err:
        kind = err.kind if isinstance(err, JevError) else "error"
        return {**FALLBACK, "fallback": True, "error": repr(err), "error_kind": kind}


if __name__ == "__main__":
    args = sys.argv[1:]
    as_json = "--json" in args
    task = " ".join(a for a in args if a != "--json") or sys.stdin.read()
    if not task.strip():
        sys.exit(__doc__)
    r = pick(task)
    if as_json:
        print(json.dumps(r))
    elif r["fallback"]:
        print(f"model={r['model']}  effort={r['effort']}  (FALLBACK: {r['error']})")
    else:
        probs = " ".join(f"{k}={v:.2f}" for k, v in r["probabilities"].items())
        print(f"model={r['model']}  conf={r['confidence']:.2f}  [{probs}]")
        print(f"effort={r['effort']}  score={r['effort_score']:.2f}")
