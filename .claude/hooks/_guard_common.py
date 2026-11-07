"""Shared helpers for the PreToolUse guard hooks in this folder.

Claude Code runs each hook with the tool call as JSON on stdin:
    {"tool_name": "Write", "tool_input": {"file_path": ...}, "cwd": ..., ...}
Exit 0 lets the call continue to the normal permission check; exit 2 blocks it
and the text on stderr is shown to the agent as the reason. Any other exit code
is a non-blocking error, so every hook catches its own exceptions and blocks
(fails closed) instead of crashing.

Standard library only, Python 3.8+: `python3` outside the repo may not be the
project's 3.12.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from typing import Callable, List, Optional

RUN_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9][A-Za-z0-9_-]*$")
CONVICTION_SUFFIX = ".conviction.json"


class Blocked(Exception):
    """Raised with the reason the agent will read."""


def project_root() -> str:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return os.path.realpath(env)
    return os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def resolve(path: str, cwd: str) -> str:
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.realpath(p)


def run(check: Callable[[dict], None]) -> None:
    """Read the hook JSON, call check(data); exit 2 with the reason if it raises."""
    try:
        data = json.loads(sys.stdin.read() or "{}")
        if not isinstance(data, dict):
            raise Blocked("hook input is not a JSON object")
        check(data)
    except Blocked as e:
        print(f"Blocked by {os.path.basename(sys.argv[0])}: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # fail closed: a crashing guard must not let the call through
        print(f"Blocked by {os.path.basename(sys.argv[0])}: guard error ({type(e).__name__}: {e})", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


def hook_cwd(data: dict) -> str:
    return data.get("cwd") or os.getcwd()


# --- write area -------------------------------------------------------------

def parse_specs(args: List[str]) -> List[str]:
    """Allowed write paths relative to runs/<run_id>/: 'dossiers/' (a folder) or 'market_view.md' (one file)."""
    if not args:
        raise Blocked("hook misconfigured: no allowed write path given (e.g. `guard_writes.py dossiers/`)")
    for s in args:
        parts = s.rstrip("/").split("/")
        if not s or s.startswith(("/", "~")) or any(p in ("", ".", "..") for p in parts):
            raise Blocked(f"hook misconfigured: bad allowed path {s!r}")
    return args


def describe_area(specs: List[str]) -> str:
    return " or ".join(f"runs/<run_id>/{s}" for s in specs)


def check_write_path(path: str, cwd: str, specs: List[str]) -> None:
    """Raise Blocked unless path is inside runs/<run_id>/<an allowed spec> of an existing run folder."""
    root = project_root()
    runs = os.path.join(root, "runs")
    target = resolve(path, cwd)
    rel = os.path.relpath(target, runs)
    where = (f"You may write only under {describe_area(specs)}, where runs/<run_id>/ is the run folder "
             f"the main session created (run_id = YYYY-MM-DD-<slug>).")
    if rel == os.curdir or rel.startswith(os.pardir) or os.path.isabs(rel):
        raise Blocked(f"{path} is outside runs/. {where}")
    parts = rel.split(os.sep)
    run_id, inner = parts[0], "/".join(parts[1:])
    if not RUN_ID_RE.match(run_id):
        raise Blocked(f"{run_id!r} is not a run_id (YYYY-MM-DD-<slug>). {where}")
    if not os.path.isdir(os.path.join(runs, run_id)):
        raise Blocked(f"run folder runs/{run_id}/ does not exist; check the run_id in your task. {where}")
    for s in specs:
        if s.endswith("/") and inner.startswith(s) and len(inner) > len(s):
            return
        if not s.endswith("/") and inner == s:
            return
    raise Blocked(f"{path} is not in your write area. {where}")


# --- shell parsing ----------------------------------------------------------

def _expansion_start(ch: str) -> bool:
    return ch.isalnum() or ch in "_{(@*#?$!-'"


_HARMLESS_REDIRECT = re.compile(r">>?[ \t]*(?:&[12](?![\w/])|/dev/null(?=$|[\s;|&]))")


def split_segments(cmd: str) -> List[str]:
    """Split at unquoted | || && ; and newlines into simple commands.

    Raises Blocked for constructs that can write files or hide what runs:
    redirection (only `2>&1` and `>/dev/null` style are allowed), command or
    process substitution, variable expansion, subshells, background jobs.
    """
    segs: List[str] = []
    buf: List[str] = []
    quote: Optional[str] = None
    i, n = 0, len(cmd)

    def flush() -> None:
        s = "".join(buf).strip()
        if s:
            segs.append(s)
        buf.clear()

    while i < n:
        c = cmd[i]
        nxt = cmd[i + 1] if i + 1 < n else ""
        if quote == "'":
            buf.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c == "\\":
            if nxt == "\n":
                i += 2  # line continuation
                continue
            buf.append(cmd[i:i + 2])
            i += 2
            continue
        if c == "`" or (c == "$" and nxt and _expansion_start(nxt)):
            raise Blocked("command substitution, `$'...'` quoting and variable expansion ($...) are not allowed; "
                          "write the literal values")
        if quote == '"':
            if c == '"':
                quote = None
            buf.append(c)
            i += 1
            continue
        if c in "'\"":
            quote = c
            buf.append(c)
        elif c in ";\n":
            flush()
        elif c == "|":
            if nxt == "&":
                raise Blocked("`|&` is not allowed")
            flush()
            i += 1 if nxt == "|" else 0
        elif c == "&":
            if nxt != "&":
                raise Blocked("background jobs and `&>` are not allowed")
            flush()
            i += 1
        elif c == ">":
            m = _HARMLESS_REDIRECT.match(cmd, i)
            if not m:
                raise Blocked("output redirection (>, >>) is not allowed: tools print JSON to stdout, "
                              "and files are written only with the Write tool or a tools `--out` path in your area")
            if buf and buf[-1] in "12" and (len(buf) == 1 or buf[-2].isspace()):
                buf.pop()  # the fd number belongs to the redirection, not to argv
            i = m.end()
            continue
        elif c == "<":
            raise Blocked("input redirection, here-documents and process substitution (<, <<, <(...)) are not allowed")
        elif c in "()":
            raise Blocked("subshells and parentheses are not allowed; run commands one at a time")
        else:
            buf.append(c)
        i += 1
    if quote:
        raise Blocked("unterminated quote")
    flush()
    return segs


def argv_of(segment: str) -> List[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError as e:
        raise Blocked(f"cannot parse command ({e})")


def expand_braces(s: str) -> List[str]:
    """Bash-style {a,b} expansion (nested ok, no ranges); used so guards see every name a word can become."""
    depth, start = 0, -1
    for i, c in enumerate(s):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}" and depth:
            depth -= 1
            if depth == 0:
                body, alts, d, last = s[start + 1:i], [], 0, 0
                for j, ch in enumerate(body):
                    d += ch == "{"
                    d -= ch == "}"
                    if ch == "," and d == 0:
                        alts.append(body[last:j])
                        last = j + 1
                if not alts:
                    continue
                alts.append(body[last:])
                return [r for a in alts for r in expand_braces(s[:start] + a + s[i + 1:])]
    return [s]


# --- glob matching (Glob tool / Grep glob filter) ----------------------------

def glob_regex(pattern: str) -> "re.Pattern[str]":
    out, i, n = [], 0, len(pattern)
    while i < n:
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pattern.find("]", i + 2)
            if j == -1:
                out.append(re.escape(c))
            else:
                body = pattern[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z", re.IGNORECASE)


def glob_matches(pattern: str, rel_path: str) -> bool:
    """Does a ripgrep-style glob match rel_path? A pattern without '/' matches the base name at any depth."""
    rel_path = rel_path.replace(os.sep, "/")
    for alt in expand_braces(pattern):
        alt = alt[2:] if alt.startswith("./") else alt
        rx = glob_regex(alt)
        if rx.match(rel_path) or ("/" not in alt and rx.match(rel_path.rsplit("/", 1)[-1])):
            return True
    return False


def has_glob(s: str) -> bool:
    return any(ch in s for ch in "*?[")
