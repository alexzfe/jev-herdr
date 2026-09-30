#!/usr/bin/env python3
"""Watch a Herdr-hosted Claude agent and step it up when it seems stuck.

Every --interval seconds that the agent is still working, Jev reads the pane's recent
output and judges whether the agent is struggling. If so, the agent is closed and its
conversation resumed (`claude --resume`) one step stronger: the next model tier, or,
already on opus, the next effort level. Resuming instead of `/model` keeps the user's
saved default model untouched.

Every check, escalation and the final outcome go to the decision log (see pick_model.py).

Usage:
  python watch_agent.py <name> --model M --effort E --task "..." [--interval 300]
                        [--threshold 0.7] [--max-steps 2]
"""
import argparse
import json
import subprocess
import time

from jev import JevError, ask
from pick_model import EFFORTS, TIERS, log_event

STRUGGLING = {
    "type": "noul",
    "instructions": "Based on `recent_output`, is the coding agent struggling with `task`: "
                    "repeating failed attempts, hitting the same error again and again, "
                    "going in circles, or confused about the approach?",
    "criteria": {
        "true": "Stuck: repeated failures, loops, or visible confusion.",
        "false": "Making progress, even if slow, or waiting on a long-running command.",
    },
}


def herdr(*args):
    """Run a herdr command; return (ok, parsed JSON or raw text)."""
    p = subprocess.run(["herdr", *args], capture_output=True, text=True)
    out = p.stdout if p.returncode == 0 else p.stderr
    try:
        return p.returncode == 0, json.loads(out)
    except json.JSONDecodeError:
        return p.returncode == 0, out


def wait(name, seconds):
    """Wait for the agent to settle. Returns its status, 'working' on timeout, None if gone."""
    ok, r = herdr("agent", "wait", name, "--timeout", str(int(seconds * 1000)))
    if ok:
        return r["result"]["agent"]["agent_status"]
    code = r.get("error", {}).get("code") if isinstance(r, dict) else None
    return None if code == "agent_not_found" else "working"


def step_up(model, effort):
    """Next stronger (model, effort), or None when already at the top."""
    if model in TIERS and model != TIERS[-1]:
        return TIERS[TIERS.index(model) + 1], effort
    if effort in EFFORTS and effort != EFFORTS[-1]:
        return model, EFFORTS[EFFORTS.index(effort) + 1]
    return None


def restart(name, model, effort, note):
    """Close the agent and resume its conversation with a new model/effort."""
    ok, info = herdr("agent", "get", name)
    if not ok:
        return False
    agent = info["result"]["agent"]
    pane, session = agent["pane_id"], agent["agent_session"]["value"]
    herdr("agent", "send-keys", name, "esc")
    time.sleep(1)
    herdr("agent", "send-keys", name, "ctrl+c", "ctrl+c")
    for _ in range(30):  # wait for claude to exit and free the name
        if not herdr("agent", "get", name)[0]:
            break
        time.sleep(0.5)
    else:
        return False
    ok, _ = herdr("agent", "start", name, "--kind", "claude", "--pane", pane,
                  "--", "--resume", session, "--model", model, "--effort", effort)
    if ok:
        # A freshly resumed session can swallow the Enter while it loads its history;
        # if the note didn't start a turn, submit it again.
        sent, r = herdr("agent", "prompt", name, note, "--wait", "--timeout", "20000")
        if not sent and isinstance(r, dict) and r.get("error", {}).get("code") == "agent_prompt_stalled":
            herdr("agent", "send-keys", name, "enter")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--model", required=True)
    ap.add_argument("--effort", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--interval", type=float, default=300)
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--max-steps", type=int, default=2)
    a = ap.parse_args()

    model, effort, steps, started = a.model, a.effort, 0, time.time()
    # The prompt may not have been picked up yet; an idle agent now is not a finished one.
    herdr("agent", "wait", a.name, "--until", "working", "--timeout", "20000")
    while True:
        status = wait(a.name, a.interval)
        minutes = round((time.time() - started) / 60, 1)
        if status is None:
            log_event("gone", name=a.name, model=model, effort=effort, steps=steps, minutes=minutes)
            return
        if status in ("idle", "done"):
            log_event("finished", name=a.name, model=model, effort=effort, steps=steps, minutes=minutes)
            return
        if status == "blocked":
            # Waiting on the user (approval or question): not a sign of struggling.
            time.sleep(30)
            continue

        # While an agent works, Herdr can't scroll its alternate-screen history
        # (agent_not_idle), so read what is on screen. The result is plain text, not JSON.
        ok, text = herdr("agent", "read", a.name, "--source", "visible")
        if not ok:
            log_event("check_failed", name=a.name, error=f"agent read: {text}")
            continue
        try:
            resp = ask({"state": {"task": a.task, "minutes_elapsed": minutes, "recent_output": text},
                       "questions": {"struggling": STRUGGLING}}, timeout=15)
            struggling = resp["answers"]["struggling"]["noul"]
        except (JevError, KeyError, TypeError) as err:
            log_event("check_failed", name=a.name, error=repr(err))
            continue
        input_tokens = (resp.get("usage") or {}).get("input_tokens")
        log_event("check", name=a.name, model=model, effort=effort, minutes=minutes,
                  struggling=struggling, input_tokens=input_tokens)

        if struggling < a.threshold or steps >= a.max_steps:
            continue
        nxt = step_up(model, effort)
        if nxt is None:
            continue
        # Without the first sentence the resumed agent reads the Ctrl+C as the user
        # stopping it and ends the task.
        note = ("(Router note: the interruption above was an automatic switch, not the user "
                f"stopping you. You are now on {nxt[0]} with {nxt[1]} effort because progress "
                "looked stuck. Pick the task up where you left off, re-running any command that "
                "was cut off; if you were going in circles, step back and reconsider the "
                "approach.)")
        if restart(a.name, *nxt, note):
            log_event("escalate", name=a.name, frm=[model, effort], to=list(nxt),
                      struggling=struggling, minutes=minutes)
            model, effort = nxt
            steps += 1
        else:
            log_event("escalate_failed", name=a.name, frm=[model, effort], to=list(nxt))


if __name__ == "__main__":
    main()
