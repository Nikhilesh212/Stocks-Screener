# Hand-over (Phase G, 2026-11-08)

The research system is built and has passed one end-to-end dry run. This page is for whoever runs it next. It covers what exists, what works, what does not, what you must confirm, and how to use it. Details and history live in [`BUILD_STATE.md`](BUILD_STATE.md); the original spec is [`SPEC.md`](SPEC.md). Every number below comes from a tool output, a config file or `BUILD_STATE.md`. Figures marked [C] were computed there with `compute calc`.

## Before the first real run

1. **Restart Claude Code in the repo root.** Session F changed the four agent definitions, and Claude Code loads them only when a session starts. A session started before 11:37 IST on 2026-11-08 still has the old ones. Accept workspace trust when asked, because the project agents' guard hooks run only after trust is accepted.
2. **Confirm the mandate DEFAULTs** in [`config/mandate.yaml`](../config/mandate.yaml) (list below). Phase 0 asks about them every run; edit the file to change the defaults.
3. **Confirm the cost DEFAULTs** in [`config/costs.yaml`](../config/costs.yaml) once you choose a broker, and re-verify the statutory rates after each Budget.
4. **Decide the open follow-ups** below. None of them blocks a run.
5. **Plan for the size of a run.** A full run spans several 5-hour usage windows (see "Scale of a full run").

## What was built

| Phase | What | Result |
|---|---|---|
| A, B | Questions, docs, plan | User chose all defaults; plan approved |
| C | Data layer (`tools data ...`) and live smoke test | 21/21 smoke checks ok |
| D | Compute group, ledger, `config/costs.yaml`, tests | 63 tests |
| E1 | 5 references, 3 guard hooks, `.claude/settings.json`, hook tests | 100 hook cases |
| E2 | 4 subagents, `equity-research` skill, `CLAUDE.md`, README, agent tests | 170 tests |
| F | Hook checks in a live session, dry run `2026-11-08-dryrun`, 5 tool fixes and 4 definition fixes | 174 tests; frozen to `ledger/test` only |
| G | This hand-over | see "Health check" |

Components:
- **Tools CLI**: `uv run python -m tools <data|compute|ledger|smoke> ...`. The output is JSON with provenance on every number; check `status` first. `data` covers resolve, prices (adjusted for corporate actions), bhavcopy, index history and constituents, filings (list, get, search, pages with page numbers), XBRL financials, shareholding, macro and events. `compute` covers calc, ratios, valuation, reverse DCF, technicals, base rates, portfolio and costs/tax. `ledger` covers freeze, mark, review, postmortem and correct. The full tables are in `BUILD_STATE.md` under "Data layer as built". `--help` works on every command.
- **Subagents** (`.claude/agents/`): `market-strategist`, `hunter`, `company-analyst` and `red-team`. All four use Opus at high effort. The `Agent` tool is blocked, so none can spawn further subagents.
- **Skill** (`.claude/skills/equity-research/`): `SKILL.md` holds the run protocol for every mode. `references/` holds the output schemas, evaluation, failure modes, India red flags and the valuation guide.
- **Guard hooks** (`.claude/hooks/`): `guard_writes.py` limits each agent's writes to its own area under `runs/<run_id>/`. `guard_bash.py` allows only the tools CLI and read-only commands, and refuses `ledger` to subagents. `guard_conviction.py` stops the red team from reading any `*.conviction.json`. All three fail closed.
- **Settings** (`.claude/settings.json`): the allowlist is `Bash(uv run python -m tools *)`, `WebSearch`, `WebFetch` and `Edit(runs/**)`. The deny list is `Read(./.env)` and `Read(./**/.env)`, added on 2026-11-08 with your approval. A test in a bypass-mode session showed the Read tool refused a dummy `.env` at the root and one in a subfolder, while `.env.example` stayed readable. The hooks already block `.env` in Bash.
- **Ledger**: `ledger/picks.jsonl` is append-only and written only by `ledger ...`. Post-mortems go in `ledger/postmortems/` and lessons in `ledger/lessons.md`. Dry runs go to `ledger/test/`, which is gitignored.

## Health check (Phase G, 2026-11-08)

- `uv run pytest`: **174 passed** in 9.16 s.
- `uv run python -m tools smoke --table` on RELIANCE, HDFCBANK and CAMS: **21/21 ok** and no bare-number violations (run at 11:44 IST). Most checks were served from that day's cache in under 2 s each. The index and macro checks went live (7.3 s and 13.4 s). Corporate-action checks passed: RELIANCE bonus x2 (ex 2024-10-28), HDFCBANK bonus x2 (ex 2025-08-26) and CAMS split x5 (ex 2025-12-05). CPI reported `unavailable` as expected.
- Agent definitions: `company-analyst.md` contains the dated litigation and regulator news sweep, and all four agents carry the blocked-Bash rules. The Phase G session started at 11:42 IST, after the definitions were last edited at 11:37 IST, so subagents spawned from it load the Session F versions.

