# Build an on-demand Indian equity research system in Claude Code

> Original build specification from the user (2026-11-08), kept verbatim so later build sessions can read it.
> Decisions taken since are recorded in `docs/BUILD_STATE.md`; where they differ, BUILD_STATE.md wins.

Read this entire document before writing any code. It describes what to build, why each design choice exists, and the order to build in. Where it says **CHECKPOINT**, stop and wait for my reply before continuing.

---

## 1. Mission

Build, inside this repository, a research system for Indian listed equities that runs inside Claude Code. When I trigger it (before Dhanteras, or whenever I want fresh ideas), a future Claude Code session will:

- form its own view of the market;
- hunt for candidates through several investment lenses;
- research each candidate deeply from primary documents;
- have every thesis attacked by an independent red team;
- construct a portfolio;
- present it to me.

I review, challenge and decide. Approved picks are frozen in a ledger and tracked against the index, so the system's real track record builds up over time.

Build all of it: the Python tools, the subagents, the skill, the ledger, tests and docs. Then dry-run it end to end.

### What this system is

- An analyst team (the main session plus subagents), with me as the portfolio manager.
- Judgment-driven. Every run thinks afresh. The protocol structures the *process* (what must be read, verified and written down). It never structures the *conclusions*.

### What this system is not

- **Not a rules engine.** No Python function may output a buy/sell ranking, a composite score, or anything that substitutes for judgment. Screens are allowed only as search aids that Claude chooses to call with its own parameters. They never act as gates that decide what gets considered.
- **Not an auto-trader.** Never place, modify or cancel orders. Never call broker order endpoints. Use read-only credentials and scopes only.
- **Not investment advice.** It produces research for my own decisions.

### The split between code and Claude

- **Code** fetches facts and computes numbers.
- **Claude** decides what matters, where to look, and what to believe.

This split exists because LLMs reason well over documents but make arithmetic and data-retrieval errors, and code has the opposite profile.

---

## 2. The evidence this design is built on

Understand these findings, because every structural choice below exists to counter one of them.

1. **Unstructured prompts don't work.** A live, ten-month, out-of-sample study by Spain's securities regulator (CNMV Working Paper 96, March 2026) tested four LLMs picking stocks:
   - Plain "which stocks should I buy" prompts produced excess returns statistically indistinguishable from zero.
   - Structured prompts improved results materially.
   - Structured prompts plus iterative review that corrected the models' errors did best.
   - Grounding recommendations in official regulatory filings improved accuracy further.
   - Caveat: the sample was only ten monthly observations, on a long-short portfolio of large Spanish stocks. Treat it as directional evidence, not a performance promise.

2. **LLMs fail in recognisable ways.** The same study documented these recurring failures. Your design must guard against each one:
   - **Entity mismatch:** pulling data for the wrong company with a similar name.
   - **Fabricated figures:** producing a price or ratio that appears in no source.
   - **Temporal mismatch:** mixing fiscal periods (this year's EPS with last year's price).
   - **Table misreading:** taking a value from the wrong row or column.
   - **Unit and currency confusion.** In India, watch especially for ₹ crore vs ₹ lakh vs ₹ million, and standalone vs consolidated figures.
   - **Aggregation and arithmetic errors:** weighted scores outside the feasible range, wrong averages.
   - **Carryover:** reusing a value from a previous company or query.
   - **Failed self-correction:** acknowledging an error but keeping the wrong number.
   - **Complexity-reduction bias:** analysing some companies fully and others superficially.
   - **Opaque reasoning:** being unable to reproduce how a conclusion was reached.

3. **Live track records are noisy.** Live LLM trading benchmarks show that most model-seasons don't finish profitable, and a model's rank in one period doesn't predict its rank in the next. Broader, longer backtests shrink previously reported LLM advantages. One good run proves nothing.

4. **LLM picks cannot be honestly backtested.** The model's training data contains what happened after any historical date, so a "what would you have picked in 2022" test is contaminated. Evaluation must be forward-only: freeze picks with a timestamp and track them.

