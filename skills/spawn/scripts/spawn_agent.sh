#!/usr/bin/env bash
# Let Jev pick the model and effort for a task, then start a Claude Code agent for it
# in a Herdr pane.
#
# Usage: spawn_agent.sh [--go --pane ID] [--watch] [--model M] [--effort E]
#                       [--interval SECS] <name> <task...>
#   --pane is an existing pane at a shell prompt; the caller creates it (the herdr
#   skill's placement rules decide where).
#   Without --go it only prints what it would do (dry run).
#   --model / --effort override what Jev picks. If Jev fails, whichever is still unset
#   is left out, so claude starts on the user's own default model or effort.
#   The watcher is opt-in: pass --watch, set JEV_HERDR_WATCH=1 in the environment, or
#   put JEV_HERDR_WATCH=1 in ${XDG_CONFIG_HOME:-~/.config}/jev-herdr/env (same file as
#   TYPESAFE_API_KEY; the environment wins if both are set). When on, watch_agent.py
#   runs in the background and steps the agent up if Jev judges it stuck. Every
#   decision is logged to ${XDG_STATE_HOME:-~/.local/state}/jev-herdr/decisions.jsonl.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
state="${XDG_STATE_HOME:-$HOME/.local/state}/jev-herdr"
config="${XDG_CONFIG_HOME:-$HOME/.config}/jev-herdr/env"
for dep in python3 jq herdr claude; do
  command -v "$dep" >/dev/null || { echo "missing dependency: $dep" >&2; exit 1; }
done

herdr_ver="$(herdr --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)"
[[ "$herdr_ver" == 0.9.* ]] || echo "tested with herdr 0.9.x, found ${herdr_ver:-unknown}" >&2

go=0 watch=0 interval=300 pane="" model="" effort=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --go) go=1; shift ;;
    --watch) watch=1; shift ;;
    --interval) interval="$2"; shift 2 ;;
    --pane) pane="$2"; shift 2 ;;
    --model) model="$2"; shift 2 ;;
    --effort) effort="$2"; shift 2 ;;
    *) break ;;
  esac
done
if [[ $watch -eq 0 ]]; then
  # Environment wins over the config file, same precedence as TYPESAFE_API_KEY.
  w="${JEV_HERDR_WATCH:-}"
  if [[ -z "$w" && -f "$config" ]]; then
    w="$(sed -n 's/^JEV_HERDR_WATCH=//p' "$config" | tail -n1)"
  fi
  [[ "$w" == "1" ]] && watch=1
fi
[[ $# -ge 2 ]] || { echo "usage: $0 [--go --pane ID] [--watch] [--model M] [--effort E] [--interval SECS] <name> <task...>" >&2; exit 2; }
[[ $go -eq 0 || -n "$pane" ]] || { echo "--go needs --pane ID: create the pane first (herdr skill)" >&2; exit 2; }
name="$1"; shift
task="$*"

pick="null" user_model="$model"
if [[ -z "$model" || -z "$effort" ]]; then
  # pick_model.py falls back on its own; this covers it crashing outright.
  pick="$(python3 "$here/pick_model.py" --json "$task")" \
    || pick='{"model":null,"effort":null,"fallback":true,"error":"pick_model.py crashed","error_kind":"error"}'
  model="${model:-$(jq -r '.model // empty' <<<"$pick")}"
  effort="${effort:-$(jq -r '.effort // empty' <<<"$pick")}"
  if [[ "$(jq -r .fallback <<<"$pick")" == true ]]; then
    kind="$(jq -r '.error_kind // empty' <<<"$pick")"
    err="$(jq -r '.error // empty' <<<"$pick")"
    case "$kind" in
      no_key|bad_key)
        echo "jev key problem ($kind): $err. Set TYPESAFE_API_KEY in $config. Starting on your default model." >&2
        ;;
      *)
        echo "jev unavailable, starting on your default model: $err" >&2
        ;;
    esac
  else
    echo "jev: $(jq -c '{model, confidence, effort, effort_score, input_tokens}' <<<"$pick")" >&2
  fi
fi

flags=()
[[ -n "$model" ]] && flags+=(--model "$model")
[[ -n "$effort" ]] && flags+=(--effort "$effort")
# One fixed-format line the skill repeats to the user, so every spawn is easy to audit.
if [[ "$pick" == null ]]; then
  why="set by you"
elif [[ "$(jq -r .fallback <<<"$pick")" == true ]]; then
  why="Jev unavailable, your defaults"
elif [[ -n "$user_model" ]]; then
  why="model set by you, effort by Jev"
else
  why="Jev $(jq -r '.confidence * 100 | round' <<<"$pick")% sure"
fi
brief="${task//$'\n'/ }"
(( ${#brief} > 60 )) && brief="${brief:0:60}…"
summary="spawned $name → ${model:-default model} / ${effort:-default} effort ($why) in $pane · \"$brief\""

if [[ $go -eq 0 ]]; then
  echo "dry run: would start '$name' in pane ${pane:-<pane>} as claude ${flags[*]:-(no flags)}, and prompt:" >&2
  echo "  $task" >&2
  exit 0
fi

test "${HERDR_ENV:-}" = 1 || { echo "not running inside Herdr" >&2; exit 1; }

out="$(herdr agent start "$name" --kind claude --pane "$pane" -- ${flags[@]+"${flags[@]}"} 2>&1)" \
  || { echo "failed to start agent '$name' in pane $pane: $out" >&2; exit 1; }
# No --wait: the caller doesn't need to block here, and watch_agent.py already waits
# for "working" status itself before it starts checking on the agent.
herdr agent prompt "$name" "$task" >/dev/null
echo "$summary"

mkdir -p "$state"
jq -nc --arg ts "$(date +%FT%T)" --arg name "$name" --arg pane "$pane" --arg task "$task" \
  --arg model "${model:-default}" --arg effort "${effort:-default}" --argjson pick "$pick" \
  '{ts: $ts, event: "spawn", name: $name, pane: $pane, task: $task, model: $model, effort: $effort, jev: $pick}' \
  >> "$state/decisions.jsonl"

if [[ $watch -eq 1 && ( -z "$model" || -z "$effort" ) ]]; then
  echo "not watching '$name': step-ups need a known model and effort to step up from" >&2
elif [[ $watch -eq 1 ]]; then
  # setsid(1) isn't available on macOS. A double fork + os.setsid() is portable and
  # detaches the watcher from this shell's session, so it survives the shell exiting.
  # Args go through argv, not interpolated into the script text, since $task is
  # arbitrary text.
  python3 - "$state/watch.log" python3 "$here/watch_agent.py" "$name" --model "$model" \
      --effort "$effort" --task "$task" --interval "$interval" <<'PY' &
import os, sys
logpath = sys.argv[1]
cmd = sys.argv[2:]
if os.fork():
    sys.exit(0)
os.setsid()
if os.fork():
    sys.exit(0)
fd = os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
os.dup2(fd, 1)
os.dup2(fd, 2)
devnull = os.open(os.devnull, os.O_RDONLY)
os.dup2(devnull, 0)
os.execvp(cmd[0], cmd)
PY
  echo "watching '$name' every ${interval}s (log: $state/decisions.jsonl)"
fi
