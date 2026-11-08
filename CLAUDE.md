# Indian equity research system

On-demand research on Indian listed equities inside Claude Code: Python tools fetch facts and compute numbers; Claude decides what matters, where to look and what to believe.
Output is research for the user's own decisions, not advice. Picks the user approves are frozen in an append-only ledger and tracked forward against the Nifty 500 TRI.

## Hard rules

- Research only. Never place, modify or cancel orders, and never call a broker order endpoint.
- Every number has provenance: a tool output, or a document cited with period and page, or a dated source. No numbers from memory.
- Arithmetic only in code: `uv run python -m tools compute calc "<expr>" --var a=<v> ...`. Never mental math.
- No code that ranks, scores or recommends stocks. Screens are search aids, never gates.
- Never commit `.env`, `data/cache/`, `runs/` or `ledger/` records (all gitignored: `origin`, GitHub Nikhilesh212/Stocks-Screener, is public). Push to `origin` only when the user explicitly asks.
- The ledger is append-only: only `uv run python -m tools ledger ...` writes `ledger/picks.jsonl`; fix a record with `ledger correct`, never by editing.

## Commands

- Setup: `uv sync`
- Tests (offline, recorded fixtures): `uv run pytest`. The fixtures are real NSE data kept out of git; record them once with `uv run python tests/fixtures/record.py --fetch` (fixture tests skip until then)
- Smoke test (live sources): `uv run python -m tools smoke --table`
- Tools: `uv run python -m tools <data|compute|ledger> <command> --help`; JSON on stdout, check `status` first.
- Research modes (skill `equity-research`): new run ("run research", "Dhanteras picks"), review ("review my picks"), post-mortem ("post-mortem <run_id>"), single company ("deep dive on <company>"). Add "dry run" to keep the real ledger clean (`--ledger-dir ledger/test`).

## Where things live

- `tools/` CLI (`data`, `compute`, `ledger`, `smoke`); `tests/` pytest
- `config/` `mandate.yaml`, `sources.yaml`, `costs.yaml`
- `.claude/skills/equity-research/` `SKILL.md` (run protocol) and `references/`; `.claude/agents/` four subagents; `.claude/hooks/` guards on subagent writes, Bash and conviction files
- `runs/<run_id>/` one folder per run; `ledger/` `picks.jsonl`, `postmortems/`, `lessons.md`; `ledger/test/` dry runs. `runs/` and `ledger/` records are gitignored and stay on this machine
- `data/cache/` downloads and extracted text keyed by ISIN (gitignored)
- `docs/BUILD_STATE.md` build status, decisions, known gaps; `docs/SPEC.md` original spec