## Data sources

From [`config/sources.yaml`](../config/sources.yaml) (verified 2026-11-08) and the dry run.

| Source | Status | Notes |
|---|---|---|
| NSE archives (nsearchives) | ok | bhavcopy, equity lists, XBRL, filings PDFs |
| NSE website API | ok | prices (chunked; a chunk that hits the 70-row cap is split and refetched), announcements, events, shareholding, index snapshot, FII/DII provisional flows |
| niftyindices.com | ok | TRI and index P/E, P/B, DY |
| NSE XBRL filings | ok | Ind AS financials from about FY18 |
| BSE equity bhavcopy | ok | BSE codes and cross-check |
| RBI homepage | ok | policy rates, INR/USD reference rate, G-sec yields (snapshot only) |
| BSE API | blocked | Akamai 403 even for robots.txt; NSE covers the same filings |
| MOSPI API (CPI) | unavailable | timed out on 2026-11-08; SSL error in the dry run; agents cite dated MOSPI releases |
| FRED (crude) | unavailable | timed out; agents cite dated releases |
| Business Standard | blocked (403) | seen in the dry run; use other dated press |
| Some company fact sheets | blocked (403) | seen in the dry run |
| Scanned results PDFs | unreadable | no text layer and no OCR; hit 2 of 3 companies in the dry run |
| NSDL FPI, Yahoo, broker API, Screener.in | not used | broker: none chosen; Screener.in not used by decision |

HTTP policy: the tools send an honest user agent, keep per-host rate limits, respect robots.txt, and treat 401/403 as blocked (never retried with altered headers). If a source refuses the honest user agent, you decide what to do about that source.

## How to trigger each mode

Start a Claude Code session in the repo root and ask in plain words. The `equity-research` skill picks the request up, or you can type `/equity-research <mode>`.

| Mode | Say something like | What happens |
|---|---|---|
| New run | "run research", "Dhanteras picks", "Diwali portfolio", "find stocks to buy" | Phases 0-7: mandate, market view, hunters, shortlist checkpoint (with a usage estimate), deep dives, red team, portfolio, report, then a freeze only if you approve it in chat |
| Single-company deep dive | "deep dive on CAMS", "analyse Computer Age Management Services" | One analyst and one red team. `run_id` is `YYYY-MM-DD-<sym>-deepdive` and there is no market view. No freeze unless you ask |
| Review | "review my picks", "check kill criteria", "how are my picks doing" | `ledger review` and `ledger mark`. Each kill criterion is judged fired, not fired or unclear, and each pick gets hold/trim/exit/re-underwrite. Notes go in `runs/<run_id>/reviews/<date>.md` |
| Post-mortem | "post-mortem 2026-10-15-dhanteras" | `ledger postmortem`: returns net of cost and tax, Brier score and calibration, cohorts A-E, and at most five lessons into `ledger/lessons.md` |
| Dry run | add "dry run" to any of the above, e.g. "dry run: deep dive on CAMS" | `run_id` is `<date>-dryrun[-slug]` and every ledger command gets `--ledger-dir ledger/test`. The real ledger stays clean |

A freeze happens only after your explicit approval in chat, and the run is then committed to local git. Nothing is ever pushed, and nothing places orders.

Expect permission prompts during a run in normal (non-bypass) mode: copying round-1 files before a re-analysis, git commits, edits under `ledger/`, and any Bash a subagent runs other than the tools CLI and Claude Code's built-in read-only commands.

## Scale of a full run

Measured in the Session F dry run (1 lens, 3 names, red team on all three):

| Agent | Minutes | Tokens | Tool calls |
|---|---|---|---|
| market-strategist | 13.1 | 134k | 65 |
| hunter (quality) | 52.8 | 194k | 95 |
| analyst INFY / HDFCBANK / BAJAJ-AUTO | 23.0 / 31.2 / 27.0 | 312k / 363k / 358k | 95 / 130 / 131 |
| red team INFY / BAJAJ-AUTO / HDFCBANK | 12.1 / 13.6 / 12.7 | 191k / 176k / 170k | 63 / 58 / 63 |

