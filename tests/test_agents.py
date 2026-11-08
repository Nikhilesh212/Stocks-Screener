"""Static checks on the subagent definitions and the skill: frontmatter, guard hooks, and that every
tools command they tell an agent to run exists with the options they name."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / ".claude" / "agents"
SKILL = ROOT / ".claude" / "skills" / "equity-research" / "SKILL.md"
HOOKS = ROOT / ".claude" / "hooks"

# agent -> the write area passed to guard_writes.py / guard_bash.py (see docs/BUILD_STATE.md, Session E2 brief)
AREAS = {
    "market-strategist": "market_view.md market/",
    "hunter": "hunters/",
    "company-analyst": "dossiers/",
    "red-team": "redteam/",
}
HOOK_CMD = 'python3 "${{CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/{script}"{args}'


def frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm), body


@pytest.mark.parametrize("name", sorted(AREAS))
def test_agent_frontmatter(name):
    fm, body = frontmatter(AGENTS / f"{name}.md")
    assert fm["name"] == name
    assert fm["model"] == ("sonnet" if name == "hunter" else "opus") and fm["effort"] == "high"
    assert fm["disallowedTools"] == "Agent"
    assert [t.strip() for t in fm["tools"].split(",")] == ["Read", "Grep", "Glob", "Bash", "WebSearch", "WebFetch", "Write", "Edit"]
    hooks = {h["matcher"]: [x["command"] for x in h["hooks"]] for h in fm["hooks"]["PreToolUse"]}
    area = " " + AREAS[name]
    assert hooks["Write|Edit|MultiEdit|NotebookEdit"] == [HOOK_CMD.format(script="guard_writes.py", args=area)]
    assert hooks["Bash"] == [HOOK_CMD.format(script="guard_bash.py", args=area)]
    if name == "red-team":
        assert hooks["Read|Grep|Glob|Bash"] == [HOOK_CMD.format(script="guard_conviction.py", args="")]
    else:
        assert len(hooks) == 2
    for cmd in (c for cs in hooks.values() for c in cs):
        assert (HOOKS / re.search(r"hooks/(\w+\.py)", cmd).group(1)).is_file()
    # every reference an agent points to exists
    for ref in re.findall(r"references/([\w-]+\.md)", body):
        assert (SKILL.parent / "references" / ref).is_file(), ref


def test_skill_frontmatter_and_size():
    fm, body = frontmatter(SKILL)
    assert fm["name"] == "equity-research"
    assert len(fm["description"]) + len(fm.get("when_to_use") or "") <= 1536
    for phrase in ("run research", "stock ideas", "find stocks to buy", "Dhanteras", "Diwali portfolio",
                   "Muhurat", "review my picks", "check kill criteria", "post-mortem", "deep dive on"):
        assert phrase in fm["description"], phrase
    assert len(SKILL.read_text().splitlines()) < 500
    for agent in AREAS:
        assert f"`{agent}`" in body, agent
    for ref in ("failure-modes.md", "red-flags-india.md", "valuation-guide.md", "output-schemas.md", "evaluation.md"):
        assert ref in body, ref


def _subparsers(p) -> dict:
    for a in p._actions:
        if isinstance(a.choices, dict):
            return a.choices
    return {}


def _documented_commands(text: str):
    """Backticked snippets that start with a tools group, with the `uv run python -m tools` prefix optional."""
    for snip in re.findall(r"`([^`]+)`", text):
        toks = snip.replace("uv run python -m tools ", "").split()
        if len(toks) >= 2 and toks[0] in ("data", "compute", "ledger"):
            yield snip, toks


def test_documented_commands_exist():
    from tools.cli import build_parser
    root = _subparsers(build_parser())
    files = [*sorted(AGENTS.glob("*.md")), SKILL, ROOT / "README.md", ROOT / "CLAUDE.md"]
    checked, problems = 0, []
    for f in files:
        for snip, toks in _documented_commands(f.read_text()):
            p, rest = root[toks[0]], toks[1:]
            if not rest or rest[0].startswith("<") or "|" in rest[0]:
                continue  # placeholders like `ledger freeze | mark | ...`
            while rest and rest[0] in _subparsers(p):
                p, rest = _subparsers(p)[rest[0]], rest[1:]
            if _subparsers(p):
                if not (rest and (rest[0].startswith("<") or "|" in rest[0] or rest[0] == "...")):
                    problems.append(f"{f.name}: `{snip}`: unknown subcommand")
                continue
            options = {s for a in p._actions for s in a.option_strings}
            problems += [f"{f.name}: `{snip}`: no option {o}" for o in re.findall(r"--[a-z][a-z0-9-]*", snip) if o not in options]
            checked += 1
    assert not problems, problems
    assert checked > 40
