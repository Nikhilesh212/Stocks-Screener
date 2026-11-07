"""PreToolUse guard hooks in .claude/hooks/, run as Claude Code runs them: JSON on stdin, exit 2 blocks.

Each test gets a throwaway project root (CLAUDE_PROJECT_DIR) holding one run
folder with a dossier and its conviction file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / ".claude" / "hooks"
RUN = "2026-11-08-test"


@pytest.fixture
def root(tmp_path):
    d = tmp_path / "runs" / RUN
    (d / "dossiers").mkdir(parents=True)
    (d / "redteam").mkdir()
    (d / "dossiers" / "CAMS.md").write_text("# CAMS dossier\n")
    (d / "dossiers" / "CAMS.json").write_text("{}")
    (d / "dossiers" / "CAMS.conviction.json").write_text('{"p_beat_benchmark": 0.6}')
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "notes.json").write_text("{}")
    return tmp_path


def hook(root: Path, script: str, tool: str, tool_input: dict, *args: str, cwd: Path | None = None, raw: str | None = None):
    payload = raw if raw is not None else json.dumps(
        {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or root)})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    p = subprocess.run([sys.executable, str(HOOKS / script), *args], input=payload, capture_output=True, text=True,
                       env=env, timeout=30)
    return p.returncode, p.stderr


R = f"runs/{RUN}"


# --- guard_writes --------------------------------------------------------------

@pytest.mark.parametrize("path", [f"{R}/dossiers/CAMS.md", f"{R}/dossiers/work/CAMS/fin.json", "ABS"])
def test_writes_allowed_in_own_area(root, path):
    path = str(root / R / "dossiers" / "CAMS.json") if path == "ABS" else path
    assert hook(root, "guard_writes.py", "Write", {"file_path": path}, "dossiers/")[0] == 0


@pytest.mark.parametrize("path,why", [
    (f"{R}/redteam/CAMS.md", "not in your write area"),
    (f"{R}/candidates.json", "not in your write area"),
    (f"{R}/dossiers", "not in your write area"),
    (f"{R}/dossiers/../redteam/CAMS.md", "not in your write area"),
    ("tools/x.py", "outside runs/"),
    ("/etc/passwd", "outside runs/"),
    ("runs/latest/dossiers/CAMS.md", "is not a run_id"),
    ("runs/2026-11-09-typo/dossiers/CAMS.md", "does not exist"),
])
def test_writes_blocked_outside_area(root, path, why):
    code, err = hook(root, "guard_writes.py", "Edit", {"file_path": path}, "dossiers/")
    assert code == 2 and why in err


def test_writes_exact_file_spec_and_notebook(root):
    args = ("market_view.md", "market/")
    assert hook(root, "guard_writes.py", "Write", {"file_path": f"{R}/market_view.md"}, *args)[0] == 0
    assert hook(root, "guard_writes.py", "Write", {"file_path": f"{R}/market/base_rates.json"}, *args)[0] == 0
    assert hook(root, "guard_writes.py", "Write", {"file_path": f"{R}/market_view.md.bak"}, *args)[0] == 2
    assert hook(root, "guard_writes.py", "NotebookEdit", {"notebook_path": f"{R}/x.ipynb"}, *args)[0] == 2


def test_writes_symlink_escape_blocked(root):
    (root / R / "dossiers" / "out").symlink_to(root / "data")
    code, err = hook(root, "guard_writes.py", "Write", {"file_path": f"{R}/dossiers/out/notes.json"}, "dossiers/")
    assert code == 2 and "outside runs/" in err


def test_writes_fail_closed(root):
    assert hook(root, "guard_writes.py", "Read", {"file_path": "/etc/passwd"}, "dossiers/")[0] == 0  # not a write
    assert hook(root, "guard_writes.py", "Write", {}, "dossiers/")[0] == 2
    code, err = hook(root, "guard_writes.py", "Write", {"file_path": f"{R}/dossiers/x.md"})
    assert code == 2 and "misconfigured" in err
    assert hook(root, "guard_writes.py", "Write", {"file_path": f"{R}/x"}, "../")[0] == 2
    assert hook(root, "guard_writes.py", "Write", {}, "dossiers/", raw="not json")[0] == 2


# --- guard_bash ------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "uv run python -m tools data prices CAMS --years 10",
    'uv run python -m tools compute calc "(a-b)/b*100" --var a=5 --var b=4 --unit %',
    f"uv run python -m tools compute ratios CAMS --out {R}/dossiers/work/ratios.json",
    f"uv run python -m tools data financials CAMS --out={R}/dossiers/work/fin.json",
    "uv run python -m tools --help",
    "uv run python -m tools data filings list CAMS --kind transcripts 2>&1 | jq '.status'",
    "uv run python -m tools data macro 2>/dev/null | head -50",
    f"ls -la runs && cat {R}/dossiers/CAMS.md | head -20",
    "grep -n 'a|b > c' data/notes.json",
    'grep -n "price$" data/notes.json',
    "find runs -name '*.md' -type f",
    "sort -n -k2 data/notes.json | uniq -c",
    f"cd {R} && uv run python -m tools data resolve CAMS --out dossiers/work/id.json",
    "wc -l data/notes.json; date +%F",
])
def test_bash_allowed(root, cmd):
    code, err = hook(root, "guard_bash.py", "Bash", {"command": cmd}, "dossiers/")
    assert code == 0, err


@pytest.mark.parametrize("cmd,why", [
    ("cat data/notes.json > x.json", "redirection"),
    ("echo x >> f", "redirection"),
    ("ls 2>err.txt", "redirection"),
    ("cat <<EOF\nx\nEOF", "input redirection"),
    ("tee x.json", "not allowed"),
    ("cp a b", "not allowed"),
    ("rm -rf runs", "not allowed"),
    ("python3 -c 'print(1)'", "not allowed"),
    ("sed -i s/a/b/ data/notes.json", "not allowed"),
    ("ls | sh", "not allowed"),
    ("ls; rm x", "not allowed"),
    ("uv run python -c 'import os'", "exactly"),
    ("uv run --with requests python -m tools data prices CAMS", "exactly"),
    ("uv run python -m tools ledger freeze r --approved me", "main session"),
    ("uv run python -m tools smoke", "main session"),
    ("uv run python -m tools compute ratios CAMS --out tools/x.json", "outside runs/"),
    (f"uv run python -m tools compute ratios CAMS --out={R}/redteam/x.json", "not in your write area"),
    (f"uv run python -m tools compute ratios CAMS --ou {R}/candidates.json", "not in your write area"),
    ("uv run python -m tools compute ratios CAMS --out", "needs a file path"),
    ("echo $(rm x)", "substitution"),
    ("echo `rm x`", "substitution"),
    ("echo $HOME", "expansion"),
    ("cat $'\\x2eenv'", "expansion"),
    ("ls & rm x", "background"),
    ("(ls)", "subshells"),
    ("find . -delete", "find with"),
    ("find . -exec rm {} \\;", "find with"),
    ("sort -o out.txt data/notes.json", "sort -o"),
    ("sort -no out.txt data/notes.json", "sort -o"),
    ("uniq data/notes.json out.txt", "output file"),
    ("rg --pre cat x", "--pre"),
    ("X=1 ls", "environment assignments"),
    ("cat .env", ".env"),
    ("cat 'unterminated", "unterminated"),
    ("", "empty"),
])
def test_bash_blocked(root, cmd, why):
    code, err = hook(root, "guard_bash.py", "Bash", {"command": cmd}, "dossiers/")
    assert code == 2 and why in err, err


def test_bash_ignores_other_tools(root):
    assert hook(root, "guard_bash.py", "Read", {"file_path": "x"}, "dossiers/")[0] == 0


# --- guard_conviction ------------------------------------------------------------

D = f"{R}/dossiers"


@pytest.mark.parametrize("tool,ti", [
    ("Read", {"file_path": f"{D}/CAMS.conviction.json"}),
    ("Read", {"file_path": f"{R}/redteam/link.json"}),  # symlink to the conviction file
    ("Grep", {"pattern": "p_beat", "path": "runs"}),
    ("Grep", {"pattern": "p_beat"}),  # default path = cwd = project root
    ("Grep", {"pattern": "p_beat", "path": D, "glob": "*.json"}),
    ("Grep", {"pattern": "p_beat", "glob": "**/*"}),
    ("Grep", {"pattern": "p_beat", "path": f"{D}/CAMS.conviction.json"}),
    ("Grep", {"pattern": "p_beat", "type": "json"}),
    ("Glob", {"pattern": "**/*.json"}),
    ("Glob", {"pattern": "runs/*/dossiers/*"}),
    ("Glob", {"pattern": "*.{md,json}", "path": D}),
    ("Glob", {"pattern": "*conviction*"}),
    ("Bash", {"command": f"cat {D}/CAMS.conviction.json"}),
    ("Bash", {"command": f"cat {D}/*"}),
    ("Bash", {"command": f"cat {D}/CAMS.c?nviction.json"}),
    ("Bash", {"command": f"cat {D}/CAMS.con\\viction.json"}),
    ("Bash", {"command": f'cat "{D}/CAMS.con""viction.json"'}),
    ("Bash", {"command": f"cat {D}/CAMS.{{con,x}}viction.json"}),
    ("Bash", {"command": "grep -rn p_beat runs"}),
    ("Bash", {"command": "rg p_beat"}),
    ("Bash", {"command": f"cd {D} && cat *"}),
    ("Bash", {"command": f"jq . {D}"}),
    ("Bash", {"command": f"find {D} -exec cat {{}} +"}),
])
def test_conviction_blocked(root, tool, ti):
    (root / R / "redteam" / "link.json").symlink_to(root / D / "CAMS.conviction.json")
    code, err = hook(root, "guard_conviction.py", tool, ti)
    assert code == 2 and "conviction" in err, err


@pytest.mark.parametrize("tool,ti", [
    ("Read", {"file_path": f"{D}/CAMS.md"}),
    ("Read", {"file_path": str(Path("ABS"))}),
    ("Grep", {"pattern": "moat", "path": "runs", "glob": "*.md"}),
    ("Grep", {"pattern": "moat", "type": "md"}),
    ("Grep", {"pattern": "x", "path": "data"}),
    ("Grep", {"pattern": "x", "path": f"{D}/CAMS.json"}),
    ("Glob", {"pattern": "**/*.md"}),
    ("Glob", {"pattern": "*.json", "path": f"{R}/redteam"}),
    ("Bash", {"command": f"cat {D}/CAMS.md {D}/CAMS.json"}),
    ("Bash", {"command": f"ls -la {D}"}),
    ("Bash", {"command": "uv run python -m tools data prices CAMS"}),
    ("Bash", {"command": f"grep -rn x {R}/redteam data"}),
    ("Write", {"file_path": f"{D}/CAMS.conviction.json"}),  # not this guard's job
])
def test_conviction_allowed(root, tool, ti):
    if ti.get("file_path") == "ABS":
        ti = {"file_path": str(root / D / "CAMS.json")}
    code, err = hook(root, "guard_conviction.py", tool, ti)
    assert code == 0, err
