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
| E | References, 4 agents, SKILL.md, CLAUDE.md, README, settings.json, hooks | **next**: start from "Session E" below |
| F | Dry run (needs Claude Code restart first) | not started |
| G | Hand-over | not started |

## Decisions in force (user-approved)

- Mandate: all §9 defaults, each marked `# DEFAULT - confirm` in `config/mandate.yaml`.
- Broker: none. Screener.in: not used. Python 3.12 via uv (`uv run python -m tools ...`). Local git only, no remote, no push.
- Smoke small cap: **CAMS** (Nifty Smallcap 250; split 10 -> 2 FV, ex 05-Dec-2025). Bonus test case: RELIANCE 1:1, ex 28-Oct-2024.
- HTTP policy: honest UA `equity-research-tool/0.1 (personal non-commercial research)`, per-host rate limits, robots.txt respected, 401/403 = blocked (never retry with altered headers). If a source refuses the honest UA, report to user; user decides per source.
- Subagents: `model: opus`, `effort: high`; block the `Agent` tool in all four (subagents can nest by default).
- `.claude/settings.json` allowlist approved by user: `Bash(uv run python -m tools *)`, `WebSearch`, `WebFetch`, `Edit(runs/**)` (+ frontmatter hooks below).
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

## Smoke result 2026-11-08 (RELIANCE, HDFCBANK, CAMS)

All 21 checks returned ok. Verified adjustments: RELIANCE bonus 1:1 ex 2024-10-28 (x2, gap check ok); CAMS split 10->2 ex 2025-12-05 (x5, gap check ok). Bug found and fixed: ISIN changes on a face-value split and feeds keep the old ISIN, so guards now use `same_issuer_equity()` (first 9 chars).

## Session D1 results (2026-11-08)

Session C's open issues, all resolved (commit 3c8b088):
1. Bare numbers: `resolve` wraps `face_value_inr` (`tools/data/resolve.py: resolve_output`); `prices` wraps the corporate-action numbers (`prices.actions_output`). Smoke `_note` was updated for the new shape.
2. HDFCBANK quarter-sum flag: **a tagging inconsistency by the filer, not a parse error.** Interest earned reconciles exactly. In the Q2FY26, Q4FY26/FY26 and Q2FY27 filings HDFC Bank files `ProfitLossOfMinorityInterest` = 0 and tags `ProfitLossForThePeriod` with the after-minority figure. In Q1FY26 and Q3FY26 it files PAT before minority interest. Changes: bank mapping gained `minority_interest`; the crosscheck table has a `note` column that explains this automatically; a `pat_owners` check was added (FY26 pat_owners reconciles exactly). FY25 pat_owners does not fully reconcile either: cause not identified (legacy filings).
3. CAMS "only 4 quarters": could not reproduce. Both list caches date from the smoke run, and all 8 requested consolidated quarters now parse, with no warnings. The smoke-run XBRL downloads probably failed transiently (their warnings were hidden). Financials output now has a `coverage` block (requested/returned/missing quarters, and whether each missing quarter is in the other basis), and the smoke note shows missing quarters and the warning count. The two bases are deliberately never mixed in one table.
4. Empty-response cache: `cache.is_empty_payload()`. Empty bodies get `ttl_hours=6` in their meta (EMPTY_TTL_HOURS), which overrides an immutable TTL. `read_cached` also expires empty bodies that were cached earlier.
5. Smoke snapshot note now prints row count and date.

New bug found and fixed (commit c322261): **shareholding** was null for every filing before Jun-2025 (old taxonomy: context ids without `_Context`, e.g. `ShareholdingOfPromoterAndPromoterGroupI`, plus government split into central and state). The Jun-2025 filings showed 5007% because they store percent, not fractions. `parse_shp` now tries both context sets and picks the scale from promoter + public = 1 or 100 (`scale_evidence` column). A company with no promoter group now gets `pledge_evidence` "no promoter group". Old filings report promoter 0.0 and new ones report null (both as filed). RELIANCE/CAMS/HDFCBANK now give 12 full quarters.

