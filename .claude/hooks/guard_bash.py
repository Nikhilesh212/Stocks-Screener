#!/usr/bin/env python3
"""PreToolUse guard for Bash: the tools CLI plus read-only commands, nothing that writes files.

Usage in an agent's frontmatter (matcher "Bash"):
    python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_bash.py" dossiers/
The arguments are the agent's write area, as for guard_writes.py; a tools
`--out FILE` must land inside it.

Allowed, alone or joined with | && || ; :
  * `uv run python -m tools data ...` and `uv run python -m tools compute ...`
    (`ledger` and `smoke` are for the main session only);
  * read-only commands: see READ_ONLY below, with their file-writing options refused.
Refused: redirection (except `2>&1` and `>/dev/null`), command/process
substitution, variable expansion, subshells, background jobs, `.env`.
"""
from __future__ import annotations

import os
import sys

from _guard_common import Blocked, argv_of, check_write_path, hook_cwd, parse_specs, resolve, run, split_segments

TOOLS_PREFIX = ["uv", "run", "python", "-m", "tools"]
TOOL_GROUPS = {"data", "compute"}
READ_ONLY = {
    "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "find", "sort", "uniq", "cut", "tr",
    "column", "nl", "stat", "du", "pwd", "basename", "dirname", "realpath", "readlink", "diff", "cmp", "comm",
    "jq", "echo", "printf", "true", "date", "file", "cd",
}
FIND_REFUSED = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
OUT_FLAGS = {"--o", "--ou", "--out"}  # argparse accepts unambiguous prefixes


def _options(argv: list) -> list:
    return [a for a in argv[1:] if a.startswith("-")]


def _positionals(argv: list) -> list:
    return [a for a in argv[1:] if not a.startswith("-")]


def check_tools(argv: list, cwd: str, specs: list) -> None:
    if argv[:5] != TOOLS_PREFIX:
        raise Blocked("run the tools exactly as `uv run python -m tools <data|compute> <command> ...`")
    rest = argv[5:]
    if not rest or rest[0] in ("-h", "--help"):
        return
    if rest[0] not in TOOL_GROUPS:
        raise Blocked(f"`tools {rest[0]}` is reserved for the main session; use the data and compute groups")
    for i, a in enumerate(rest):
        flag, eq, val = a.partition("=")
        if flag in OUT_FLAGS:
            if not eq:
                if i + 1 >= len(rest):
                    raise Blocked("--out needs a file path")
                val = rest[i + 1]
            check_write_path(val, cwd, specs)


def check_read_only(argv: list) -> None:
    cmd = argv[0]
    opts = _options(argv)
    if cmd == "find" and FIND_REFUSED & set(argv):
        raise Blocked(f"find with {sorted(FIND_REFUSED & set(argv))} is not allowed (runs commands or writes files)")
    if cmd == "sort" and any(o.startswith(("-o", "--o")) or ("o" in o and not o.startswith(("--", "-k", "-t")))
                             for o in opts):
        raise Blocked("sort -o/--output writes a file; print to stdout instead")
    if cmd == "uniq" and len(_positionals(argv)) > 1:
        raise Blocked("uniq with an output file argument writes a file; print to stdout instead")
    if cmd == "rg" and any(o.startswith("--pre") for o in opts):
        raise Blocked("rg --pre runs a command on every file")
    if cmd == "date" and any(o in ("-s",) or o.startswith("--set") for o in opts):
        raise Blocked("date -s sets the clock")
    if cmd == "file" and any(o in ("-C",) or o.startswith("--compile") for o in opts):
        raise Blocked("file -C writes a magic file")


def check(data: dict) -> None:
    specs = parse_specs(sys.argv[1:])
    if data.get("tool_name") != "Bash":
        return
    command = (data.get("tool_input") or {}).get("command") or ""
    cwd = hook_cwd(data)
    segments = split_segments(command)
    if not segments:
        raise Blocked("empty command")
    for seg in segments:
        argv = argv_of(seg)
        if not argv:
            continue
        if "=" in argv[0] and not argv[0].startswith("-"):
            raise Blocked("environment assignments (NAME=value cmd) are not allowed")
        if any(os.path.basename(a.partition("=")[2] or a) == ".env" for a in argv[1:]):
            raise Blocked(".env holds credentials and is never read by agents")
        if argv[0] == "uv":
            check_tools(argv, cwd, specs)
        elif argv[0] in READ_ONLY:
            check_read_only(argv)
            if argv[0] == "cd":  # later segments resolve relative paths from here
                cwd = resolve(argv[1] if len(argv) > 1 else "~", cwd)
        else:
            raise Blocked(f"`{argv[0]}` is not allowed. Allowed: `uv run python -m tools data|compute ...` and "
                          f"read-only commands ({', '.join(sorted(READ_ONLY))}). Use the Read/Grep/Glob tools "
                          f"for files and the Write tool (inside your area) to save output")


if __name__ == "__main__":
    run(check)
