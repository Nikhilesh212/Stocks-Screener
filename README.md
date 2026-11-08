# Indian equity research system (Claude Code)

A research team for Indian listed equities that runs inside Claude Code. When you ask for it, a Claude Code session forms its own view of the market, hunts for candidates through several lenses, researches each one from primary filings, has every thesis attacked by an independent red team, builds a portfolio and presents it to you. You review, challenge and decide. Picks you approve are frozen in an append-only ledger and tracked forward against the Nifty 500 Total Return Index, so the system's real record builds up over time.

Code fetches facts and computes numbers, with provenance on every number; Claude decides what matters. No code ranks or scores stocks, nothing places orders, and the output is research for your own decisions, not investment advice.

**New here? Read [`docs/HANDOVER.md`](docs/HANDOVER.md) first.** It covers what was built, which data sources work, known gaps, the defaults to confirm before the first real run, and how big a full run is.

## Setup

Requirements: Linux or macOS, [uv](https://docs.astral.sh/uv/), Claude Code.

```bash
uv sync
```

This installs Python 3.12 and the pinned dependencies into `.venv/`. Credentials are optional: copy `.env.example` to `.env` only if you want to override the User-Agent or add a key (never commit `.env`).

**First time in Claude Code, and after pulling changes to `.claude/`:** restart Claude Code in the repo root and accept the workspace-trust prompt. The four subagents and their guard hooks load only at session start, and project hooks run only in a trusted workspace. `.claude/settings.json` pre-approves `uv run python -m tools ...`, web search/fetch and writes under `runs/`; anything else asks you first.

## Tests and smoke test

```bash
uv run pytest
```

Offline: data-layer tests use recorded fixtures, compute and ledger tests use synthetic inputs, hook tests feed the guards sample tool calls.

```bash
uv run python -m tools smoke --table
```

Hits the live sources for RELIANCE, HDFCBANK and CAMS (or `--symbols A,B`) and prints a status table; the result is saved to `data/cache/smoke_status.json`. Run it before a research run to see which sources are up.

## The tools

`uv run python -m tools <group> <command> --help` lists every option. Output is JSON on stdout; check `status` first. Groups:

- `data`: `resolve`, `prices`, `bhavcopy`, `index` (history, constituents, snapshot), `filings` (list, get, search, pages), `financials`, `shareholding`, `macro`, `events`.
- `compute`: `calc`, `ratios`, `valuation`, `reverse_dcf`, `technicals`, `base_rates`, `portfolio`, `costs_tax`.
- `ledger`: `freeze`, `mark`, `review`, `postmortem`, `correct`.
- `smoke`.

Examples:

```bash
uv run python -m tools data resolve CAMS
```

```bash
uv run python -m tools compute valuation CAMS --peers KFINTECH
```

Downloads are cached in `data/cache/` keyed by ISIN (gitignored).

## Running research

Ask in plain words in a Claude Code session started in this repo; the `equity-research` skill picks it up. You can also type `/equity-research` with the mode as an argument.

| Mode | Say something like | What happens |
|---|---|---|
| New run | "run research", "Dhanteras picks", "Diwali portfolio", "find stocks to buy" | Phases 0-7 below |
| Single-company deep dive | "deep dive on Computer Age Management Services" | one analyst plus one red team; no portfolio, no freeze unless you ask |
| Review | "review my picks", "check kill criteria" | `ledger review` and `ledger mark`, kill criteria judged per pick, hold/trim/exit/re-underwrite recommendations; notes in `runs/<run_id>/reviews/<date>.md` |
| Post-mortem | "post-mortem 2026-10-15-dhanteras" | `ledger postmortem`, decision quality vs outcome, calibration, cohorts, at most five lessons into `ledger/lessons.md` |

Add "dry run" to any request to use a `<date>-dryrun` run id and the test ledger (`ledger/test/`, gitignored).

A new run goes through these phases, writing everything into `runs/<run_id>/`:

0. **Mandate and memory**: you confirm `config/mandate.yaml` for this run (horizon, capital, drawdown tolerance, names, exclusions, themes); lessons from past post-mortems are applied; open runs are reviewed first.
1. **Market read**: the `market-strategist` subagent writes `market_view.md`; you see a ten-line summary and may push back.
2. **Hunting**: one `hunter` per lens (quality, value, momentum, policy/capex, small/mid caps, contrarian), merged into `candidates.json` and `shortlist.md` (15-25 names). **Checkpoint**: you approve the shortlist after seeing the usage estimate.
3. **Deep dives**: one fresh `company-analyst` per name; dossier, machine summary and a separate conviction file with the probabilities.
4. **Red team**: one `red-team` per dossier re-fetches the key numbers and attacks the thesis without seeing the conviction file; material discrepancies go back to a fresh analyst once.
5. **Portfolio**: sizing within the mandate, `compute portfolio` checks, hidden common bets, comparison with buying the index and with cash.
6. **Presentation**: the final report; challenge it.
7. **Freeze**: only on your explicit approval, `ledger freeze` records the picks and cohorts A-E, and the run is committed to local git.

How a run is judged: expected excess return over the Nifty 500 TRI over the horizon, net of costs and tax, within the mandate's limits, plus calibration of the stated probabilities (Brier score). Fewer picks, cash or "buy the index" are legitimate answers. Details: `.claude/skills/equity-research/references/evaluation.md`.

### Scale of a full run

A full run spawns about 1 strategist + 6 hunters + one analyst and one red team per shortlisted name, plus a second round for names sent back. For 20 names that is roughly 45-55 subagent runs at high effort (Opus, except the six hunters on Sonnet), each with dozens to over a hundred tool calls, and several hours of wall time. It uses a lot of your plan's usage; the session tells you its estimate before the deep dives and you can cut the list. A single-company deep dive is two or three subagent runs. Measured numbers from the 2026-11-08 dry run, and the estimate for a full 20-name run, are in [`docs/HANDOVER.md`](docs/HANDOVER.md#scale-of-a-full-run).

Expect some permission prompts during a run: copying round-1 files before a re-analysis, edits under `ledger/`, and any Bash command a subagent runs other than the tools CLI and Claude Code's built-in read-only commands (`ls`, `cat`, `grep`, `find`, ...).

## Review and post-mortem

- **Review** after each results season or big news: say "review my picks" (or name the run). Each kill criterion is judged fired, not fired or unclear, with the announcement and page as evidence. `mark` returns are gross of costs and tax.
- **Post-mortem** at the horizon end (an interim one before it with `--force`): returns net of costs and tax, with and without the annual LTCG exemption; Brier scores and a calibration table; cohort comparisons (A final portfolio, B all deep-dived names, C red-team kills, D all candidates, E the index) that show which stage adds value. One run's gaps are mostly noise: read them across runs.

## Where things live

| Path | What |
|---|---|
| `tools/` | Python CLI: `common/` (provenance, cache, HTTP policy, entity resolution), `data/`, `compute/`, `ledger/` |
| `tests/` | pytest suite and recorded fixtures (`tests/fixtures/record.py` re-records them) |
| `config/mandate.yaml` | horizon, benchmark, limits, liquidity floor, exclusions |
| `config/sources.yaml` | data sources, priority, status |
| `config/costs.yaml` | transaction costs and tax rates, each with source and date |
| `.claude/skills/equity-research/` | `SKILL.md` (the run protocol) and `references/` (failure modes, red flags, valuation guide, output schemas, evaluation) |
| `.claude/agents/` | `market-strategist`, `hunter`, `company-analyst`, `red-team` |
| `.claude/hooks/` | guards that confine each subagent's writes and Bash to its own area of the run folder, and keep conviction files from the red team |
| `runs/<run_id>/` | one folder per run; layout in `references/output-schemas.md` |
| `ledger/` | `picks.jsonl` (append-only), `postmortems/`, `lessons.md`; `ledger/test/` for dry runs |
| `docs/HANDOVER.md` | hand-over: start here before the first real run |
| `docs/BUILD_STATE.md` | build status, decisions and known gaps; `docs/SPEC.md` is the original specification |

## Things to confirm

- `config/mandate.yaml`: the defaults were confirmed on 2026-11-08 (marked `# user-confirmed 2026-11-08`). Phase 0 still asks you to confirm or change them for each run; edit the file to change the defaults.
- `config/costs.yaml`: brokerage and DP charge are defaults you confirmed on 2026-11-08 (the more expensive of Zerodha and Groww). Revisit them if you choose a broker, and re-verify statutory rates after each Budget.

## Known gaps

- **Financial history**: exchange XBRL starts around FY18 and some years are missing (RELIANCE has no FY22 filing; CAMS and HDFCBANK consolidated from FY23/FY24). Five- and ten-year CAGRs often come back null with a reason; analysts take older years from annual reports. Balance sheet and cash flow exist only at H1 and FY.
- **Banks**: NIM, CASA and credit cost are not in XBRL (analysts read presentations); asset quality is standalone-only, and HDFCBANK standalone XBRL stops at Q3FY25. HDFCBANK has no promoter group.
- **Macro**: no keyless source for CPI or crude; agents cite dated releases.
- **Index P/E** changed method on 31-Mar-2021 (standalone to consolidated earnings); `base_rates` splices it by default.
- **Price history**: the cache holds 2-3 years unless `data prices SYM --years 10` is run, which analysts do before valuation. Peers need their own price cache.
- **Costs**: grandfathering of pre-2018 cost, STCG basic-exemption absorption, rebate under s.87A and your slab rate are not modelled (dividend tax only with `--slab-rate`).
- **Industry**: `data resolve` gives the broad index-list industry; basic industry comes from announcements.
- **Rate limits are per process.** Parallel subagents each run their own tools process, so NSE sees several request streams at once. The skill starts deep dives in batches of about five; if `source_error` or HTTP 429 shows up, use smaller batches.
- **Scanned PDFs**: some results PDFs have no text layer (`filings get` warns "no text layer (scanned?); OCR not attempted"). There is no OCR, so analysts fall back to transcripts and dated press reports. In the 2026-11-08 dry run this hit two of three companies.
- **Own-history valuation percentiles** rest on the XBRL earnings history, often only 25-28 months, even with 10 years of prices; the tools label them "shorter than 5y".
- **Hooks verified live** (2026-11-08): out-of-area writes, `ledger` from subagents, redirection and non-allowlisted commands are blocked, and the red team cannot read conviction files. Not verified: that `Edit(runs/**)` matches subagent writes without a prompt (the test session ran in bypass-permissions mode).

Open follow-ups: whether subagents may run the read-only `ledger mark` during reviews (the hooks currently refuse the whole `ledger` group).

## Disclaimer

This is a research tool, not investment advice. The author is not registered with SEBI as an investment adviser or research analyst, and nothing in this repository or its output is a recommendation to buy or sell any security. You make and own your decisions.

The tools read public sources (NSE, niftyindices.com, RBI and company filings) under those sources' own terms of use. You are responsible for following them, keeping request rates polite, and setting `ER_USER_AGENT` in `.env` to identify yourself. Runs use your Claude Code plan; a full run spans several 5-hour usage windows (see [`docs/HANDOVER.md`](docs/HANDOVER.md#scale-of-a-full-run)).

## Licence

Copyright (C) 2026 Nikhilesh212.

Released under the [GNU Affero General Public License v3.0 only](LICENSE) (AGPL-3.0-only). You may use, modify and even sell it, but if you distribute it, or let others use a modified version over a network, you must release your complete source under the same licence. The PDF library it depends on, PyMuPDF, is also AGPL-3.0.

**Commercial licence.** To build this into a closed-source product or service without the AGPL's obligations, contact [Nikhilesh212 on GitHub](https://github.com/Nikhilesh212) for a separate commercial licence.

Contributions are accepted on the terms in [`CONTRIBUTING.md`](CONTRIBUTING.md).