Fixture tests (commit c322261): `tests/conftest.py` (autouse: refuse-all transport, CACHE_ROOT -> tmp in every module that binds it, rate limits off; `routes({...})` fixture), `tests/test_data_layer.py` (33 tests, green), `tests/fixtures/record.py` re-records trimmed fixtures from `data/cache`.

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
- Freeze input `runs/<run_id>/freeze_input.json`: `{model_id, horizon_months?, picks: [{symbol, weight, thesis, scenarios: [{name, probability, return_pct, return_range_pct: [lo|null, hi|null]}], p_beat_benchmark, kill_criteria: [..], review_dates: [YYYY-MM-DD]}], cohorts?: {B: [SYM], C: [SYM], D: [SYM]}}`. Validation: weights > 0 summing <= 1; scenario probabilities sum to 1 +- 0.01; p in [0, 1]; thesis and kill criteria required; zero picks allowed. Cohorts not listed are read from the run folder: B = `dossiers/*.json` (`identity.nse_symbol`/`symbol`), C = `redteam/*.json` with `"verdict": "kill"`, D = `candidates.json` (list, or `{candidates: [...]}`, of symbols or `{symbol}`). **Session E must make the agents write these files in that shape.** Scenario `return_range_pct` is needed for the multi-class scenario Brier score.
- Entry = close of the first session after the freeze date; returns are TR (dividends reinvested); cohort A cash earns 0; B/C/D equal-weight buy-and-hold; members without prices are excluded from the mean and named (survivorship risk). `freeze` requires `--approved "<who/when>"`. Capital: mandate `capital_inr`, else notional INR 10 lakh (labelled).

Cost and tax sources (verified 2026-11-08; full notes in `docs/costs_research_2026-11-08.md`): STT 0.1% each side (NSE/FATAX/73524), NSE txn INR 307/crore incl. IPFT (NSE/FA/73061), BSE INR 375/crore (BSE equity master circular Apr-2026), SEBI INR 10/crore (NSE investor page), stamp 0.015% buy (NSE), GST 18% on brokerage + exchange + SEBI fee (SEBI circular 18-Jul-2022), CDSL INR 3.50 / NSDL INR 4.00 per debit, STCG 20% s.111A / s.196 (2025 Act), LTCG 12.5% above INR 1.25 lakh s.112A / s.198, holding > 12 months s.2(42A) / s.2(101)(b), cess 4%, surcharge cap 15% (Budget memo), 87A/s.156 not against 111A/112A, dividend TDS 10% above INR 10,000 s.194 / s.393. Budget 2026 changed STT on F&O only.

### Session E: agents, skill, references, docs (start here)
Write the 5 references, 4 agent definitions (opus, effort high, Agent tool blocked, hooks), SKILL.md (§3 nearly verbatim; modes; phases; <500 lines), hooks scripts, `.claude/settings.json`, CLAUDE.md (short), README.md. Re-read each agent as if it had no other context. Update this file. Commit. Then the user restarts Claude Code.
Carry over from Phase D:
- `output-schemas.md` must define `freeze_input.json`, `dossiers/*.json` (with `identity`), `redteam/*.json` (with `verdict`: kill/pass/...), `candidates.json` exactly as in "Session D2 results", plus the ledger record types. Agents write those files; the ledger reads them.
- Teach agents the command order: `data prices SYM --years 10` (and for each peer) before `compute valuation`; `data financials` before `ratios`; `compute calc` for any arithmetic; quote `warnings` from compute outputs (unadjusted price gaps) instead of ignoring them.
- `ledger freeze` needs `--approved`; the SKILL must run it only after the user's explicit approval in chat and pass the approval text. Dry runs use `--ledger-dir ledger/test` (gitignored).
- Bank analysts: run `ratios --basis standalone` for asset quality; NIM/CASA/credit cost come from presentations with page cites.
- Tell the user the cost DEFAULTs (brokerage, DP charge) in `config/costs.yaml` need confirming once a broker is chosen, and re-verify rates after each Budget.

### Session F: dry run
One lens, three companies, red team on all, portfolio step; `runs/<date>-dryrun/`; freeze only to `ledger/test/`. Report what worked, failure modes caught, shallowness, time/usage, fixes.