**Design consequences.** Each one maps to a failure above:

- Ground every claim in primary documents (annual reports, results, concall transcripts, exchange filings).
- Give every number a provenance record (source, period, as-of date, unit).
- Do all arithmetic in tested code.
- Resolve every company to its ISIN and echo the ISIN back from every tool, so entity mismatches are detectable.
- Run each company's analysis in a fresh subagent context, which prevents carryover and conviction bleed.
- Verify independently in a separate context, using a red team that re-fetches key numbers rather than trusting the analyst.
- Keep a human in the loop before anything is frozen.
- Evaluate forward-only against an index, using cohort comparisons to measure which stage adds value.

---

## 3. The objective: how a run is scored

Put this section into SKILL.md nearly verbatim. Every run must be told exactly how it will be judged.

### Primary objective

Maximise expected excess return over the **Nifty 500 Total Return Index** across the mandate horizon (default 12 months or more). Measure it net of estimated transaction costs and capital-gains tax.

### Constraints

These come from `config/mandate.yaml`:

- portfolio drawdown tolerance;
- maximum weight per position;
- maximum weight per sector;
- liquidity limit: each position must be exitable within a few days at a modest fraction of average daily traded value;
- universe and exclusions.

### Calibration

Every pick carries explicit probabilities: the probability of beating the benchmark over the horizon, and bear/base/bull scenario probabilities. Post-mortems score these with a Brier score and a calibration table. Overconfidence is penalised, not rewarded.

### Legitimate outcomes

Fewer picks, holding cash, or "buy the index instead" are all acceptable answers. A forced pick that loses is worse than no pick. A system that must always find winners will invent them.

### Why this is not "maximise profit at any risk"

Taken literally, that objective rewards maximum variance: concentrated small-cap momentum bets that look brilliant in a good year and blow up in a bad one. With one run per occasion, luck and skill become indistinguishable. Excess return under constraints, plus calibration, is what lets me learn whether the system has an edge.

---

## 4. Repository layout

Create this structure. Adjust names only if Claude Code's current conventions require it (see Phase B).

```
.
├── CLAUDE.md                      # project memory: purpose, rules, commands
├── README.md                      # how to set up, run, review, post-mortem
├── pyproject.toml                 # pinned deps; use uv or venv, your choice, documented
├── .env.example                   # every credential the tools can use, all optional
├── .gitignore                     # .env, data/cache/, large PDFs
├── config/
│   ├── mandate.yaml               # horizon, benchmark, limits, exclusions (see §9)
│   ├── sources.yaml               # data sources, priority order, status, notes
│   └── costs.yaml                 # transaction costs and tax rates, each with source + date
├── .claude/
│   ├── skills/
│   │   └── equity-research/
│   │       ├── SKILL.md           # the run protocol (see §7)
│   │       └── references/
│   │           ├── failure-modes.md
│   │           ├── red-flags-india.md
│   │           ├── valuation-guide.md
│   │           ├── output-schemas.md
│   │           └── evaluation.md
│   └── agents/
│       ├── market-strategist.md
│       ├── hunter.md
│       ├── company-analyst.md
│       └── red-team.md
├── tools/                         # Python package; CLI entry: python -m tools ...
│   ├── __main__.py
│   ├── common/                    # provenance types, caching, http client, units, entity resolution
│   ├── data/                      # resolve, prices, index, filings, financials, shareholding, macro, events
│   ├── compute/                   # ratios, valuation, reverse_dcf, technicals, base_rates, portfolio, costs_tax
│   └── ledger/                    # freeze, mark, review, postmortem, cohorts
├── tests/                         # pytest; unit tests use recorded fixtures, no network
├── data/cache/                    # gitignored; raw downloads and extracted text, keyed by ISIN
├── runs/<run_id>/                 # one folder per research run (see §7)
└── ledger/
    ├── picks.jsonl                # append-only
    ├── runs.jsonl                 # append-only run metadata
    ├── postmortems/
    ├── lessons.md                 # distilled lessons, read at the start of every run
    └── test/                      # dry-run and test ledger, kept separate from the real one
```

