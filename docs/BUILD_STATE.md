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
| D | Compute + ledger + tests + costs.yaml | **in progress**: Session D1 did open issues, fixture tests, part of compute. Continue from "Session D2" below |
| E | References, 4 agents, SKILL.md, CLAUDE.md, README, settings.json, hooks | not started |
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

Provenance: `tools/common/provenance.py`: `num()`, `missing()`, `derived()`, `table()`; `find_bare_numbers()` must return [] for every command output (tests should assert this).
HTTP test seam: `tools.common.http.set_transport(fn)` swaps in a recorded-fixture transport.

## Known gaps (tell the user in hand-over)

- Financial history: Ind AS XBRL only (about FY18 onward). BS/CF only at H1 and FY. 10-year history needs annual-report reading.
- Bank KPIs NIM/CASA/credit cost not in XBRL; analysts extract from presentations with page cites. GNPA/NNPA %, CET1, ROA are in XBRL (unit "as filed").
- CPI and crude: no working keyless source; cite dated releases.
- Index P/E: suspected methodology break (standalone -> consolidated earnings ~2021); verify before base_rates uses it.
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

### Session D2: rest of Phase D (start here)
Compute work in progress. All of it imports cleanly and is registered nowhere yet (`tools/compute/__init__.py` is empty, so the CLI hides the group). None of it has unit tests yet.
- `tools/compute/_util.py`: frame(table) -> DataFrame, fnum/safe_div (None, never 0), cagr (None + reason for non-positive endpoints), percentile_rank, t_quantile (Cornish-Fisher), normal_quantile (Acklam), mean_ci(values, n_eff), wilson_ci, records_table, load_mandate.
- `calc.py`: DONE (AST whitelist, `--var NAME=VALUE`, functions abs/min/max/round/sqrt/log/ln/log10/exp/sum/avg/cagr, exponent cap; errors raise CalcError(InputError)). Needs tests.
- `ratios.py`: written, **never run**. Input is `--input` (JSON from `data financials --out`) or the symbol. It computes per-FY corporate ratios (EBITDA excludes other income; ROE/ROCE on average balances; D/E; net debt; interest cover; OCF/EBITDA; OCF/PAT; FCF = cfo - capex, where XBRL capex is a positive outflow; receivable/inventory/payable days; CCC; shares from paid-up/FV; dilution), bank ratios (NII/avg assets as a NIM proxy, cost/income, provisions/avg advances as a credit-cost proxy, ROA, ROE, PCR from absolute NPAs; asset-quality fields filed as 0 count as not reported, since consolidated bank filings carry 0), CAGRs over 3/5/10y, TTM, quarterly margins, contingent liabilities via a `--contingent-liabilities` flag (cited). Run it on RELIANCE, HDFCBANK (try standalone too) and CAMS, then fix.
- `base_rates.py`: DONE and run on real data (no bare numbers). Month-end samples, forward TRI return, P/E percentile buckets over the full sample (look-ahead noted), n_independent = n_obs/H, t-interval and Wilson CIs, the naive interval shown for contrast, `--pe-method spliced|post_break|raw` (spliced divides pre-break P/E by the measured jump), `--where COL:LO:HI`. Needs a synthetic-series unit test.
- `technicals.py`: written, **never run**. DMA 50/200, 52w range, 3/6/12m stock TR vs index TRI, realised vol 60/252d, max drawdown with dates, ADV 20/60d (INR crore), delivery %.
- **Not started:** `valuation.py`, `reverse_dcf.py`, `portfolio.py`, `costs_tax.py`, `__init__.py` register(), and unit tests for every compute module.
  - valuation design: P/E, EV/EBITDA, P/B, FCF yield now. For history, sample monthly; market cap = adj_close(t) x filed shares x cum adj_factor at the filing's period end (survives a split before the next filing); TTM from quarters available as of t (lag 45 days for Q1-Q3, 60 for Q4); percentile against own 5/10y history (say if the history is shorter); peers via `--peers SYM,...` from the cache. Banks: P/E and P/B only.
  - reverse_dcf design: CF0 per share (FCF/share, EPS, or `--base-value`); N high-growth years at g; F fade years with growth fading linearly to gt; Gordon terminal value; bisection for g in [-0.9, 2.0], reporting out-of-range; error if ke <= gt or CF0 <= 0. Sensitivity grids of ke x N and ke x gt. Hand-check: N=F=0 gives Gordon.
  - portfolio design: `--holdings SYM:w,...` or JSON; correlation of daily returns (1y); beta vs Nifty 500; size bucket from index membership (NIFTY 100 / MIDCAP 150 / SMALLCAP 250 / other); momentum 12-1m; value only if supplied; HHI and effective N; cash = 1 - sum(w); days to exit at 10/15/20% of ADV (needs capital; missing if null); -20% beta stress; mandate checks (facts about limit breaches only).
  - costs_tax design: rates in `config/costs.yaml` as lists with `effective_from`; brokerage `# DEFAULT - confirm` (no broker); STCG if held 12 months or less, LTCG above; exemption shown with and without; cess 4%; surcharge as a parameter. The ledger reuses these functions.
- **costs research:** a background agent in Session D1 was verifying rates from official sources and writing to `~/.config/Claude/side-session-notes/local_8a551c4f-46f1-4927-aacc-2577f25b7f10/costs_research.md`. Read it if present. If missing or incomplete, redo the verification (STT, NSE txn charge, SEBI fee, stamp duty, GST base, CDSL/NSDL DP, STCG/LTCG rates and exemption, sections under both the 1961 and 2025 Acts, cess, surcharge cap, 87A, dividend TDS).
- Then `tools/ledger/` (spec §5.4). Proposed freeze input: `runs/<run_id>/freeze_input.json` with picks (weight, thesis, probabilities, scenarios, kill criteria, review dates). Cohorts B/C/D come from `dossiers/*.json`, `redteam/*` verdicts and `candidates.json`, or are listed explicitly. Append-only JSONL, `--ledger-dir ledger/test`, entry at next-session close, TR with dividends, tax with and without the LTCG exemption. Session E documents the schema in `output-schemas.md`.
- Finish: `uv run pytest` green, update this file (CLI table for compute/ledger, gaps), commit locally, report to the user (built, infeasible, cost/tax sources).

### Session E: agents, skill, references, docs
Write the 5 references, 4 agent definitions (opus, effort high, Agent tool blocked, hooks), SKILL.md (§3 nearly verbatim; modes; phases; <500 lines), hooks scripts, `.claude/settings.json`, CLAUDE.md (short), README.md. Re-read each agent as if it had no other context. Update this file. Commit. Then the user restarts Claude Code.

### Session F: dry run
One lens, three companies, red team on all, portfolio step; `runs/<date>-dryrun/`; freeze only to `ledger/test/`. Report what worked, failure modes caught, shallowness, time/usage, fixes.
