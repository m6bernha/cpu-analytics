#!/usr/bin/env python3
"""Check that every *_URL env var read by backend/app/ is pinned in render.yaml.

Prevents the recurring failure mode where a new env var is activated in the
Render dashboard but never committed to render.yaml. A Blueprint re-provision
then drops the value and the corresponding feature silently regresses to its
empty state. This bit us twice in three days:

  - 2026-04-23: ATHLETE_PROJ_TABLES_URL (commit 0310b9a pinned it after the fact)
  - 2026-04-26: QT_CURRENT_CSV_URL (PR #14 pinned it after the fact)

Run from repo root, no arguments, exits 0 on success and 1 with a message
listing missing keys on failure. Wired into the backend CI job.

Scope: only env var names matching `[A-Z][A-Z0-9_]*_URL` are checked. The
pattern is intentional, since URL-shaped env vars are the ones that point
at external resources whose loss on re-provision actually breaks the app.
Other env vars (DATABASE_URL aside, which is set by Render itself) can be
added to ALLOWLIST below with an inline reason if a false positive shows up.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend" / "app"
RENDER_YAML = REPO_ROOT / "render.yaml"

# Env var names intentionally NOT pinned in render.yaml. Add an inline
# comment for every entry so the next person knows why.
ALLOWLIST: set[str] = set()  # Add entries with an inline reason comment.

# Match os.environ.get("FOO_URL") or os.environ["FOO_URL"], single or double
# quoted, with arbitrary whitespace inside the call.
_ENV_READ_RE = re.compile(
    r"""os\.environ(?:\.get\(|\[)\s*["']([A-Z][A-Z0-9_]*_URL)["']"""
)

# Match `- key: SOMETHING` lines under envVars in render.yaml. Indentation
# can vary so the pattern is loose on leading whitespace.
_RENDER_KEY_RE = re.compile(
    r"""^\s*-\s*key:\s*([A-Z][A-Z0-9_]+)\s*$""", re.MULTILINE
)


def find_env_vars_read() -> set[str]:
    found: set[str] = set()
    for path in BACKEND_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _ENV_READ_RE.finditer(text):
            found.add(match.group(1))
    return found


def find_pinned_env_vars() -> set[str]:
    text = RENDER_YAML.read_text(encoding="utf-8")
    return set(_RENDER_KEY_RE.findall(text))


def main() -> int:
    if not BACKEND_DIR.is_dir():
        print(f"ERROR: backend dir not found at {BACKEND_DIR}", file=sys.stderr)
        return 2
    if not RENDER_YAML.is_file():
        print(f"ERROR: render.yaml not found at {RENDER_YAML}", file=sys.stderr)
        return 2

    read = find_env_vars_read()
    pinned = find_pinned_env_vars()
    missing = read - pinned - ALLOWLIST

    if missing:
        print("ERROR: env vars read by backend/app/ but NOT pinned in render.yaml:")
        for var in sorted(missing):
            print(f"  - {var}")
        print()
        print("Fix one of:")
        print("  1. Add `- key: <NAME>` plus a `value:` line under envVars in render.yaml")
        print("  2. Add the var to ALLOWLIST in scripts/check_env_var_pinning.py with a reason")
        return 1

    print(
        f"OK: {len(read)} *_URL env var(s) read by backend, all pinned in render.yaml"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