---

## 5. Python tools: specification

### 5.1 General contract (applies to every tool)

**Interface**
- `python -m tools <group> <command> [args] --json` writes JSON to stdout and logs to stderr. Subagents call tools through Bash, so the CLI must be stable and documented (`python -m tools --help` and per-command help).

**Provenance on every number**
- Every numeric output is an object: `{value, unit, period, as_of, source, source_url, source_doc, page, retrieved_at, notes}`.
- No bare numbers in tool outputs.

**Units and periods**
- Units are explicit and normalised: store money in ₹ crore unless otherwise labelled, and keep per-share values in ₹.
- Fiscal periods use Indian notation (FY26, Q2FY27).
- Standalone vs consolidated is always labelled. Consolidated is the default where available.

**Entity resolution**
- `tools data resolve <symbol|name>` returns ISIN, NSE symbol, BSE code, legal name, industry classification and index memberships.
- Every other tool accepts ISIN or symbol and echoes the ISIN and legal name back, so mismatches are detectable downstream.

**Missing data**
- Return `null` with a reason. Never impute silently, and never substitute zero for a missing value.

**Caching**
- Disk cache keyed by ISIN, source and period, with `retrieved_at`. A `--refresh` flag bypasses it.
- PDFs are stored and their extracted text kept with page numbers, so dossiers can cite pages.

**Cross-checks**
- Where two sources provide the same figure, compare them. Flag differences above 2% in the output.

**Politeness and legality**
- Rate-limit requests and use sensible headers.
- Respect site terms and robots.txt.
- Never bypass CAPTCHAs, bot protection or logins. If a source blocks automated access, mark it unavailable in `config/sources.yaml` and tell me. Don't work around it.

**Secrets**
- Read credentials from `.env` via python-dotenv. Never print, log or commit them.
- Use read-only scopes only.

**Tests**
- Unit tests use recorded fixtures and never touch the network.
- A separate `python -m tools smoke` command hits live sources and prints a status table.

### 5.2 Data group

For every source below, **verify it works today** rather than trusting memory. Exchange endpoints and site structures change. Record what you find in `config/sources.yaml`.

| Command | What it provides | Candidate sources, in priority order |
|---|---|---|
| `resolve` | Identity, classification, index membership | NSE/BSE equity lists and index constituent files |
| `prices` | Daily OHLCV adjusted for splits and bonuses; corporate-action log; delivery % if available | (1) my broker's API, if I provide read-only credentials; (2) NSE bhavcopy archives; (3) yfinance `.NS` as a last resort, flagged lower-trust |
| `index` | Nifty 500 price and TRI history, Nifty 50, sector indices; index P/E, P/B and dividend-yield history | NSE index data |
| `filings` | List and download announcements, quarterly results, annual reports, investor presentations, concall transcripts, credit-rating actions | NSE/BSE corporate announcement feeds, company investor-relations pages |
| `financials` | Annual (10 years) and quarterly (8+ quarters) P&L, balance sheet, cash flow; standalone and consolidated | Parsed from exchange results filings or XBRL where available; Screener.in export only if I supply my own account and only within its terms; cross-check between sources |
| `shareholding` | Promoter %, pledged %, FII/DII/MF/retail holdings over 8+ quarters | Exchange shareholding-pattern filings |
| `macro` | RBI policy rate, CPI, 10-year G-sec yield, INR/USD, crude, FII/DII flows | RBI, MOSPI, NSE/NSDL. Record **release dates** as well as values, because data is revised and released with lags. |
| `events` | Upcoming results dates, corporate actions, whether the stock is on NSE ASM/GSM surveillance lists | NSE/BSE |

**Price adjustments.** Verify corporate-action adjustment against at least one known bonus issue and one stock split before trusting the price series. Bonuses are frequent in India and a common source of silent errors.

**News.** News search stays in Claude's hands (WebSearch/WebFetch inside the run). It is not a tool, and every news item cited must carry its publication date.

### 5.3 Compute group