- Dry-run totals [C]: about 1.90M subagent tokens, 700 tool calls, 185 subagent-minutes and about 111 minutes of critical path. The main session's context ended near 276k tokens, and the account's 5-hour window was at 85%.
- **A full run** (1 strategist, 6 hunters, 20 names, about 4 round-2 pairs) at the per-agent averages (analyst 344k, red team 179k) [C]: **about 13.9M subagent tokens and about 3.4 hours of critical path** with deep dives in batches of five. That is several 5-hour usage windows on the current plan. Cutting the shortlist at the Phase 2 checkpoint is the main lever.
- A single-company deep dive is two or three subagent runs: about 523k tokens for one analyst and one red team at the averages above [C].
- The main session of a 20-name run will hold more context than the 3-name dry run did, so expect context compaction. The run's state lives in the files under `runs/<run_id>/`.

## Known gaps and limitations

- **Financial history**: Ind AS XBRL starts around FY18, and balance sheet and cash flow exist only at H1 and FY. Some years are missing: RELIANCE has no FY22 filing, and CAMS and HDFCBANK consolidated data starts at FY23/FY24. Five- and ten-year CAGRs often come back null with a reason, and older years come from annual reports.
- **Banks**: NIM, CASA and credit cost are not in XBRL, so analysts take them from presentations with page cites. GNPA/NNPA %, CET1 and ROA are in XBRL. Asset quality is in standalone filings only, and HDFCBANK standalone XBRL stops at Q3FY25. HDFCBANK has no promoter group.
- **Macro**: no keyless source for CPI or crude; agents cite dated releases.
- **Index P/E** changed method on 2021-03-31 (standalone to consolidated earnings). `base_rates` splices it by default. No tool computes P/B or dividend-yield percentiles for indices.
- **Valuation history**: the price cache holds 2-3 years until `data prices SYM --years 10` is run, which analysts do before valuation. Peers need their own price cache, and a peer without one is listed with the error. Own-history percentiles rest on the XBRL earnings history, which is often only 25-28 months even with 10 years of prices, and they are labelled "shorter than 5y".
- **Costs**: brokerage and DP charge are DEFAULTs. Grandfathering of pre-2018 cost, absorption of the STCG basic exemption, the s.87A rebate and your slab rate are not modelled (dividend tax is computed only with `--slab-rate`).
- **Industry**: `data resolve` gives the broad index-list industry; basic industry comes from announcements.
- **Rate limits are per process**, so parallel subagents send parallel request streams to NSE. The skill runs deep dives in batches of about five. The dry run hit no 429 with three analysts in parallel; five or more is untested.
- **No OCR**: scanned results PDFs cannot be read, and `filings get` warns about them. Analysts fall back to transcripts and dated press reports.
- **No prompt-free JSON validator for agents**: `jq` is not auto-approved and the hooks refuse `python`. Agents read their JSON back, and `ledger freeze` validates the freeze input.
- **`Edit(runs/**)` without prompts is unverified**: Sessions F and G ran in bypass-permissions mode.
- **Not yet exercised end to end**: the new analyst news sweep, holder-shaped kill criteria, a round-2 send-back (the dry run had no material discrepancies) and a red-team kill (cohort C was empty). See "Optional second dry run".

## DEFAULTs you must confirm

[`config/mandate.yaml`](../config/mandate.yaml). Each of these is marked `# DEFAULT - confirm`:

| Key | Default |
|---|---|
| `horizon_months` | 12 (12 or more also qualifies listed equity for long-term capital gains treatment) |
| `capital_inr` | null (optional; used only for liquidity and cost estimates) |
| `max_positions` | 10 |
| `max_weight` | 0.15 |
| `max_sector_weight` | 0.35 |
| `max_drawdown_tolerance` | 0.25 |
| `liquidity.min_adv_inr_crore` | 5 |
| `liquidity.max_days_to_exit` | 3 |
| `liquidity.participation_rate` | 0.15 |
| `exclusions`, `include_themes`, `avoid_themes` | empty |

Set by the spec and not marked DEFAULT: benchmark `NIFTY 500 TRI`, `min_positions: 0` (index or cash are valid answers), universe `NSE main board` (SME excluded), `allow_cash: true`, `instruments: equity_cash_only` (no F&O, leverage or shorting).

[`config/costs.yaml`](../config/costs.yaml). No broker has been chosen, so the more expensive of Groww and Zerodha is used:
- `brokerage_delivery`: 0.1% per executed order, capped at INR 20 with a floor of INR 5 (Groww). Zerodha charges 0 on delivery.
- `dp_charge_per_sell`: INR 23.6 per scrip per sell day including GST (Groww). Zerodha charges INR 15.34 including GST.
- Statutory items (STT, exchange, SEBI, stamp, GST, tax rates) were verified on 2026-11-08. Re-verify them after each Budget. Per-item notes: `docs/costs_research_2026-11-08.md`.

