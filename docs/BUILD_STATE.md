# Build state and handoff

Read this first in any new build session, then `docs/SPEC.md` (the original spec).
Each build phase runs in its own Claude Code session to keep context small.
Update this file and commit at the end of every phase.

## Phase status

| Phase | What | Status |
|---|---|---|
| A | Questions | done 2026-11-08: user chose all defaults |
| B | Docs + plan | done 2026-11-08: plan approved with defaults (below) |
| C | Data layer + smoke | done 2026-11-08 (fixture tests added in Session D1) |
| D | Compute + ledger + tests + costs.yaml | done 2026-11-08 (Sessions D1, D2): 63 tests green |
| E | References, 4 agents, SKILL.md, CLAUDE.md, README, settings.json, hooks | done 2026-11-08 (E1: references, hooks + tests, settings.json; E2: agents, SKILL.md, CLAUDE.md, README, `tests/test_agents.py`): 170 tests green |
| F | Dry run (needs Claude Code restart first) | done 2026-11-08: hooks verified live; dry run `2026-11-08-dryrun` end to end (1 lens, 3 names, red team on all, portfolio, freeze to `ledger/test`); 5 tool fixes + 4 definition fixes; 174 tests green. See "Session F results" |
| G | Hand-over | done 2026-11-08: agent definitions confirmed live; 174 tests green; smoke 21/21 ok; `docs/HANDOVER.md` written and linked from README. Second dry run not run (optional; needs the user's go-ahead). See "Session G results". Mandate and cost defaults confirmed by the user after hand-over (2026-11-08) |

## Decisions in force (user-approved)

- Mandate: all §9 defaults, each marked `# DEFAULT - confirm` in `config/mandate.yaml`.
- Broker: none. Screener.in: not used. Python 3.12 via uv (`uv run python -m tools ...`). Remote `origin` (GitHub Nikhilesh212/Stocks-Screener, public) added 2026-11-08; push only when the user asks.
- 2026-11-08 after hand-over (user-approved): history rewritten to author and committer Nikhilesh212 <58919032+Nikhilesh212@users.noreply.github.com> (also set in repo git config); `runs/2026-11-08-dryrun` removed from history (kept locally) and `runs/` plus `ledger/` records gitignored, so personal research never reaches the public repo (SKILL Phase 7 and post-mortem no longer commit); licence AGPL-3.0-only with commercial licences from the author, replacing MIT; `CONTRIBUTING.md` asks contributors for a licence that keeps commercial licensing possible.
- Smoke small cap: **CAMS** (Nifty Smallcap 250; split 10 -> 2 FV, ex 05-Dec-2025). Bonus test case: RELIANCE 1:1, ex 28-Oct-2024.
- HTTP policy: honest UA `equity-research-tool/0.1 (personal non-commercial research)`, per-host rate limits, robots.txt respected, 401/403 = blocked (never retry with altered headers). If a source refuses the honest UA, report to user; user decides per source.
- Subagents: `model: opus`, `effort: high`; block the `Agent` tool in all four (subagents can nest by default). Changed 2026-11-08 after hand-over, user-approved: `hunter` uses `model: sonnet` (effort high). Reason: breadth search re-checked downstream by Opus analysts and red teams; hunters were about 8% of a full run's tokens and the slowest agent on the critical path. Analyst and red team stay Opus high (hardest judgment, most of the cost).
- `.claude/settings.json` allowlist approved by user: `Bash(uv run python -m tools *)`, `WebSearch`, `WebFetch`, `Edit(runs/**)` (+ frontmatter hooks below).
- `.claude/settings.json` deny list (user-approved 2026-11-08, Session G): `Read(./.env)`, `Read(./**/.env)`.
- User restarts Claude Code after Phase E; the dry run happens after that.

## Claude Code facts verified from current docs (2026-11-08)

- Subagent frontmatter: name, description, tools, disallowedTools, model (sonnet|opus|haiku|fable|full ID|inherit), permissionMode (unreliable for subagents), maxTurns, skills (preload full SKILL.md), mcpServers, hooks, memory, background, omitClaudeMd, effort (low|medium|high|xhigh|max), isolation, color, initialPrompt.
- Subagents DO load project + user CLAUDE.md (unless `omitClaudeMd: true`). They CAN spawn subagents (depth 3) unless `Agent` is removed.
- No per-path write restriction in `tools:`. Enforce with `PreToolUse` hooks in each agent's frontmatter (matcher `Write|Edit`, script exits 2 to block). Project-agent hooks run only after workspace trust is accepted. Bash can write files too, so add a Bash allowlist hook.
- Planned hooks (`.claude/hooks/`): `guard_writes.py` (Write/Edit only under `runs/<run_id>/<agent's subdir>/`), `guard_bash.py` (allow `uv run python -m tools ...` + read-only commands), `guard_conviction.py` (red team: block any Read/Grep/Glob/Bash touching `*.conviction.json`).
- Permission rule syntax: `Bash(uv run python -m tools *)`; Write is governed by `Edit(...)` rules; gitignore-style paths.
- Background subagent permission prompts surface in the main session; pre-approve via settings.
- Concurrent subagent default limit 20 (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`). Batch deep dives <= 20.
- `.claude/agents/` and `.claude/skills/` did not exist at the build session start, so a restart (or `/reload-skills` for skills) is needed before the new agents load.
- Skill frontmatter: name, description, when_to_use, argument-hint, arguments, disable-model-invocation, user-invocable, allowed-tools, disallowed-tools, model, effort, context (fork), agent, hooks, paths. description + when_to_use truncated at 1,536 chars. Body < 500 lines. `$ARGUMENTS` supported.

## Data layer as built (`tools/`)

CLI: `uv run python -m tools <group> <command> ... [--json] [--refresh] [--out FILE]`. Output always JSON on stdout; exit 2 on source/entity errors.

| Command | Notes |
|---|---|
| `data resolve <symbol|ISIN|name>` | EQUITY_L + SME list, 9 Nifty constituent files, BSE code from BSE bhavcopy. Never auto-picks a fuzzy match. |
| `data prices <sym> [--years 3] [--from --to] [--rows N]` | NSE security-wise history in 90-day chunks (API caps ~70 rows/call). Adjusts bonus/split/consolidation (parsed factor, checked vs overnight gap ±15%), rights (TERP), demerger (approx from gap, flagged). TR series with dividends. Saves `data/cache/<ISIN>/derived/prices_adjusted.parquet`. Cross-checks last close vs bhavcopy. |
| `data bhavcopy --date D [--symbols A,B]` | Full-market cross-section (unadjusted). For marking many names. |
| `data index history "NIFTY 500" [--parts price,tri,pepb]` | NSE price + niftyindices TRI and P/E-P/B-DY (1-year chunks). Saves `data/cache/_market/derived/index_NIFTY_500.parquet`. |
| `data index constituents NAME` / `data index snapshot [--names]` | snapshot = all NSE indices incl. sectoral, with P/E, P/B, DY. |
| `data filings list <sym> [--kind ...] [--months 12]` | announcements (90-day chunks), transcripts/presentations/results/ratings by keyword, annual reports, rating feed. |
| `data filings get <sym> <url>` / `search <sym> <doc_id> <regex>` / `pages <sym> <doc_id> 10-14` | PDF -> page-numbered text in cache for page citations. |
| `data financials <sym> [--basis consolidated|standalone] [--quarters 12] [--years 8]` | XBRL from integrated filings (Q3FY25+) and legacy Ind AS filings. Corporate and bank taxonomies. Quarterly, annual, H1 and balance-sheet tables, INR crore. Cross-check: sum of quarters vs FY (>2% flag); restatement conflicts. |
| `data shareholding <sym> [--quarters 12]` | SHP XBRL: promoter, public, FII/FPI, DII, MF, insurance, non-institutions, govt, pledge. |
| `data macro` | RBI rates, INR/USD ref rate, G-sec yields (10y proxy) with as-on date; NSE FII/DII provisional (history accumulates in cache); CPI null (MOSPI unreachable). |
| `data events <sym>` | NSE event calendar, upcoming corporate actions, ASM/GSM status. |
| `smoke [--symbols] [--table]` | Live status table; saved to `data/cache/smoke_status.json`. |

### Compute group (`uv run python -m tools compute ...`)

| Command | Notes |
|---|---|
| `calc "<expr>" --var a=1 --unit x` | safe arithmetic (AST whitelist); agents never do mental math |
| `ratios <sym> [--basis standalone] [--input FIN.json] [--contingent-liabilities CR --contingent-source "AR FY26 p.212"]` | per-FY corporate or bank ratios, CAGRs 3/5/10y, TTM, quarterly margins, dilution on today's share basis |
| `valuation <sym> [--peers A,B]` | P/E, EV/EBITDA, P/B, FCF yield now; percentile vs own monthly 5/10y history (filing lags respected) and vs caller's peers |
| `reverse_dcf <sym> --ke 0.12 [--base fcf|eps] [--years 10 --fade 5 --terminal-growth 0.05]` or `--price P --base-value CF0` | implied growth + ke x N and ke x gt grids |
| `technicals <sym>` | DMA 50/200, 52w range, 3/6/12m TR vs Nifty 500 TRI, vol 60/252d, max drawdown, ADV 20/60d, delivery % |
| `base_rates [--index "NIFTY 50"] [--horizon 12] [--pe-method spliced|post_break|raw] [--where ret_12m:-100:0]` | forward TRI returns by P/E bucket, n_obs and n_independent, CIs |
| `portfolio --holdings SYM:w,... [--capital INR] [--value SYM:x,... --value-label "P/E"]` | correlation, sector/size/beta/momentum, HHI, days to exit at 10/15/20% ADV, -20% beta stress, mandate checks |
| `costs_tax --buy-value V --sell-value V --buy-date D --sell-date D [--exchange BSE] [--surcharge 0.15] [--exemption-remaining INR]` | round-trip cost lines, STCG/LTCG with and without exemption, net return |

### Ledger group (`uv run python -m tools ledger ...`, `--ledger-dir ledger/test` for dry runs)

| Command | Notes |
|---|---|
| `freeze <run_id> --approved "<who/when>" [--input FILE]` | appends run + pick records with cohorts A-E; refuses a second freeze of the same run |
| `mark <run_id> [--as-of D] [--no-fetch]` | gross TR of each pick and cohort vs Nifty 500 TRI since entry; comparisons A-B, C-A, B-D, D-E, A-E |
| `review <run_id> [--as-of D]` | announcements since the last review next to kill criteria; appends a review record |
| `postmortem <run_id> [--force] [--slab-rate 0.3] [--surcharge 0.1]` | net-of-cost-and-tax returns (portfolio with/without LTCG exemption), Brier + calibration table, scenario Brier, cohorts; writes the template |
| `correct <record_id> --set field=JSON --reason "..."` | appends a correction; readers apply it, the original line is never edited |

Provenance: `tools/common/provenance.py`: `num()`, `missing()`, `derived()`, `table()`; `find_bare_numbers()` must return [] for every command output (tests should assert this).
HTTP test seam: `tools.common.http.set_transport(fn)` swaps in a recorded-fixture transport.

## Known gaps (tell the user in hand-over)

- Financial history: Ind AS XBRL only (about FY18 onward). BS/CF only at H1 and FY. 10-year history needs annual-report reading.
- Bank KPIs NIM/CASA/credit cost not in XBRL; analysts extract from presentations with page cites. GNPA/NNPA %, CET1, ROA are in XBRL (unit "as filed").
- CPI and crude: no working keyless source; cite dated releases.
- Index P/E: methodology break on 2021-03-31 confirmed (standalone -> consolidated earnings); base_rates splices it by default.
- Annual XBRL history: RELIANCE FY19-FY21 and FY23-FY26 (no FY22 filing in NSE's list), CAMS/HDFCBANK consolidated from FY23/FY24. 5- and 10-year CAGRs mostly come back null with the reason; take older years from annual reports.
- HDFCBANK standalone XBRL stops at Q3FY25 (integrated filings list only consolidated for it); bank asset quality (GNPA/NNPA/PCR) is only in standalone filings.
- Price cache holds 2-3 years, so valuation percentiles vs own 5/10y history are labelled "shorter than 5y"; run `data prices SYM --years 10` before relying on them.
- Valuation peers need each peer's prices cached first (`data prices PEER`); a peer without cache is listed with the error, not fetched silently.
- Cost model: broker items (brokerage, DP charge) are DEFAULTs (Groww tariff, the more expensive of Zerodha/Groww); exchange charges use the top retail slab before Oct-2024; grandfathering (pre-2018 cost), STCG basic-exemption absorption, 87A and the user's slab rate are not modelled (dividend tax only with `--slab-rate`).
- `data resolve` industry = broad index-list industry; basic industry from announcements' `smIndustry`.
- HDFCBANK has no promoter group; shareholding shows promoter null, public 100.
- HTTP rate limits are per process, so parallel subagents multiply the request rate to NSE (SKILL batches analysts about 5 at a time). See Session E2 results.
- No tool computes P/B or dividend-yield percentiles for indices (P/E only, via `base_rates`).
- No OCR: scanned results PDFs (no text layer) cannot be read; `filings get` warns. Hit 2 of 3 companies in the F dry run (HDFCBANK, BAJAJ-AUTO Q2FY27).
- Own-history valuation percentiles rest on the XBRL earnings history (25-28 months for INFY, HDFCBANK, BAJAJ-AUTO), even with 10y prices.
- `Edit(runs/**)` allowlist not verified without prompts: Session F ran in bypass-permissions mode.
- Test fixtures are not in git (NSE's terms restrict redistribution). A fresh clone must run `uv run python tests/fixtures/record.py --fetch` (live NSE) before the 12 fixture tests run; until then they skip. If NSE stops serving one of the recorded windows or filings, `record.py` fails and names it, and that fixture cannot be re-recorded as is.

## Smoke result 2026-11-08 (RELIANCE, HDFCBANK, CAMS)

All 21 checks returned ok. Verified adjustments: RELIANCE bonus 1:1 ex 2024-10-28 (x2, gap check ok); CAMS split 10->2 ex 2025-12-05 (x5, gap check ok). Bug found and fixed: ISIN changes on a face-value split and feeds keep the old ISIN, so guards now use `same_issuer_equity()` (first 9 chars).

## Session D1 results (2026-11-08)

Session C's open issues, all resolved (commit 5c7e16c):
1. Bare numbers: `resolve` wraps `face_value_inr` (`tools/data/resolve.py: resolve_output`); `prices` wraps the corporate-action numbers (`prices.actions_output`). Smoke `_note` was updated for the new shape.
2. HDFCBANK quarter-sum flag: **a tagging inconsistency by the filer, not a parse error.** Interest earned reconciles exactly. In the Q2FY26, Q4FY26/FY26 and Q2FY27 filings HDFC Bank files `ProfitLossOfMinorityInterest` = 0 and tags `ProfitLossForThePeriod` with the after-minority figure. In Q1FY26 and Q3FY26 it files PAT before minority interest. Changes: bank mapping gained `minority_interest`; the crosscheck table has a `note` column that explains this automatically; a `pat_owners` check was added (FY26 pat_owners reconciles exactly). FY25 pat_owners does not fully reconcile either: cause not identified (legacy filings).
3. CAMS "only 4 quarters": could not reproduce. Both list caches date from the smoke run, and all 8 requested consolidated quarters now parse, with no warnings. The smoke-run XBRL downloads probably failed transiently (their warnings were hidden). Financials output now has a `coverage` block (requested/returned/missing quarters, and whether each missing quarter is in the other basis), and the smoke note shows missing quarters and the warning count. The two bases are deliberately never mixed in one table.
4. Empty-response cache: `cache.is_empty_payload()`. Empty bodies get `ttl_hours=6` in their meta (EMPTY_TTL_HOURS), which overrides an immutable TTL. `read_cached` also expires empty bodies that were cached earlier.
5. Smoke snapshot note now prints row count and date.

New bug found and fixed (commit f039667): **shareholding** was null for every filing before Jun-2025 (old taxonomy: context ids without `_Context`, e.g. `ShareholdingOfPromoterAndPromoterGroupI`, plus government split into central and state). The Jun-2025 filings showed 5007% because they store percent, not fractions. `parse_shp` now tries both context sets and picks the scale from promoter + public = 1 or 100 (`scale_evidence` column). A company with no promoter group now gets `pledge_evidence` "no promoter group". Old filings report promoter 0.0 and new ones report null (both as filed). RELIANCE/CAMS/HDFCBANK now give 12 full quarters.

Fixture tests (commit f039667): `tests/conftest.py` (autouse: refuse-all transport, CACHE_ROOT -> tmp in every module that binds it, rate limits off; `routes({...})` fixture), `tests/test_data_layer.py` (33 tests, green), `tests/fixtures/record.py` re-records trimmed fixtures from `data/cache`.

Also added: `tools/common/errors.py: InputError`, which the CLI reports as status `input_error`, exit 2. `META_INT_KEYS` now includes `requested_quarters`, `returned_quarters`, `n_picks` and `n_records`.

Index history cached: NIFTY 500 and NIFTY 50 TRI + P/E/P/B/DY from 1999-01-01 to 2026-11-06 (6930 rows), in `data/cache/_market/derived/index_*.parquet`.

**Index P/E methodology break: confirmed.** On 2021-03-31 the implied earnings (TRI change / P/E change) jump in one day by +20.0% for Nifty 500 and about +20% for Nifty 50, with no matching price move. That is the switch from standalone to consolidated earnings. Secondary source: https://cafemutual.com/news/press-news/21438-nifty-valuation-to-become-12-cheaper-from-march-31 (no NSE Indices circular found). Other one-day jumps above 10% occurred in 2000-2005 (probably constituent and earnings-season effects); `base_rates` lists them.

## Next sessions

### Session D2 results (2026-11-08)
Built and tested: rest of `tools/compute/` (ratios and technicals run and fixed on RELIANCE, HDFCBANK both bases, CAMS; new valuation, reverse_dcf, portfolio, costs_tax; `register()`), `config/costs.yaml`, `tools/ledger/` (freeze, mark, review, postmortem, correct). Tests: `tests/test_compute.py` (22, hand-checked synthetic inputs incl. calc and base_rates), `tests/test_ledger.py` (6, stub market), one new XBRL test, a CLI-help test. `uv run pytest`: 63 passed. Every compute/ledger output checked with `find_bare_numbers() == []` (tests and live runs).

Bugs found and fixed:
1. **XBRL undefined contexts** (`tools/data/xbrl.py`): RELIANCE legacy filings FY19-FY21 reference `OneD`/`FourD`/`OneI` without defining them, so whole years were silently dropped. `parse()` now recreates referenced-but-undefined contexts, dates durations from the filer's own `DateOfStart/EndOfReportingPeriod` facts and instants from the matching duration, drops any it cannot date, and `financials` warns per filing. RELIANCE annual history went from FY23-26 to FY19-21 + FY23-26.
2. **EPS/share counts across bonuses and splits** (`ratios`): filed EPS is not restated for later bonuses/splits (RELIANCE 1:1 FY25, HDFCBANK 1:1 Aug-2025, CAMS 10->2 Dec-2025), so EPS CAGR read -15% to -31%. Ratios now fetch NSE corporate actions (cached) and add `share_basis_factor`, `shares_restated_crore`, `eps_restated`; dilution uses restated shares (issuance/buyback only); EPS CAGR on filed EPS is refused (null + reason) when shares moved > 20%.
3. **Stale unadjusted price cache**: HDFCBANK's cached parquet lacked the Aug-2025 bonus (re-running `data prices` fixed it; probably an earlier empty corporate-action response). Compute now runs `unadjusted_gaps()` on every price series and adds a `warnings` entry for any overnight gap > 25% the adjustment factor does not explain.

Design notes (for Session E's `output-schemas.md`):
- Valuation history: month-end samples; a quarter is public from period end + 45 days (Q4: + 60); market cap = adj_close x filed shares x share_basis_factor(filing period end); P/E on TTM pat_owners; EV = mcap + net debt (minority interest not added); FCF yield on the latest public FY. Banks: P/E and P/B only.
- Reverse DCF: CF0 per share (FCF/share or TTM EPS from cache, or `--price/--base-value`); N years at g, F fade years with growth linear to gt, Gordon terminal; bisection on [-90%, 200%]; N = F = 0 solves implied terminal growth instead. Grids: ke x N and ke x gt.
- costs_tax: per-trade lines; tax gain excludes STT (s.48); LTCG if held more than 12 months; with/without exemption; surcharge capped at 15%; cess on tax + surcharge. Postmortem nets short/long-term results across picks and applies ONE annual exemption at portfolio level.
- Ledger files: `<ledger-dir>/picks.jsonl` (append-only; records `run`, `pick`, `review`, `postmortem`, `correction`; numbers are provenance numbers), `<ledger-dir>/postmortems/<run_id>.md` (written once; interim ones are `<run_id>.interim-<date>.md`). Record ids: `<run_id>:run`, `<run_id>:<ISIN>`, `<run_id>:review:<date>`, `<run_id>:postmortem[-interim-<date>]`, `<id>:correctionN`.
- Freeze input `runs/<run_id>/freeze_input.json`: `{model_id, horizon_months?, picks: [{symbol, weight, thesis, scenarios: [{name, probability, return_pct, return_range_pct: [lo|null, hi|null]}], p_beat_benchmark, kill_criteria: [..], review_dates: [YYYY-MM-DD]}], cohorts?: {B: [SYM], C: [SYM], D: [SYM]}}`. Validation: weights > 0 summing <= 1; scenario probabilities sum to 1 +- 0.01; p in [0, 1]; thesis and kill criteria required; zero picks allowed. Cohorts not listed are read from the run folder: B = `dossiers/*.json` (`identity.nse_symbol`/`symbol`), C = `redteam/*.json` with `"verdict": "killed"` (E1; `"kill"` also accepted), D = `candidates.json` (list, or `{candidates: [...]}`, of symbols or `{symbol}`). **Session E must make the agents write these files in that shape.** Scenario `return_range_pct` is needed for the multi-class scenario Brier score.
- Entry = close of the first session after the freeze date; returns are TR (dividends reinvested); cohort A cash earns 0; B/C/D equal-weight buy-and-hold; members without prices are excluded from the mean and named (survivorship risk). `freeze` requires `--approved "<who/when>"`. Capital: mandate `capital_inr`, else notional INR 10 lakh (labelled).

Cost and tax sources (verified 2026-11-08; full notes in `docs/costs_research_2026-11-08.md`): STT 0.1% each side (NSE/FATAX/73524), NSE txn INR 307/crore incl. IPFT (NSE/FA/73061), BSE INR 375/crore (BSE equity master circular Apr-2026), SEBI INR 10/crore (NSE investor page), stamp 0.015% buy (NSE), GST 18% on brokerage + exchange + SEBI fee (SEBI circular 18-Jul-2022), CDSL INR 3.50 / NSDL INR 4.00 per debit, STCG 20% s.111A / s.196 (2025 Act), LTCG 12.5% above INR 1.25 lakh s.112A / s.198, holding > 12 months s.2(42A) / s.2(101)(b), cess 4%, surcharge cap 15% (Budget memo), 87A/s.156 not against 111A/112A, dividend TDS 10% above INR 10,000 s.194 / s.393. Budget 2026 changed STT on F&O only.

### Session E (split by the user into E1 and E2, run in series)
Original plan, kept for reference; E1 did the references, hooks and settings.json (see below). Write the 5 references, 4 agent definitions (opus, effort high, Agent tool blocked, hooks), SKILL.md (§3 nearly verbatim; modes; phases; <500 lines), hooks scripts, `.claude/settings.json`, CLAUDE.md (short), README.md. Re-read each agent as if it had no other context. Update this file. Commit. Then the user restarts Claude Code.
Carry over from Phase D:
- `output-schemas.md` must define `freeze_input.json`, `dossiers/*.json` (with `identity`), `redteam/*.json` (with `verdict`: kill/pass/...), `candidates.json` exactly as in "Session D2 results", plus the ledger record types. Agents write those files; the ledger reads them.
- Teach agents the command order: `data prices SYM --years 10` (and for each peer) before `compute valuation`; `data financials` before `ratios`; `compute calc` for any arithmetic; quote `warnings` from compute outputs (unadjusted price gaps) instead of ignoring them.
- `ledger freeze` needs `--approved`; the SKILL must run it only after the user's explicit approval in chat and pass the approval text. Dry runs use `--ledger-dir ledger/test` (gitignored).
- Bank analysts: run `ratios --basis standalone` for asset quality; NIM/CASA/credit cost come from presentations with page cites.
- Tell the user the cost DEFAULTs (brokerage, DP charge) in `config/costs.yaml` need confirming once a broker is chosen, and re-verify rates after each Budget.

### Session E1 results (2026-11-08)
Built: `.claude/skills/equity-research/references/` (5 files), `.claude/hooks/` (3 guards + `_guard_common.py`), `.claude/settings.json`, `tests/test_hooks.py` (100 cases). Also fixed: `data --help` crashed (stray `%` in the `prices` help; `tests/test_compute.py::test_every_cli_help_renders` now walks every subcommand, including nested `data index ...` and `data filings ...`); ledger cohort discovery now treats red-team verdict `killed` (spec wording; `kill` still accepted) as cohort C and skips `*.conviction.json` when reading `dossiers/*.json` for cohort B (`tests/test_ledger.py::test_discover_cohorts_reads_run_files`).

### Session E2 brief (done; kept for reference)
Write the 4 agent definitions (`.claude/agents/{market-strategist,hunter,company-analyst,red-team}.md`), `.claude/skills/equity-research/SKILL.md`, `CLAUDE.md` and `README.md` on top of what E1 built. Re-read each agent as if it had no other context. Update this file, `uv run pytest`, commit. Then the user restarts Claude Code (new agents, skill and hooks load only after a restart; project hooks also need workspace trust).

**Reference files** (`.claude/skills/equity-research/references/`, written for subagents with no other context; point each agent at the ones it needs, by path):
- `failure-modes.md`: the 10 CNMV failure modes, each with countermeasures tied to real commands (resolve/ISIN echo, provenance, fiscal notation, XBRL over PDFs, units, `compute calc`, carryover, re-fetch on correction, reading log, citations), plus India/tool traps (unadjusted-gap `warnings`, 10y prices before valuation, short XBRL history, peers' cache, sources down, dated news). All agents.
- `red-flags-india.md`: 17 required flags plus 8 extra checks; for each, why, the exact command/document search, and pass/flag/unknown guidance (judgment, not a score); row format for dossier section 6. Analyst, red team.
- `valuation-guide.md`: command order; what `compute valuation` returns; sector methods (banks P/B vs ROE with implied-ROE formula, insurers P/EV/VNB from presentations, cyclicals mid-cycle, holdcos SOTP, platforms unit economics, others); reverse DCF step by step (base choice, ke from `data macro` + stated ERP, grids, `what_has_to_go_right`, `--years 0 --fade 0` returns `implied_terminal_growth`); scenario returns and tiled ranges. Analyst, red team, hunter.
- `output-schemas.md`: the run-folder table (path, writer, reader), citation and number conventions, `ProvNum`/`Identity` defs, templates and JSON schemas for market_view, hunters/<lens>, candidates.json + shortlist.md, dossier .md (15 sections + reading log + corrections log) / .json / .conviction.json, redteam .md/.json, round-2 archiving, portfolio_holdings.json + portfolio.md, final_report.md, freeze_input.json (matches the ledger validator), reviews/<date>.md, ledger record types. Everyone.
- `evaluation.md`: §3 objective verbatim, why only forward evaluation is valid, the ledger commands, entry/returns/costs rules, cohorts A-E and how to read them, Brier (p_beat and multi-class scenario), calibration table, how to set probabilities, review and post-mortem practice. Analyst (conviction), main session.

**Hook command lines for each agent's frontmatter** (exactly these; matchers as shown; every agent also needs `disallowedTools: Agent`):

```yaml
# market-strategist
hooks:
  PreToolUse:
    - matcher: "Write|Edit|MultiEdit|NotebookEdit"
      hooks:
        - type: command
          command: 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_writes.py" market_view.md market/'
    - matcher: "Bash"
      hooks:
        - type: command
          command: 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_bash.py" market_view.md market/'
```
- hunter: same two hooks with argument `hunters/` (instead of `market_view.md market/`).
- company-analyst: same two hooks with argument `dossiers/`.
- red-team: same two hooks with argument `redteam/`, plus a third:
```yaml
    - matcher: "Read|Grep|Glob|Bash"
      hooks:
        - type: command
          command: 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_conviction.py"'
```

What the hooks enforce (tell each agent, so it does not waste turns on blocked calls):
- `guard_writes.py <spec>...`: Write/Edit/MultiEdit/NotebookEdit only under `runs/<run_id>/<spec>`; a spec ending in `/` is a folder subtree, otherwise one exact file. `run_id` must match `YYYY-MM-DD-<slug>` and **the run folder must already exist**, so the main session creates `runs/<run_id>/` in Phase 0 before spawning anyone (the Write tool creates subfolders itself). Symlinks and `..` are resolved before the check.
- `guard_bash.py <spec>...`: allows `uv run python -m tools data|compute ...` (exact prefix; `ledger` and `smoke` are refused for subagents; a `--out` path, including argparse prefixes `--o`/`--ou`, must be inside the agent's area) and read-only commands: ls cat head tail wc grep egrep fgrep rg find sort uniq cut tr column nl stat du pwd basename dirname realpath readlink diff cmp comm jq echo printf true date file cd, joined by `| && || ;`. Refused: other commands (sed, awk, xargs, python, curl, cp, mv, rm, tee...), redirection except `2>&1` / `>/dev/null`, `$(...)`, backticks, `$VAR`, `$'...'`, subshells, `&`, here-docs, `NAME=value cmd`, `.env`, and file-writing options (find -exec/-delete, sort -o, uniq OUT, rg --pre, date -s, file -C).
- `guard_conviction.py`: blocks Read of any `*.conviction.json` (also via symlink); Grep/Glob whose path and glob could include one (`glob: "*.md"` or a non-json `type` is fine); Bash that names one after quote removal and brace/glob expansion, or that reads a folder holding one (`grep -r`, `rg`, `cat dir/*`, `jq dir`, `find -exec`). Listing (`ls`, `find` without exec, `du`, `stat`) is allowed.
- All three read hook JSON from stdin, exit 2 with a reason on stderr to block, and fail closed (any internal error blocks). Standard library only, Python 3.8+ (`python3` is the pyenv shim: 3.12 in the repo, 3.9 elsewhere; both tested). If `$CLAUDE_PROJECT_DIR` were unset, python could not open the script and exits 2, which blocks every call: also fail-closed, but confusing. **E2: confirm in the hooks docs that `CLAUDE_PROJECT_DIR` is set for frontmatter hooks; Session F should check that one out-of-area write is really blocked.**

**Decisions made in E1** (E2 should follow them; tell the user in hand-over):
1. Red-team verdict values are the spec's `survives | weakened | killed`; only `killed` puts a name in cohort C. A red-team JSON also has `send_back` (material numerical discrepancies) and `round` (1 or 2).
2. Probabilities, expected value, `p_beat_benchmark` and confidence live **only** in `dossiers/<SYM>.conviction.json`. The dossier .md/.json carry scenario drivers, returns and ranges but no probabilities (spec §6.3 section 11 lists probabilities in the dossier; that would leak them to the red team).
3. Scenario `return_pct` is the gross total return over the horizon (what the ledger scores); `return_range_pct` must tile the number line, bear `[null, x)`, base `[x, y)`, bull `[y, null]`, or the scenario Brier score is skipped.
4. In run JSON files, facts are provenance objects copied from tool output; judgments (returns, probabilities, weights) are plain numbers.
5. Run-folder additions beyond the spec: `mandate.yaml` (confirmed mandate), `market/` (strategist working files), `hunters/<lens_slug>.md/.json`, `dossiers/work/<SYM>/`, `redteam/work/<SYM>/`, `dossiers/round1/` + `redteam/round1/` (main session copies round-1 files there before a re-analysis; top-level files are always the latest), `portfolio_holdings.json`, `reviews/<date>.md`. `market_view.md` stays at the run root (spec path) via the exact-file spec.
6. Dossier JSON `kill_criteria` are objects `{criterion, observe, by}`; the main session turns each into the string `'<criterion> (observe: <source>; by <YYYY-MM-DD>)'` for `freeze_input.json`.
7. The main session has no hooks; it is bounded by the settings allowlist and by SKILL.md.

**Things E2 must handle in the agent/skill text:**
- Agent `tools:` Read, Grep, Glob, Bash, WebSearch, WebFetch, Write, Edit; `model: opus`, `effort: high`; `disallowedTools: Agent`.
- `.claude/settings.json` allows only `Bash(uv run python -m tools *)`, `WebSearch`, `WebFetch`, `Edit(runs/**)`. Read-only Bash (ls, cat, grep) is not pre-approved, so subagent use of it raises permission prompts in the main session: tell agents to prefer the Read/Grep/Glob tools for files. (Superseded in E2: common read-only Bash is auto-approved by Claude Code; see Session E2 results.) Check in Session F that `Edit(runs/**)` (relative path) matches writes when Claude Code runs from the repo root.
- Hunters have no universe-wide fundamentals screener. Search aids: `data index constituents NAME`, `data index snapshot` (sector P/E etc.), `data bhavcopy --date D [--symbols]` (cross-section of closes/turnover/delivery), web search, then per-name `compute valuation/technicals/ratios`. They choose the parameters; screens never gate.
- The analyst passes `--out runs/<run_id>/dossiers/work/<SYM>/...` when saving tool output (e.g. for `compute ratios --input`), never a path elsewhere.
- Spawn prompts pass only: company (symbol), run_id, mandate path, market-view path (and, for round 2, the discrepancy list). Never the hoped-for answer.

**Follow-ups to offer the user (not done, need approval):** a `permissions.deny` rule for `Read(.env)` (guard_bash already blocks `.env` in Bash; the Read tool is unguarded); whether subagents may run `ledger mark` (read-only) during reviews (currently blocked with the whole `ledger` group).

### Session E2 results (2026-11-08)
Built: `.claude/agents/{market-strategist,hunter,company-analyst,red-team}.md`, `.claude/skills/equity-research/SKILL.md` (237 lines), `CLAUDE.md`, `README.md`, `tests/test_agents.py` (6 tests: agent frontmatter and exact hook command lines, referenced files exist, skill trigger phrases and size, and every `data|compute|ledger` command and `--option` named in the agents, skill, README and CLAUDE.md exists in the argparse tree). `uv run pytest`: 170 passed.

Verified in the current Claude Code docs (hooks, sub-agents, permissions, tools-reference; 2026-11-08):
- Hook commands run via `sh -c`, and `CLAUDE_PROJECT_DIR` is exported to the hook process. Frontmatter hooks use "the same format"; the docs do not say separately whether they get the variable. Hooks run in Claude Code's current directory (not stated to be the project root). **Decision:** hook lines use `"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/..."`, identical when the variable is set and falling back to the session cwd (the repo root) when not. Tested with `sh -c` both ways: an out-of-area write is blocked with the guard's own reason.
- **Grep and Glob tools are absent by default on Linux/macOS**; Claude uses Bash `grep`/`find` (embedded ugrep/bfs). They come back only via `--tools`/`--allowedTools`, or for a subagent whose `tools:` lists them and omits Bash. The agents keep them in `tools:` (per spec) and are told to use them if present, else `grep`/`find`.
- **Claude Code auto-approves a built-in read-only Bash set** in every mode: ls, cat, echo, pwd, head, tail, grep, find, wc, which, diff, stat, du, cd, read-only git. A compound command runs without a prompt only if every part is allowed. `jq`, `sort` and `rg` are not named, so they may prompt. E1's note that read-only Bash is not pre-approved was wrong for the common commands. Agents are told to avoid `jq`, `sort` and `rg`.
- Context saving: agents run big commands as `uv run python -m tools <cmd> --out runs/<run_id>/<area>/work/... | grep '"status"'` (passes guard_bash, no prompt) and then read parts of the saved file.

Decisions made in E2 (tell the user in hand-over):
1. Subagents reply to the main session in a few lines (paths, status, gaps, verdict); analysts never put probabilities in the reply.
2. Analysts must not open other dossiers, conviction files, `hunters/`, `candidates.json` or `shortlist.md`; spawn prompts never mention the lens or why a name was shortlisted. Round-2 analysts may read `dossiers/round1/<SYM>.md`, never its conviction file.
3. Hunters use 3-year prices (`data prices SYM`) for a first look and label percentiles "shorter than 5y"; analysts fetch 10 years.
4. Deep-dive mode: `run_id = YYYY-MM-DD-<sym>-deepdive`, the analyst gets `market view: none for this deep dive`; no freeze unless the user asks.
5. "dry run" in a request means `run_id` `<date>-dryrun[-slug]` and `--ledger-dir ledger/test` on every ledger command.
6. Phase 3 runs analysts in batches of about 5 (rate-limit gap below), never more than 20 concurrent subagents.
7. Hard exclusions applied mechanically: universe, `exclusions`, liquidity floor. `avoid_themes` is judged per name with a stated reason.
8. Red-team "material" discrepancy: would change a conclusion, a scenario return, a valuation reading or a red-flag mark; any entity, period, unit or basis mismatch on a decision-relevant number.
9. Phase 0 finds open runs by grepping `ledger/picks.jsonl` for `"record_type": "run"` without a `postmortem` record (no ledger "list runs" command exists).

New known gaps (also in README):
- **HTTP rate limits are per process** (`tools/common/http.py`: `_wait` keeps `_last` in memory), so N parallel subagents send N request streams to NSE. Mitigation: batches of about 5. A cross-process limiter (file lock or timestamp file in `data/cache/`) would fix it.
- Agents have no prompt-free JSON validator (`jq` is not auto-approved; `python` is refused by guard_bash). They Read their JSON back; `ledger freeze` validation catches freeze-input errors.
- No tool computes P/B or dividend-yield percentiles for indices (only P/E, via `base_rates`).

Open follow-ups (need the user's approval): a `permissions.deny` rule for `Read(.env)`; subagent access to the read-only `ledger mark`; `Bash(jq *)` in the allowlist; the cross-process rate limiter.

### Session F brief (start here, after restarting Claude Code)
Goal (spec §10 Phase F): a dry run end to end. One lens, three companies, red team on all, portfolio step, freeze only to `ledger/test/`. Then report what worked, failure modes caught, shallowness, time and usage, and fixes.

0. Preconditions: the user restarted Claude Code in the repo root and accepted workspace trust (project hooks need it). Confirm the four agents and the `equity-research` skill are available. `uv run pytest` green; `uv run python -m tools smoke --table` (note sources that are down).
1. Cheap hook checks before spending usage. Create `runs/<today>-hooktest/` (Write a placeholder `mandate.yaml`), then spawn short test-only subagents ("Hook test only, do not research: try each of these and report each result verbatim, then stop"). Remove the folder afterwards, with the user's OK.
   - hunter: Write `runs/<id>/hunters/t.md` should succeed **without a permission prompt** (checks that `Edit(runs/**)` matches); Write `runs/<id>/dossiers/t.md` should be blocked with guard_writes' reason (a "can't open file" error instead would mean the `CLAUDE_PROJECT_DIR` fallback failed); `uv run python -m tools data resolve CAMS` runs without a prompt; `uv run python -m tools ledger mark x` is blocked; `cat config/mandate.yaml` runs without a prompt.
   - red-team: after the main session writes a dummy `runs/<id>/dossiers/T.conviction.json` and `T.md`, Read of the conviction file is blocked by guard_conviction and Read of `T.md` succeeds.
   If anything misbehaves, fix the hook lines or settings before step 2 and record the change here.
2. Dry run: invoke the skill ("dry run: run research with one lens, quality, and a shortlist of three names"). Follow SKILL.md; the user answers the Phase 0 mandate prompt and both checkpoints. `run_id` `<today>-dryrun`; every ledger command with `--ledger-dir ledger/test`.
3. Watch and record under "Session F results" here:
   - per subagent: duration, tokens and tool calls (task notifications), context pressure or compaction, every permission prompt and what triggered it;
   - schema conformance of `candidates.json`, dossier `.json`/`.conviction.json`, red-team `.json`, `freeze_input.json`; `ledger freeze` validation and cohort discovery (B from dossiers, C from `killed`, D from candidates);
   - failure modes the red team caught; numbers without citations; mental math; depth differences between the three dossiers; honesty of reading logs;
   - NSE rate limiting with three parallel analysts (`source_error`, HTTP 429).
4. Fix what the dry run exposes (agents, SKILL.md, references, tools), rerun `uv run pytest`, commit locally. Write a "Session G brief" for the hand-over: known gaps, cost DEFAULTs in `config/costs.yaml`, mandate DEFAULTs, the open follow-ups, E1 decisions 1-7 and E2 decisions 1-9.

### Session F results (2026-11-08)
Run in a side session started from the build session, 05:00-11:40 IST. That session ran in **bypass-permissions mode**, so "no permission prompt" observations do not test the `Edit(runs/**)` allowlist.

**Preconditions.** Four agents and the skill loaded. `uv run pytest` 170 passed. Smoke 21/21 ok; one bare number (`data events`: `corporate_actions_next_12m[].cash_per_share`), fixed.

**Hook checks** (short sonnet test subagents in `runs/2026-11-08-hooktest/`, deleted afterwards with the user's OK): all 19 actions behaved as designed.
- hunter: Write to `hunters/` allowed; to `dossiers/` and `docs/` blocked with guard_writes' reason (so the `CLAUDE_PROJECT_DIR` fallback works); `data resolve` allowed; `ledger mark` blocked; `cat` allowed; `>` redirection blocked; `python3` blocked; `--out` outside the area blocked, inside allowed.
- red-team: Read and `cat` of `T.conviction.json` blocked; `cat dossiers/T.*` blocked; `grep -r` over a folder holding conviction files blocked; Read of `T.md` and `ls` allowed; Write to `redteam/` allowed, to `dossiers/` blocked. Glob tool absent, Grep not listed (as E2 found).

**Dry run `2026-11-08-dryrun`.** User: mandate defaults, `capital_inr` 100000; one lens (quality) plus a lens note from the market view (prefer names whose margins and balance sheets hold with Brent near $100, a weak rupee and 25-50bp more hikes); shortlist INFY, HDFCBANK, BAJAJ-AUTO; at checkpoint 2 the user chose to freeze the illustrative override (HDFCBANK 0.10, INFY 0.05, BAJAJ-AUTO 0.05) into `ledger/test` as a pipeline test. The run's recommendation was **no picks, buy the Nifty 500**: every analyst expected return was 3.7-12.6pp below the base-rate mean (15.68%), every `p_beat_benchmark` below 0.5 (0.35-0.47), and every red-team verdict `weakened`.

| Agent | Minutes | Tokens | Tool calls | Notes |
|---|---|---|---|---|
| market-strategist | 13.1 | 134k | 65 | MOSPI CPI API SSL error (used PDF); Business Standard 403; NSE ownership PDF timeout |
| hunter (quality) | 52.8 | 194k | 95 | 7 candidates, 9 rejected; slowest agent |
| analyst INFY | 23.0 | 312k | 95 | complete; 2 self-corrections |
| analyst HDFCBANK | 31.2 | 363k | 130 | complete; 4 self-corrections; hit the truncated-price bug before the fix |
| analyst BAJAJ-AUTO | 27.0 | 358k | 131 | complete; 2 self-corrections |
| red team INFY | 12.1 | 191k | 63 | weakened, 15 numbers re-fetched, 0 material |
| red team BAJAJ-AUTO | 13.6 | 176k | 58 | weakened, 17 re-fetched, 0 material |
| red team HDFCBANK | 12.7 | 170k | 63 | weakened, 14 re-fetched, 0 material |

Totals [C: compute calc]: about 1.90M subagent tokens, 700 tool calls, 185 subagent-minutes, about 111 minutes on the critical path (three analysts in parallel, red teams started as each dossier finished). No context compaction in any subagent. Main session context ended at about 276k tokens (above the 200k guideline); the account's 5-hour window was at 85% by the end. A full run (1 strategist, 6 hunters, 20 names plus about 4 round-2 pairs) at Session F's per-agent averages (analyst 344k, red team 179k tokens) would be about 13.9M subagent tokens [C: compute calc] and about 3.4 hours of critical path with batches of five [C: compute calc]: several 5-hour usage windows on this plan.

**What worked.**
- Every JSON file conforms to `output-schemas.md` (checked with a script: required keys, 8-12 key numbers with provenance, scenario order and ranges, probabilities summing to 1, `.json` and `.conviction.json` scenarios equal, expected return = sum p x r).
- `ledger freeze` validated the input; cohort discovery found A (3, cash 0.80), B (3 from `dossiers/*.json`, conviction files skipped), C (empty, noted), D (7 from `candidates.json`), E; no bare numbers. `ledger mark --no-fetch` before entry returns nulls with reasons.
- Three parallel analysts: no HTTP 429 and no `source_error` from NSE.
- Arithmetic went through `compute calc` in every file checked; red-team citations spot-checked against the documents (INFY Q1FY27 call p.33 matched verbatim).
- Depth was even across the three dossiers (48-51 KB, 12 key numbers, 17-18 red-flag rows, 6 kill criteria each); reading logs were honest about "partly read" (targeted search instead of full reads, media-call transcripts only for INFY).

**Failure modes caught.**
- By the analysts themselves: BAJAJ-AUTO's tool P/E (22.9x) includes INR 1,598.81 cr of non-cash gains from taking control of KTM (AR FY26 p.371); normalised 26.1x.
- By the red teams (all omissions or framing, no wrong numbers): INFY's FY27 1-2% CC guide includes about 1.7pp of acquisitions (Q1FY27 call p.33), so organic growth is about zero, and INR growth (10.7%) hides USD growth (1.3%); HDFCBANK's dossier missed a US SDNY securities class action (Aug-2026) and the RBI's open questions on the MSRDC penalties, and its variant view was consensus; BAJAJ-AUTO's scenarios start from an EPS 16.1% below the H1FY27 run-rate and normalise one-off gains but not same-quarter KTM losses, and a lender asset-quality figure (BACL GNPA, AR FY26 p.58) was logged as a gap though it was available.
- Not exercised: a send-back and round 2 (no material discrepancies), a red-team kill (cohort C empty).

**Where subagents went shallow or broke rules.** No rule breaks found in the files: no probabilities in dossier `.json`, no conviction file read by a red team (hooks would have blocked it), no `ledger` call by a subagent. Shallow spots: HDFCBANK's litigation news (no news sweep), BACL asset quality, annual reports and transcripts read by targeted search. Every subagent tried a blocked Bash form at least once (`sed`, `awk`, `paste`, `$VAR`/`$(...)`, here-documents; red teams also `python3` and `NAME=value` prefixes) and recovered. The BAJAJ-AUTO analyst's reply stated its conclusion ("doesn't support owning it over the Nifty 500"): not a probability, and not passed on.

**Fixes made in Session F** (174 tests green):
1. `compute portfolio --mandate PATH`: mandate checks, capital and source labels now come from the run's confirmed mandate (they read `config/mandate.yaml` before). `ledger freeze` prefers `runs/<run_id>/mandate.yaml` for horizon and `capital_inr`. SKILL Phase 5 and `output-schemas.md` pass `--mandate`. Tests added.
2. `data prices`: a chunk that hits NSE's 70-row cap is split in halves and refetched (HDFCBANK traded EQ and IL series in 2016-17, two rows a day, so 90-day chunks were truncated; `--years 10` failed, and one chunk silently lost 8 days inside the 10-day holiday tolerance). Test parametrised on dense and sparse second series. Live: HDFCBANK `--years 10` ok, 2,479 rows from 2016-11-08.
3. `data events`: corporate-action numbers wrapped in provenance (smoke bare-number violation).
4. `data filings list`: warns when `--limit` (default 60) cuts the announcements list (BAJAJ-AUTO's analyst saw only the latest 60 of 145). Test added.
5. Agent definitions: company-analyst mandatory list gains a dated litigation and regulator news sweep (queries logged) and the rerun-with-`--limit` note; kill criteria are always written for a holder, even when the analyst concludes "do not own" (analyst and red team); all four agents get an explicit list of Bash forms that are always blocked and "use Read with offset/limit" instead of `sed`. **These definition changes load only after a restart.**

Not repeated: a second dry run would cost about 2M tokens and the definition fixes need a restart to load. Recommended in Phase G instead (below).

### Session G brief (start here, after restarting Claude Code)
Goal (spec §10 Phase G): hand-over. Summarise what was built, which data sources work, known gaps and limitations, how to trigger each mode, and the expected scale of a full run; remind the user to restart Claude Code so changed agents load; commit everything.

1. Restart Claude Code in the repo root (agent definitions changed in Session F). `uv run pytest` (174) and `uv run python -m tools smoke --table`.
2. Optional, ask the user first (about 0.5-1M tokens): a short second dry run to exercise what F did not: the new analyst news sweep and holder-shaped kill criteria, a round-2 send-back (main session `mkdir -p` + `cp` into `round1/`), and permission prompts in normal (non-bypass) mode for `Edit(runs/**)`. A single-company deep dive (`dry run: deep dive on <SYMBOL>`) covers most of it cheaply.
3. Hand-over content, from this file:
   - built: Phases C-F; tools table above; four agents, skill, hooks, settings.
   - data sources: smoke table (all 21 ok on 2026-11-08); down or limited: MOSPI CPI API (SSL), Business Standard (403), some company fact sheets (403), scanned PDFs (no OCR).
   - known gaps: the "Known gaps" list above (now incl. OCR, short own-history percentiles, unverified `Edit(runs/**)` prompts).
   - user to confirm: mandate DEFAULTs in `config/mandate.yaml`; cost DEFAULTs (brokerage, DP charge) in `config/costs.yaml` once a broker is chosen; re-verify statutory rates after each Budget.
   - decisions to tell the user: "Decisions made in E1" and "Decisions made in E2" (Session E1/E2 sections above), and Session F's fixes.
   - open follow-ups needing approval: `permissions.deny` for `Read(.env)`; subagent access to read-only `ledger mark`; `Bash(jq *)` in the allowlist; a cross-process rate limiter (not needed at 3 parallel analysts, untested at 5+); OCR for scanned PDFs (would need a system package such as tesseract).
   - scale of a full run: Session F's per-agent table; 20 names is about 13.9M subagent tokens and about 3.4 hours of critical path with batches of five (Session F results).
   - modes: README "Running research".
4. Remind the user to restart Claude Code; update this file (Phase G done); commit locally. Never push.

### Session G results (2026-11-08)
Run in a side session started from the build session at 11:42 IST, in **bypass-permissions mode** (so `Edit(runs/**)` prompts are still unverified).

- Agent definitions live: `company-analyst.md` has the dated litigation/regulator news sweep, and all four agents carry the blocked-Bash rules. They were last edited at 11:37 IST and the session process started at 11:42 IST, so its subagents load the Session F versions. A session started before 11:37 still has the old ones: restart Claude Code before the first real run.
- `uv run pytest`: 174 passed. `smoke --table`: 21/21 ok and no bare-number violations; most checks were served from that day's cache, while index and macro ran live. CPI was `unavailable` as expected.
- Second dry run: not run. It is optional and needs the user's go-ahead, at about 0.5-1M tokens for `dry run: deep dive on <SYMBOL>`. It must run from a session in normal permission mode to test the `Edit(runs/**)` prompts. A round-2 send-back happens only if the red team finds a material discrepancy.
- Wrote `docs/HANDOVER.md` covering what was built, data sources, known gaps, the DEFAULTs to confirm, E1/E2 decisions and F fixes, open follow-ups, modes and the scale of a full run. README links to it from the intro, "Scale of a full run" and "Where things live".
- After hand-over, with the user's approval: added `permissions.deny` `Read(./.env)` and `Read(./**/.env)` to `.claude/settings.json`. In this bypass-mode session the Read tool refused a dummy `.env` at the repo root and in a subfolder; `.env.example` stayed readable. The dummy files were deleted. Removed the item from the open follow-ups in HANDOVER and README.

### Fixtures recorded locally, out of git (2026-11-08)
Side session started from the build session after the repository went public. NSE's terms restrict redistributing its data, and `tests/fixtures/` shipped trimmed NSE responses and filings.

- `tests/fixtures/record.py --fetch` makes the live calls that fill `data/cache` for every fixture through the tools' own functions (`get_entity`, `prices.raw_history` on the exact 90-day chunk, `corporate_actions` on 2023-11-04..2026-11-08, `financials.list_filings`, the SHP master list via `nse_api`, filings via `cache.fetch` with the tools' cache keys), then trims as before (rows filtered, never edited). Filing links come from NSE's own lists. It fails, naming the fixture and the reason, when a source file is missing, a window has no rows, a price chunk comes back truncated, a filing is no longer linked or a symbol resolves to another ISIN; on failure it writes nothing. The integrated results list is now filtered across all its cached pages, because a filing moves to later pages as new ones arrive.
- `tests/conftest.py`: `require_fixtures()` (called by the `routes` fixture) and a `pytest_runtest_call` wrapper that turns a missing `FIXTURES / name` read into a skip. The message is "real fixtures not recorded: run `uv run python tests/fixtures/record.py --fetch`" plus the missing files. `tests/test_data_layer.py` is unchanged.
- `.gitignore` ignores `tests/fixtures/*` except `*.py`, `README*` and `.gitkeep`, and the 14 data files were removed from the index (`git rm --cached`) but kept on disk. The old exception for PDF fixtures was dropped.
- Verified: with the fixtures present, 174 passed and none skipped. In a scratch copy without them, 162 passed and 12 skipped, with no errors. `record.py --fetch` from an empty `data/cache` in the worktree made 32 live requests, and all 14 regenerated fixtures were **byte-identical** to the committed ones. Rebuilding from the main checkout's existing cache was also byte-identical. 174 passed on the regenerated fixtures. With no cache, `record.py` exits 1 with "cannot record nse_price_RELIANCE_2024-10.json: data/cache/... not found (run with --fetch)".
- History purged with the user's approval (2026-11-08). `master` was fast-forwarded to this commit. `git filter-branch --index-filter` then removed `tests/fixtures/*.json` and `*.xml` from every local branch, and `master` was force-pushed to `origin main` with `--force-with-lease`.
  - Authors, dates and messages are unchanged; each rewritten commit differs only by the 14 files.
  - A `git bundle` of all refs from before the rewrite was saved in that session's `/tmp` scratchpad.
  - The `gold-silver-analysis` worktree's branch was moved to the rewritten base, keeping its uncommitted edits and its fixture files on disk.
  - The shared `.git/info/exclude` also ignores the fixture files, for worktrees whose `.gitignore` predates this change.
  - GitHub keeps the old commits reachable by SHA until GitHub Support purges them.