These are pure functions. Unit-test every one against hand-computed examples.

- **`ratios`**
  - Return metrics: ROCE, ROE, and ROA (for financials).
  - Margins and growth: margin history, revenue/EBITDA/PAT/EPS CAGRs over 3, 5 and 10 years.
  - Balance sheet: debt-to-equity, interest coverage, contingent liabilities as % of net worth.
  - Earnings quality: OCF/EBITDA, OCF/PAT, free cash flow, receivable/inventory/payable days and their trend, cash conversion cycle, other income as % of PBT, dilution history.
  - Banks and NBFCs: NIM, GNPA/NNPA, PCR, CASA, CAR, credit cost, where available.
- **`valuation`**
  - P/E, EV/EBITDA, P/B and FCF yield.
  - Each multiple's percentile against the company's own 5- and 10-year history, and against a peer set Claude supplies.
- **`reverse_dcf`**
  - Given price, cost of equity, a high-growth period, fade and terminal growth, solve for the growth rate the market is implying.
  - Output a sensitivity table.
  - The question it answers is "what has to go right to justify today's price?", not "what is it worth".
- **`technicals`**
  - Trend versus the 50- and 200-day moving averages, distance from 52-week high and low.
  - 3/6/12-month relative strength versus Nifty 500, realised volatility, maximum drawdown.
  - 20- and 60-day average daily traded value in ₹ crore.
- **`base_rates`**
  - The distribution of forward returns over the horizon for Nifty 500 (and Nifty 50), conditional on starting index valuation (P/E percentile bucket) and optionally other state variables Claude chooses.
  - Always report the number of observations and confidence intervals.
  - Warn explicitly that overlapping windows inflate apparent sample size.
- **`portfolio`**
  - Correlation matrix from daily returns.
  - Exposure summary: sector, size, value, momentum, beta.
  - Concentration (HHI).
  - Days to exit each position at 10–20% of average daily traded value.
  - Simple stress test: beta-implied loss in a −20% market.
- **`costs_tax`**
  - Estimate round-trip costs: brokerage, STT, exchange charges, stamp duty, GST, SEBI fee, DP charges.
  - Estimate capital-gains tax impact by holding period.
  - Every rate lives in `config/costs.yaml` with its source URL and verification date. Verify current rates during the build, because they change with Union Budgets.

### 5.4 Ledger group

- **`freeze <run_id>`** appends approved picks to `ledger/picks.jsonl`. It runs only after my explicit approval in a run. Each record contains:
  - run_id, timestamp, model id;
  - ISIN and symbol;
  - reference entry price and its timestamp, weight;
  - thesis (three sentences);
  - scenario probabilities and return estimates, probability of beating the benchmark;
  - kill criteria, review dates;
  - benchmark (Nifty 500 TRI) level at freeze;
  - the cohort definitions (below).

  The ledger is append-only. Corrections are new records that reference the original.
- **`mark <run_id>`** reports the current value of every cohort versus the benchmark.
- **`review <run_id>`** fetches results and announcements since the last review and lists them next to each pick's kill criteria. Claude judges whether a criterion has fired.
- **`postmortem <run_id>`**, at the end of the horizon, computes:
  - per-pick and portfolio excess return, net of estimated costs and tax;
  - Brier score and a calibration table;
  - the cohort comparison.

  It then writes a template at `ledger/postmortems/<run_id>.md` for Claude to fill in.

**Cohorts.** This is the most important evaluation feature, because it tells me which stage of the pipeline adds value. Record and track all of these for every run:

| Cohort | Contents |
|---|---|
| A | Final portfolio, as weighted |
| B | Equal-weight of all deep-dived names |
| C | Equal-weight of names the red team killed |
| D | Equal-weight of the hunters' full candidate list |
| E | Nifty 500 TRI |

How to read the comparisons:

- If B ≈ A, portfolio construction adds nothing.
- If C beats A, the red team is destroying value.
- If D ≈ B, the deep dives add nothing.
- If D ≈ E, hunting adds nothing.

---

## 6. Subagents (`.claude/agents/`)

