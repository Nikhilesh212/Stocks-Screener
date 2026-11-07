# Build state and handoff

Read this first in any new build session, then `docs/SPEC.md` (the original spec).
Each build phase runs in its own Claude Code session to keep context small.
Update this file and commit at the end of every phase.

## Phase status

| Phase | What | Status |
|---|---|---|
| A | Questions | done 2026-11-08: user chose all defaults |
| B | Docs + plan | done 2026-11-08: plan approved with defaults (below) |
| C | Data layer + smoke | code done, smoke run 2026-11-08. **Missing: recorded-fixture unit tests for the data layer** (do in Phase D session) |
| D | Compute + ledger + tests + costs.yaml | not started |
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

## Open issues for Session D (fix first)

1. Bare numbers in outputs: `resolve` `entity.face_value_inr`; `prices` `corporate_actions[].factor/cash_per_share/observed_gap/applied_factor`. Wrap in `num()` or make them a `table()`.
2. HDFCBANK financials: one "sum of quarters vs FY" cross-check flag. Find out whether it's a parse/period problem or a real reporting effect (e.g. the merger), and note it.
3. CAMS financials returned only 4 quarters with `--quarters 8`; check legacy consolidated filings (maybe `indAs` label or basis), and fall back to standalone per period if needed.
4. Cache risk: an empty 200 response for a past-dated chunk is cached forever (`ttl_hours=None`). Don't cache empty lists for immutable keys, or give them a short TTL.
5. `data index snapshot` note prints `""` in smoke; cosmetic.

## Next sessions

### Session D: compute, ledger, tests, costs
1. Recorded-fixture tests for the data layer: copy small real responses into `tests/fixtures/` (trim big ones), test via `set_transport`, assert `find_bare_numbers(out) == []`. Cover: corp-action parsing (`Bonus 1:1`, `Bonus 4:1`, `Face Value Split ... From Rs 10/- ... To Rs 2/-`, rights text), adjustment on RELIANCE 2024 bonus and CAMS 2025 split, XBRL legacy FourD mislabel fix, bank XBRL, SHP parse, periods/units.
2. `tools/compute/`: calc (safe arithmetic evaluator for agents), ratios, valuation, reverse_dcf, technicals, base_rates, portfolio, costs_tax, each a pure function plus a CLI command reading cached parquet/JSON. Hand-checked unit tests for each. No scores or rankings.
3. `config/costs.yaml`: verify current brokerage-independent charges (STT, exchange txn, SEBI fee, stamp duty, GST, DP) and capital-gains rates from official sources (NSE circulars, Income Tax / Finance Act), each with URL + verification date.
4. `tools/ledger/`: freeze, mark, review, postmortem, cohorts A-E. Append-only JSONL; `--ledger-dir ledger/test` for dry runs. Entry price = last close at freeze + next-session close (evaluation uses next close). Total-return for picks (dividends). Tax with and without the LTCG exemption.
5. `uv run pytest` green. Update this file. Commit.

### Session E: agents, skill, references, docs
Write the 5 references, 4 agent definitions (opus, effort high, Agent tool blocked, hooks), SKILL.md (§3 nearly verbatim; modes; phases; <500 lines), hooks scripts, `.claude/settings.json`, CLAUDE.md (short), README.md. Re-read each agent as if it had no other context. Update this file. Commit. Then the user restarts Claude Code.

### Session F: dry run
One lens, three companies, red team on all, portfolio step; `runs/<date>-dryrun/`; freeze only to `ledger/test/`. Report what worked, failure modes caught, shallowness, time/usage, fixes.
