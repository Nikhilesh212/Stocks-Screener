#!/usr/bin/env python3
"""PreToolUse guard for the red team: never touch an analyst's *.conviction.json.

Usage in red-team's frontmatter (matcher "Read|Grep|Glob|Bash"):
    python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_conviction.py"
The red team must judge the dossier without the analyst's probabilities, so this
blocks: reading a conviction file; Grep/Glob whose search could include one;
Bash commands that name one (after quote removal, brace and glob expansion) or
that read a folder holding one (grep -r, rg, cat, jq, tools --input ...).
Listing commands (ls, find without -exec, du, stat) may still see the names.
"""
from __future__ import annotations

import glob
import os
from typing import List, Optional

from _guard_common import (CONVICTION_SUFFIX, Blocked, argv_of, expand_braces, glob_matches, has_glob, hook_cwd,
                           project_root, resolve, run, split_segments)

WHY = "the red team must not see the analyst's conviction file (probabilities stay hidden until portfolio construction)"
LISTING = {"ls", "find", "du", "stat", "cd", "pwd", "realpath", "readlink", "basename", "dirname"}
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}


def is_conviction(path: str) -> bool:
    return path.lower().endswith(CONVICTION_SUFFIX) or os.path.realpath(path).lower().endswith(CONVICTION_SUFFIX)


def conviction_files() -> List[str]:
    """Every conviction file in the project (analysts can only write them under runs/)."""
    found = []
    for base, _dirs, files in os.walk(os.path.join(project_root(), "runs")):
        found += [os.path.join(base, f) for f in files if f.lower().endswith(CONVICTION_SUFFIX)]
    return found


def holding(folder: str) -> List[str]:
    folder = os.path.realpath(folder).rstrip(os.sep) + os.sep
    return [c for c in conviction_files() if os.path.realpath(c).startswith(folder)]


def check_search(folder: str, pattern: Optional[str], what: str) -> None:
    """Grep/Glob over folder: blocked if a conviction file there could match the glob."""
    for c in holding(folder):
        rel = os.path.relpath(os.path.realpath(c), os.path.realpath(folder))
        if pattern is None or glob_matches(pattern, rel):
            raise Blocked(f"{what} would include {rel}; {WHY}. Narrow the path or glob (e.g. glob '*.md'), "
                          f"or Read the dossier .md/.json directly")


def check_bash(command: str, cwd: str) -> None:
    for seg in split_segments(command):
        argv = [w for word in argv_of(seg) for w in expand_braces(word)]
        if not argv:
            continue
        if any("conviction" in a.lower() for a in argv):
            raise Blocked(f"the command names a conviction file; {WHY}")
        cmd = argv[0]
        recursive_default = cmd == "rg" or (cmd in ("grep", "egrep", "fgrep") and any(
            a in ("--recursive", "--dereference-recursive") or a.startswith("--directories=rec")
            or (a.startswith("-") and not a.startswith("--") and ("r" in a or "R" in a)) for a in argv[1:]))
        paths = []
        for a in argv[1:]:
            val = a.partition("=")[2] if a.startswith("--") and "=" in a else a
            if not val or (val.startswith("-") and val == a):
                continue
            full = resolve(val, cwd)
            paths += glob.glob(full) if has_glob(val) else [full]
        if recursive_default and not any(os.path.isdir(p) for p in paths):
            paths.append(cwd)  # rg / grep -r with no folder search the current one
        for p in paths:
            if is_conviction(p):
                raise Blocked(f"{p} is a conviction file; {WHY}")
            if os.path.isdir(p) and holding(p):
                listing = cmd in LISTING and not (cmd == "find" and FIND_EXEC & set(argv))
                if not listing:
                    raise Blocked(f"`{cmd}` would read {p}, which holds conviction files; {WHY}. "
                                  f"Point it at the dossier .md/.json files themselves")
        if cmd == "cd" and len(argv) > 1:
            cwd = resolve(argv[1], cwd)


def check(data: dict) -> None:
    tool = data.get("tool_name")
    ti = data.get("tool_input") or {}
    cwd = hook_cwd(data)
    if tool == "Read":
        path = ti.get("file_path") or ""
        if is_conviction(resolve(path, cwd)) or is_conviction(path):
            raise Blocked(f"{path} is a conviction file; {WHY}")
    elif tool == "Grep":
        target = resolve(ti.get("path") or cwd, cwd)
        if os.path.isfile(target):
            if is_conviction(target):
                raise Blocked(f"{target} is a conviction file; {WHY}")
            return
        file_type = ti.get("type")
        if file_type and file_type != "json" and not ti.get("glob"):
            return  # a type filter other than json excludes *.conviction.json
        check_search(target, ti.get("glob"), "this Grep")
    elif tool == "Glob":
        pattern = ti.get("pattern") or ""
        if "conviction" in pattern.lower():
            raise Blocked(f"the pattern targets conviction files; {WHY}")
        folder = resolve(ti.get("path") or cwd, cwd)
        if os.path.isabs(pattern):
            folder, pattern = os.sep, pattern.lstrip(os.sep)
        check_search(folder, pattern, "this Glob")
    elif tool == "Bash":
        check_bash(ti.get("command") or "", cwd)


if __name__ == "__main__":
    run(check)