**Each definition must be self-contained.** Claude Code subagents receive only their own system prompt plus basic environment details. They do not see the main session's instructions. So each definition must include, or tell the subagent to read by path:

- the provenance rules;
- the relevant failure modes;
- its output schema;
- its file-writing boundaries.

Point them to the files in `.claude/skills/equity-research/references/`.

**Model.** Use the most capable model available for every analytical subagent (`opus` or `inherit`; check the current docs for valid aliases and whether an effort setting exists). Do not use small or fast models for analysis.

**Tools.** Read, Grep, Glob, Bash (for the tools CLI), WebSearch and WebFetch, plus Write restricted by instruction to the subagent's own output paths under `runs/<run_id>/`.

### 6.1 `market-strategist`

**Purpose:** a top-down market read at the start of each run.

**Output:** `runs/<run_id>/market_view.md`, covering:

- Market valuation versus history, with base rates from the tool: what forward returns looked like from similar starting points, with n and confidence intervals.
- Where we are in the earnings cycle; rates and liquidity; domestic flows (SIP, DII) versus FII flows.
- The policy and event calendar within the horizon: Budget, RBI meetings, major elections, global risks.
- What the current consensus believes, and which sectors are crowded or hated.
- The strategist's view, stated with a confidence level, and what would change it.
- Implications for hunting: which lenses look most promising now, and which areas to be careful in.

Every figure is fetched via tools or cited with a date. No numbers from memory.

### 6.2 `hunter`

One definition, invoked several times in parallel, each time with a different lens passed in the task. Default lenses:

1. Quality compounders at reasonable prices.
2. Value, turnaround and re-rating candidates.
3. Earnings momentum and upgrade cycles.
4. Policy, capex and cyclical beneficiaries.
5. Under-covered small and mid caps (liquidity floor applies).
6. Contrarian: the most disliked sectors, looking for what has been oversold.

The orchestrator may add or replace a lens per run if the market view suggests it.

**Output:** 8–15 candidates per lens. For each:

- why it fits the lens;
- *why the market might be mispricing it*;
- *why it might already be priced in*;
- the key data points, fetched via tools.

Hunters may call screening tools with parameters they choose. They must not let a screen decide for them.

### 6.3 `company-analyst`

One fresh instance per company. This is the core of the system.

**Mandatory reading before forming any view:**

