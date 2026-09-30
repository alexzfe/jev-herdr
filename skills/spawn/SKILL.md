---
name: spawn
description: Spawn a Claude Code agent in a background Herdr tab to take a delegated subtask, with TypeSafe's Jev picking its model and effort. Use when asked to spawn, spin up or hand off work to an agent, or when long, open-ended work should run in parallel while you continue. Requires HERDR_ENV=1.
---

# Jev agents for Herdr

`scripts/spawn_agent.sh` (relative to this skill's base directory) asks Jev which model
(haiku, sonnet or opus) and effort (low to max) suit the task, then starts
`claude --model <m> --effort <e>` in a pane of a background tab labeled `agents` in the
caller's workspace, without taking focus. If Jev is unreachable, the agent starts on
the user's default model and effort.

## Spawn an agent

1. Verify you are inside Herdr: `test "${HERDR_ENV:-}" = 1`. If it fails, tell the user
   this skill needs a Herdr-managed pane, and stop.
2. Write the **brief**. The new agent starts with none of this conversation, so the
   brief is self-contained: the goal, the files and paths involved, constraints
   (read-only or allowed to edit, what to leave alone), what done looks like, and how to
   report back. Jev routes on this text, so describe the task's real difficulty.
3. Pick a name matching `[a-z][a-z0-9_-]{0,31}`, unique among live agents
   (`herdr agent list`).
4. From the directory the agent should work in, run:

   ```bash
   <skill-dir>/scripts/spawn_agent.sh --go <name> "<brief>"
   ```

   Options: `--model M` / `--effort E` when the user names them (Jev fills in whichever
   is missing), `--tab LABEL` for a different tab, `--watch` when the user asks for the
   agent to be watched or stepped up if it gets stuck (see below). Without `--go` it
   only prints what it would do.
5. Done when it prints `started '<name>' (...)`. Tell the user the model, effort and
   Jev's confidence from the `jev:` line, and the tab.
   - `jev key problem` means the user's TypeSafe key is missing or rejected, so every
     spawn falls back to the user's default model. Lead your reply with it and the fix
     it prints: set `TYPESAFE_API_KEY=...` in `~/.config/jev-herdr/env`.
   - `jev unavailable, starting on your default model` means a network or API error;
     mention the reason.

## Follow up

- Wait: `herdr agent wait <name> --timeout <ms>` returns on `idle`, `done` or `blocked`.
- Read: `herdr agent read <name> --source recent-unwrapped --lines 200`. When a long
  answer has scrolled out of reach, ask the agent to write it to a file and reply with
  the path.
- `blocked` means an approval or question dialog: show it to the user and let them
  decide.
- Finished agents stay open for the user to read. Close their panes when the user asks.
- For any other pane, tab or agent control, use the `herdr` skill.

## Watching and step-ups (opt-in, experimental)

With `--watch`, or `JEV_HERDR_WATCH=1` in the env file, `scripts/watch_agent.py` sends
Jev what is on screen in the agent's pane every 5 minutes while it works. Above 0.7 on
"struggling" it closes the agent and resumes the same conversation (`claude --resume`)
one step stronger: haiku → sonnet → opus, then higher effort, at most twice. The
resumed agent receives a one-line router note explaining the switch.

Every spawn, check, step-up and finish is appended to
`${XDG_STATE_HOME:-~/.local/state}/jev-herdr/decisions.jsonl`, with Jev's
`input_tokens` per request. Read it when the user asks how routing is performing, what
it costs, or wants to tune the thresholds.
