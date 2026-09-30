#!/usr/bin/env python3
"""Score the router against labeled tasks.

Each line of the tasks file is: <model>\t<task>
Usage: python eval/run_eval.py [eval/eval_tasks.txt]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "spawn" / "scripts"))
from pick_model import pick  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("eval_tasks.txt")
rows = [line.split("\t") for line in Path(path).read_text().splitlines() if line.strip()]
hits_model = 0
start = time.time()
for want_model, task in rows:
    r = pick(task)
    if r["fallback"]:
        sys.exit(f"Jev unavailable: {r['error']}")
    ok_m = r["model"] == want_model
    hits_model += ok_m
    print(f"{'✓' if ok_m else '✗'} want {want_model:6} "
          f"got {r['model']:6} {r['effort']:6} conf={r['confidence']:.2f}  {task[:60]}")
n = len(rows)
print(f"\nmodel {hits_model}/{n}  avg {(time.time() - start) / n:.2f}s/task")