- the latest annual report (business section, MD&A, notes on related-party transactions and contingent liabilities, auditor's report);
- the last four to eight quarterly results;
- the last two to four concall transcripts;
- the latest investor presentation;
- the shareholding pattern trend;
- credit-rating actions;
- exchange announcements from the last 12 months.

Log what was read in the dossier. If something could not be obtained, say so.

**Hard rules:**

- Begin the dossier with an identity block matching `resolve` output: ISIN, symbols, legal name.
- Every number comes from a tool or a cited document with period and page.
- All arithmetic is done via tools or Python, never mentally.
- When correcting an error, re-fetch the number. Never "correct" it verbally while keeping the old value.
- Read with the same depth for every company. If time or context runs short, say so explicitly rather than quietly doing a shallower job.
- Seek disconfirming evidence actively.

**Outputs:**

- `runs/<run_id>/dossiers/<SYMBOL>.md`, following the template in `output-schemas.md`.
- `runs/<run_id>/dossiers/<SYMBOL>.json`, a machine summary.
- A separate `runs/<run_id>/dossiers/<SYMBOL>.conviction.json` holding the probabilities and confidence. It is kept separate so the red team doesn't see it.

**Dossier template sections:**

1. Identity block and liquidity.
2. What the business does and how it makes money.
3. Industry structure, competitive position, moat (or its absence).
4. Financial history tables, with provenance.
5. Earnings quality.
6. Governance and red-flag checklist from `red-flags-india.md`: each item marked pass, flag or unknown, with evidence.
7. Management: capital-allocation record, *guidance versus delivery* (compare promises made in past concalls with what happened), promoter behaviour.
8. Valuation: multiples versus own history and peers; reverse DCF; the analyst's own view of plausible growth, with reasoning.
9. Catalysts and dated events within the horizon.
10. Technical and entry context.
11. Bear, base and bull scenarios: drivers, probability, horizon return. Expected value and probability of beating the benchmark.
12. **Variant perception:** what this analysis believes that the market doesn't, and the strongest reason it might be wrong.
13. **Kill criteria:** specific, observable, dated conditions that would invalidate the thesis.
14. Open questions and data gaps.
15. Sources.

### 6.4 `red-team`

One fresh instance per dossier. It receives the dossier but **not** the conviction file. Its job has two parts.

**Verification**
- Independently re-fetch the 8–10 most decision-relevant numbers via tools and compare them with the dossier.
- Check entity identity, period alignment and units.
- List every discrepancy with its size.

**Attack**
- Write the strongest bear case, as a short-seller would.
- Name what the bull case ignores or underweights.
- Test whether the variant perception is genuinely non-consensus.
- Check whether the kill criteria are real or decorative.

**Verdict:** `survives`, `weakened` or `killed`, with reasons.

**Output:** `runs/<run_id>/redteam/<SYMBOL>.md` and a JSON verdict.

The red team is rewarded for finding real problems, not for being negative. A thesis that survives honest attack is the goal.

---

## 7. SKILL.md: the run protocol

### Frontmatter

- `name: equity-research`
- A `description` that triggers readily. Claude tends to under-trigger skills, so make it a little pushy. It should cover:
  - "run research", "stock ideas", "find stocks to buy";
  - "Dhanteras picks", "Diwali portfolio", "Muhurat trading picks";
  - "review my picks", "check kill criteria";
  - "post-mortem";
  - "deep dive on <company>".

### Size and style

- Keep the body under roughly 500 lines. Put detail in `references/` and point to it, saying when to read each file.
- Write in the imperative, and explain *why* each step exists rather than relying on bare MUSTs. Future sessions follow instructions better when they understand the purpose.

### Modes

1. **New run** (default).
2. **Review:** check open runs against kill criteria after new results.
3. **Post-mortem:** at horizon end.
4. **Single-company deep dive:** analyst plus red team only, no portfolio step.

### New-run phases

Each phase writes its output into `runs/<run_id>/`, where `run_id = YYYY-MM-DD-<short-slug>`.

**Phase 0: Mandate and memory**
- Load `config/mandate.yaml` and ask me to confirm or change it for this run (horizon, capital to deploy, drawdown tolerance, number of names, exclusions, any themes to include or avoid).
- Read `ledger/lessons.md` and the latest post-mortems. Write the lessons that apply to this run into `runs/<run_id>/lessons_applied.md`.
- If open runs exist, run a quick review first. New decisions should account for existing exposure.
- State the information cutoff (today's date). Nothing after it may be used.

**Phase 1: Market read**
- Spawn `market-strategist`.
- Show me a ten-line summary. I may push back before hunting starts.

**Phase 2: Hunting**
- Spawn hunters in parallel, one per lens.
- Merge and de-duplicate the results, noting names found by more than one lens.
- Apply only the *mandate's hard exclusions* mechanically. Everything else is judgment.
- Select 15–25 names for deep dives, with a written rationale that includes what was dropped and why. Save `candidates.json` (the full list, which becomes cohort D) and `shortlist.md`.
- Before Phase 3, tell me roughly how many subagent runs the next phases will take, because deep runs consume a lot of usage.
- **CHECKPOINT:** show me the shortlist. I may add or remove names.

**Phase 3: Deep dives**
- Spawn one `company-analyst` per name, in parallel batches of a size you judge sensible for rate limits and usage. Each runs in a fresh context.
- Never tell an analyst what you hope it finds. Pass only the company, the run_id, the mandate and the market-view path.

**Phase 4: Verification and red team**
- Spawn one `red-team` per dossier.
- If the red team finds material numerical discrepancies, send the dossier back to a fresh analyst *once*, with the discrepancy list and an instruction to re-fetch. If it still fails, drop the name.
- Killed names form cohort C.

**Phase 5: Portfolio construction**
- The main session does this, reading the dossiers, conviction files and red-team verdicts.
- Size positions by expected value and downside, within mandate limits.
- Run the portfolio tools and look for hidden common bets (for example, five names that all depend on falling rates).
- Explicitly compare the result against "buy the Nifty 500" and against "hold cash", and say why the portfolio is better, or recommend fewer names.
- Write `portfolio.md` and `final_report.md`.

**Phase 6: Present to me**

The report includes:

- a summary table: picks, weights, one-line thesis, probability of beating the benchmark, main risk, kill criteria;
- what was rejected and why, including the red-team kills;
- where the system is least confident, and the data gaps;
- a one-line note that this is research for my decision, not advice.

I will challenge it. Answer from evidence, revise where I'm right, and hold your ground where I'm not.

**Phase 7: Freeze**
- Only on my explicit approval, run `tools ledger freeze`.
- Record all five cohorts.
- Commit `runs/<run_id>/` and the ledger to git.

### Rules for the main session during any run

- Never state a number that wasn't produced by a tool or cited from a document in this run. Numbers remembered from training are not allowed in run outputs.
- Date-stamp everything.
- Prefer disconfirming evidence over confirming evidence.
- If a data source is down, say so and degrade gracefully. Never fill gaps silently.
- Do not propagate conviction between subagents.

### Review mode

- Run `tools ledger review`.
- For each pick, judge each kill criterion as fired, not fired or unclear, citing evidence.
- Recommend hold, trim, exit or "re-underwrite", and let me decide.
- Append dated notes to the run folder.

### Post-mortem mode

- Run `tools ledger postmortem`.
- Fill in the template, separating *decision quality* from *outcome*. A good decision can lose, and a bad one can win.
- Analyse calibration and the cohort comparison.
- Distil at most five durable lessons into `ledger/lessons.md`. Merge or replace older lessons rather than letting the file grow without bound.

### References to write

- **`failure-modes.md`:** the taxonomy from §2, with a concrete countermeasure for each.
- **`red-flags-india.md`.** Include at least:
  - promoter pledging, and its trend;
  - promoter selling;
  - auditor resignations or changes, and qualified opinions;
  - large or growing related-party transactions;
  - contingent liabilities relative to net worth;
  - capital work-in-progress that never completes;
  - receivables or inventory days rising faster than sales;
  - OCF persistently well below PAT;
  - frequent equity dilution and preferential allotments;
  - large unexplained "other income";
  - goodwill and loans to group entities;
  - credit-rating downgrades;
  - ASM/GSM surveillance listing;
  - SME-board or illiquid status;
  - frequent changes in accounting policy;
  - large unresolved tax or regulatory disputes;
  - management guidance repeatedly missed.
- **`valuation-guide.md`:** sector-appropriate approaches.
  - Banks and NBFCs: P/B against ROA and ROE, asset quality, growth.
  - Insurers: embedded-value-based measures.
  - Cyclicals: mid-cycle earnings rather than peak multiples.
  - Holding companies: sum of the parts with a discount.
  - Platforms and early-stage businesses: unit economics.
  - Also cover how to use the reverse DCF properly.
- **`output-schemas.md`:** exact templates and JSON schemas for market view, candidates, dossier, conviction file, red-team verdict, portfolio and final report.
- **`evaluation.md`:** the scoring rule from §3, the cohort logic from §5.4, calibration scoring, and why only forward evaluation is valid.

---

## 8. CLAUDE.md (project memory)

Keep it short. It loads in every session, so it should contain only:

- The project's purpose in two lines.
- Hard rules:
  - research only, never place orders;
  - every number has provenance;
  - arithmetic only in code;
  - never commit `.env` or cache;
  - the ledger is append-only.
- Key commands: setup, tests, smoke test, how to trigger each skill mode.
- Where things live.

---

## 9. `config/mandate.yaml`

Ask me for these values in Phase A. If I don't answer some, use the conservative defaults below and mark them `# DEFAULT - confirm`.

```yaml
horizon_months: 12            # >= 12 also qualifies listed equity for long-term capital gains treatment
benchmark: NIFTY 500 TRI
capital_inr: null             # optional; used only for liquidity and cost estimates
min_positions: 0              # zero is allowed: "buy the index" or "hold cash" are valid outcomes
max_positions: 10
max_weight: 0.15
max_sector_weight: 0.35
max_drawdown_tolerance: 0.25  # portfolio-level tolerance I am prepared to sit through
liquidity:
  min_adv_inr_crore: 5
  max_days_to_exit: 3
  participation_rate: 0.15
universe: NSE main board      # SME platform excluded by default
exclusions: []                # sectors or companies I don't want
include_themes: []
avoid_themes: []
allow_cash: true
instruments: equity_cash_only # no F&O, no leverage, no shorting
```

---

## 10. How to build: phases and checkpoints

### Phase A: Questions

Ask me the following in one message, then **CHECKPOINT**:

1. Mandate values from §9: horizon, drawdown tolerance, max positions, exclusions, capital (optional).
2. Which broker I use, and whether I'll create a read-only API key (Kite Connect, Upstox, Dhan, Fyers, Angel One SmartAPI, or none). Also whether I have a Screener.in account I'm willing to use.
3. Python environment preference (uv or venv) and OS.
4. One small-cap company I'd like included in smoke tests (or you choose).

### Phase B: Read the current docs, then plan

- Read the current Claude Code documentation on **skills** and **subagents**. Check frontmatter fields, model aliases, whether an effort setting exists, how skills are invoked, whether skills can be preloaded into subagents, and tool restrictions.
- Don't rely on memory: these features change often. Adjust §4 and §6 if the conventions differ.
- Then give me a short plan: the final file tree, the data sources you'll try first, and anything in this document you think is wrong or infeasible.
- **CHECKPOINT.**

### Phase C: Data layer

- Implement `tools/common` and the data group.
- Run `python -m tools smoke` on RELIANCE, HDFCBANK and the small cap.
- Show me a source-status table: each source, what it provides, whether it works, blocked or needs credentials, and notes. Update `config/sources.yaml` to match.
- **CHECKPOINT.**

### Phase D: Compute and ledger

- Implement the compute and ledger groups.
- Unit-test every compute function against hand-checked examples, including the corporate-action adjustment and the reverse DCF solver.
- Verify current cost and tax rates and record their sources in `config/costs.yaml`.
- Run the full test suite and make it pass.

### Phase E: Agents, skill and docs

- Write the reference files, the four subagent definitions, SKILL.md, CLAUDE.md and README.md.
- Re-read each subagent definition as if you were that subagent with no other context, and fix anything it couldn't act on.

### Phase F: Dry run

- Run the full protocol at reduced scope: one lens, three companies, red team on all three, portfolio step included.
- Write to `runs/<date>-dryrun/` and freeze only into `ledger/test/`.
- Report:
  - what worked;
  - which failure modes the verification caught;
  - where the subagents went shallow or broke rules;
  - approximate time and usage;
  - fixes made.
- Fix the problems and repeat once if needed.

### Phase G: Hand-over

Summarise:

- what was built;
- which data sources work;
- known gaps and limitations;
- how to trigger each mode;
- the expected scale of a full run.

Remind me to **restart Claude Code** so newly created agents and skills are picked up. Commit everything.

---

## 11. Quality bar and don'ts

**Quality bar**
- Prefer a few reliable data sources over many flaky ones.
- If something in this document is infeasible or wrong, tell me plainly and propose an alternative. Don't silently deviate.

**Don'ts**
- No hard-coded "good stock" rules, composite scores or rankings in code.
- No fabricated or placeholder financial data outside clearly labelled test fixtures.
- No order placement, ever. No write scopes on any broker API.
- No bypassing anti-bot protections, CAPTCHAs or logins.
- No numbers from model memory in any run output.
- No backtesting of LLM picks on historical dates.
- No forced picks to fill a quota.
