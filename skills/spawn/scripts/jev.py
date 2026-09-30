#!/usr/bin/env python3
"""Minimal Jev client. Reads a request JSON (state + questions) from a file or stdin,
posts it to TypeSafe's System One endpoint, prints the response JSON.

The API key comes from $TYPESAFE_API_KEY, else from a TYPESAFE_API_KEY= line in
$XDG_CONFIG_HOME/jev-herdr/env (default ~/.config/jev-herdr/env).

Usage:
  python jev.py request.json
  echo '{"state": "...", "questions": {...}}' | python jev.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://api.typesafe.ai/v1/systemone"


class JevError(Exception):
    """Jev could not be reached or returned something unusable.

    `kind` is one of "no_key" (no API key found), "bad_key" (HTTP 401/403), or
    "error" (everything else), so callers can distinguish a misconfiguration from
    a transient failure without parsing the message.
    """

    def __init__(self, message, kind="error"):
        super().__init__(message)
        self.kind = kind


def load_key():
    if key := os.environ.get("TYPESAFE_API_KEY"):
        return key
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    env = config / "jev-herdr" / "env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("TYPESAFE_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise JevError(f"TYPESAFE_API_KEY not found in environment or {env}", kind="no_key")


def ask(body, timeout=60):
    body.setdefault("model", "jev-latest")
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {load_key()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        kind = "bad_key" if e.code in (401, 403) else "error"
        raise JevError(f"HTTP {e.code}: {e.read().decode(errors='replace')}", kind=kind) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise JevError(f"Request to {URL} failed: {e}") from e
    except json.JSONDecodeError as e:
        raise JevError("Jev returned a non-JSON response") from e


if __name__ == "__main__":
    try:
        src = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
        body = json.load(src)
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"Bad request input: {e}")
    if not isinstance(body, dict):
        sys.exit("Request must be a JSON object")
    try:
        print(json.dumps(ask(body), indent=2))
    except JevError as e:
        sys.exit(str(e))
