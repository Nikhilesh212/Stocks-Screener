#!/usr/bin/env python3
"""PreToolUse guard: Write/Edit only inside this agent's area of an existing run folder.

Usage in an agent's frontmatter (matcher "Write|Edit|MultiEdit|NotebookEdit"):
    python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_writes.py" dossiers/
Each argument is a path relative to runs/<run_id>/: a trailing '/' allows that
folder's subtree, otherwise exactly that file (e.g. `market_view.md market/`).
The run folder must already exist (the main session creates it), which catches
a mistyped run_id. Other tools pass through untouched.
"""
from __future__ import annotations

import sys

from _guard_common import Blocked, check_write_path, hook_cwd, parse_specs, run

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def check(data: dict) -> None:
    specs = parse_specs(sys.argv[1:])
    if data.get("tool_name") not in WRITE_TOOLS:
        return
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    if not path:
        raise Blocked("no file path in the tool call")
    check_write_path(path, hook_cwd(data), specs)


if __name__ == "__main__":
    run(check)