## Decisions made during the build

Approved by the user in Phases A-B: all mandate defaults; no broker; Screener.in not used; Python 3.12 via uv; local git only, no remote; CAMS as the small-cap smoke case; subagents on Opus at high effort with `Agent` blocked; the settings allowlist above.

Made in E1:
1. Red-team verdicts are `survives | weakened | killed`, and only `killed` puts a name in cohort C. A red-team JSON also has `send_back` (material numerical discrepancies) and `round` (1 or 2).
2. Probabilities, expected value, `p_beat_benchmark` and confidence live only in `dossiers/<SYM>.conviction.json`, never in the dossier `.md`/`.json`. The spec put probabilities in the dossier, but that would leak them to the red team.
3. Scenario `return_pct` is the gross total return over the horizon. `return_range_pct` must tile the number line (bear `[null, x)`, base `[x, y)`, bull `[y, null]`), or the scenario Brier score is skipped.
4. In run JSON files, facts are provenance objects copied from tool output, and judgments (returns, probabilities, weights) are plain numbers.
5. The run folder adds to the spec: `mandate.yaml`, `market/`, `hunters/`, `dossiers/work/`, `redteam/work/`, `dossiers/round1/` and `redteam/round1/` (top-level files are always the latest), `portfolio_holdings.json` and `reviews/<date>.md`.
6. Dossier `kill_criteria` are `{criterion, observe, by}` objects. The main session turns each into one string for `freeze_input.json`.
7. The main session has no hooks. It is bounded by the settings allowlist and by `SKILL.md`.

Made in E2:
1. Subagents reply to the main session in a few lines (paths, status, gaps, verdict). Analysts never put probabilities in the reply.
2. Analysts never open other dossiers, conviction files, `hunters/`, `candidates.json` or `shortlist.md`, and spawn prompts never mention the lens or why a name was shortlisted. Round-2 analysts may read `dossiers/round1/<SYM>.md` but never its conviction file.
3. Hunters use 3-year prices for a first look and label percentiles "shorter than 5y"; analysts fetch 10 years.
4. In deep-dive mode, `run_id` is `YYYY-MM-DD-<sym>-deepdive` and the analyst gets "market view: none for this deep dive". There is no freeze unless you ask.
5. "dry run" means `run_id` `<date>-dryrun[-slug]` and `--ledger-dir ledger/test` on every ledger command.
6. Deep dives run in batches of about 5, never more than 20 concurrent subagents.
7. Hard exclusions (universe, `exclusions`, liquidity floor) are applied mechanically. `avoid_themes` is judged per name with a stated reason.
8. A "material" red-team discrepancy is one that would change a conclusion, a scenario return, a valuation reading or a red-flag mark, or any entity, period, unit or basis mismatch on a decision-relevant number.
9. Phase 0 finds open runs by grepping `ledger/picks.jsonl` for run records without a postmortem, because there is no "list runs" command.

Fixes made in F:
1. `compute portfolio --mandate PATH` and `ledger freeze` read the run's confirmed `runs/<run_id>/mandate.yaml` rather than `config/mandate.yaml`.
2. `data prices` splits and refetches any chunk that hits NSE's 70-row cap. HDFCBANK traded two series in 2016-17, which truncated chunks.
3. `data events` wraps corporate-action numbers in provenance.
4. `data filings list` warns when `--limit` (default 60) cuts the announcements list.
5. Agent definitions:
   - The analyst runs a dated litigation and regulator news sweep and logs its queries.
   - Kill criteria are always written for a holder, even when the conclusion is "do not own".
   - All four agents list the always-blocked Bash forms, with "use Read with offset/limit" in place of `sed`.

## Open follow-ups needing your approval

- Letting subagents run the read-only `ledger mark` during reviews. The hooks currently refuse the whole `ledger` group.
- Adding `Bash(jq *)` to the allowlist, to give agents a prompt-free JSON check.
- A cross-process rate limiter (a file lock or timestamp file in `data/cache/`). It is not needed at 3 parallel analysts and untested at 5 or more.
- OCR for scanned PDFs. This needs a system package such as tesseract.

## Optional second dry run

Not run in Phase G. It would exercise what Session F did not:
- the analyst news sweep;
- holder-shaped kill criteria;
- a round-2 send-back, which happens only if the red team finds a material discrepancy;
- `Edit(runs/**)` permission prompts.

It costs about 0.5-1M tokens. A single-company `dry run: deep dive on <SYMBOL>` covers most of it. Run it from a session in normal (non-bypass) permission mode, or the prompt check proves nothing. It freezes only into `ledger/test/`, and only if you ask.
