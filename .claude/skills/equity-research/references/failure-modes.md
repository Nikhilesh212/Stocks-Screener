# Failure modes and countermeasures

Read this before you fetch or write anything. It applies to every agent in an equity-research run: market-strategist, hunter, company-analyst, red-team and the main session.

## Why this file exists

A live, ten-month, out-of-sample study by Spain's securities regulator (CNMV Working Paper 96, March 2026) had LLMs pick stocks. Plain "what should I buy" prompts produced excess returns indistinguishable from zero. Structured prompts, iterative error correction and grounding in regulatory filings each improved results. The errors the models made fell into the ten patterns below. Each pattern has a countermeasure built into our tools. Use it every time, not only when something looks wrong: these errors are invisible to the one making them.

## The ground rules all countermeasures rest on

- **Code fetches facts and computes numbers; you decide what matters.** Every number you write comes from a tool output (a provenance object) or from a document you cite with its page. Nothing from memory, not even "well-known" figures such as the repo rate or a company's market cap.
- **The tools CLI.** Run `uv run python -m tools <group> <command> ...`. Output is JSON on stdout. Check `"status"` first: `ok` or `resolved` means usable; `entity_error`, `source_error`, `missing_input`, `input_error` mean the number does not exist for you. Run `uv run python -m tools <group> <command> --help` for exact options. Never guess an option name.
- **Provenance object.** Every tool number is `{value, unit, period, as_of, source, source_url, source_doc, page, retrieved_at, notes}`. Tables carry one provenance block for all rows (`kind: "table"`, `units`, `source`). Carry `unit`, `period` and `source` into your writing. When `value` is `null`, `notes` says why. Write "not available: <reason>" and never substitute zero or an estimate.
- **Information cutoff.** The run's cutoff is the run date (the `YYYY-MM-DD` at the start of the run_id). Never use anything published after it. Date every news item and every document you cite.

## The ten failure modes

### 1. Entity mismatch: data for the wrong company with a similar name

Examples: Bajaj Finance vs Bajaj Finserv; Tata Motors vs Tata Motors DVR; a subsidiary's annual report instead of the parent's; a demerged entity's old history.

Countermeasures:
- Start with `uv run python -m tools data resolve <symbol|ISIN|name>`. Use it only when `status` is `resolved`. If it returns `candidates`, it refused to guess: choose by ISIN, never by the closest-looking name.
- Copy the identity block from `resolve` (`isin`, `nse_symbol`, `bse_code`, `legal_name`) to the top of your output. Every other tool echoes `identity.isin` and `identity.legal_name`. Compare them with your identity block **every time** you read a tool output.
- An ISIN can change on a face-value split (the first 9 characters stay the same issuer). If an older document shows a different ISIN, check the first 9 characters before treating it as another company.
- For PDFs and web pages, confirm the legal name (and CIN or ISIN where shown) on the first page or masthead before taking any number from it. For news, check that the article is about the listed entity, not a group company or an unlisted subsidiary.

### 2. Fabricated figures: a number that appears in no source

Countermeasures:
- Every number you write has one of: a tool command whose output contains it, or a document citation `doc_id`/title, period and page (`data filings search` and `data filings pages` return page numbers).
- If you cannot find a number, say so: "FY26 order book: not disclosed in the AR, Q4 presentation or Q4 call (searched 'order book|order inflow')".
- Your own estimates are allowed only when labelled as estimates, with the inputs cited and the arithmetic done with `compute calc`.
- Numbers in these reference files are illustrations, never data. Do not copy them.

### 3. Temporal mismatch: mixing periods

Examples: today's price with last year's EPS called "current P/E"; FY25 margin compared with Q2FY27 revenue; an index P/E from before 31-Mar-2021 compared with one after it.

Countermeasures:
- Indian fiscal notation: FY26 = 1-Apr-2025 to 31-Mar-2026; Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar, so Q2FY27 = Jul-Sep 2026. Write periods in this notation.
- Read each number's `period` and `as_of`. Put the period next to every number in tables and text.
- Use `compute valuation` for multiples. It pairs each month's price with only the results that were public by then (quarter end + 45 days, Q4 + 60 days). Do not recompute multiples by hand from mismatched inputs.
- Index P/E changed method on 31-Mar-2021 (standalone to consolidated earnings, a jump of about 20% in implied earnings). `compute base_rates` splices it by default (`--pe-method spliced`). Never compare raw index P/E across that date.
- Macro data is revised and released with a lag: cite the release date as well as the reference period (`data macro` returns as-on dates).

### 4. Table misreading: the wrong row or column

Countermeasures:
- Prefer exchange XBRL (`data financials`) to PDF tables. It is machine-tagged, in INR crore, and labelled by period and basis.
- When you must read a PDF table (segment data, order book, bank NIM/CASA/credit cost), use `data filings pages <SYM> <doc_id> <range>` and read the column headers and the unit line again before taking the value. Note the page.
- Use the `crosschecks` table in `data financials` output (sum of four quarters vs the FY figure; `flag` above 2%) and the `restatements_or_conflicts` table. Explain any flag in your notes instead of ignoring it.
- Sanity-check one figure per table against a second source where one exists (e.g. revenue in the results PDF vs XBRL).

### 5. Unit and currency confusion

Countermeasures:
- Tools normalise money to INR crore and per-share values to INR (see each number's `unit`). Documents do not: annual reports use INR crore, INR lakh or INR million; some IT and pharma companies report in USD.
- Conversions: 1 crore = 100 lakh = 10 million; 1 billion = 100 crore. Do every conversion with `compute calc` and state both the source unit and the result unit.
- Percent vs percentage points: a margin moving from 10% to 12% is +2 percentage points (pp), or +20% relative. Say which.
- **Standalone vs consolidated.** Tool outputs carry `basis`. Consolidated is the default. Never put standalone and consolidated figures in one table or ratio. Banks: asset quality (GNPA, NNPA, PCR) is filed only on the standalone basis, so run `compute ratios <SYM> --basis standalone` for it and label it.
- Shares and EPS across bonuses and splits: filed EPS is not restated for later corporate actions. Use `eps_restated` and `shares_restated_crore` from `compute ratios`. It refuses EPS CAGR on filed EPS when the share count moved more than 20%. Respect that.

### 6. Aggregation and arithmetic errors

Examples: a weighted average outside the range of its inputs; scenario probabilities summing to 1.1; a CAGR computed over the wrong number of years.

Countermeasures:
- **Every** derived number goes through `uv run python -m tools compute calc "<expr>" --var name=value ... --unit <unit> --label "<what>"`. That includes sums, differences, averages, growth rates, per-share figures, probability-weighted returns and portfolio weights. Functions available: abs, avg, cagr, exp, ln, log, log10, max, min, round, sqrt, sum. Never do mental math, even for "easy" sums.
- Check that bear/base/bull probabilities sum to 1 and that their returns are ordered bear < base < bull.
- Portfolio weights and limits: `compute portfolio` reports the mandate checks (weight, sector, liquidity). Use its output, not your own sum.

### 7. Carryover: a value from a previous company or query

Countermeasures:
- Each company is analysed in its own fresh subagent. Never reuse a number from another dossier, an earlier task or an example. If you need a peer's number, fetch it for that peer with the tool and cite it.
- Before you finish each section, check that every tool output you used shows the same `identity.isin` as your identity block.
- Do not let another agent's conclusions in. Analysts never see other dossiers' conviction files, and the red team never sees the analyst's conviction file (a hook enforces this).

### 8. Failed self-correction: admitting an error but keeping the wrong number

Countermeasures:
- When you find an error, **re-fetch**: re-run the tool or re-read the page. Replace the number everywhere it appears (search your own file for the old value) and recompute everything derived from it with `compute calc`.
- Never write "this figure may be off, but..." and carry on with it. Either fix it or mark it as unknown and remove its influence on the conclusion.
- Record each correction in the dossier's corrections log: old value, new value, cause, source.

### 9. Complexity-reduction bias: some companies analysed fully, others superficially

Countermeasures:
- Company analysts work through the same mandatory reading list for every company and log each item as read, partly read or not obtainable, with the reason (see `output-schemas.md`, dossier section "Reading log").
- If your context or time runs short, say so explicitly in "Open questions and data gaps" and lower your stated confidence. A visibly incomplete dossier is acceptable; a quietly shallow one is not.
- Hunters give every candidate the same fields. The main session compares dossier depth before portfolio construction, and the red team checks the reading log.

### 10. Opaque reasoning: a conclusion nobody can reproduce

Countermeasures:
- Every claim points to its evidence: a tool command (written so it can be re-run), or a document and page, or a dated URL.
- Keep the chain explicit: fact, then inference, then conclusion. Mark inferences as yours.
- Tool outputs include `formulas`. When a ratio matters, quote the formula with the number.
- The Sources section lists every document and command used.

## India- and tool-specific traps

- **Unadjusted price gaps.** Compute commands add a `warnings` entry when a price series has an overnight gap above 25% that no corporate-action factor explains. Quote it and treat price-based numbers (returns, drawdown, multiples history) as suspect until resolved. Re-running `data prices <SYM> --years 10 --refresh` often fixes a stale cache.
- **Short price history.** Valuation percentiles need history: run `data prices <SYM> --years 10` (and for each peer) before `compute valuation`. Otherwise the percentile is labelled "shorter than 5y".
- **Financial history depth.** XBRL starts around FY18 and some years are missing. Five- and ten-year CAGRs often come back `null` with a reason. Take older years from annual reports with page citations, and never fill gaps by assumption.
- **Peers.** `compute valuation <SYM> --peers A,B` needs each peer's prices in the cache first (`data prices A`). A peer without a cache is listed with an error, not fetched.
- **Sources down.** If a tool returns `source_error`, say so and degrade gracefully. Do not retry with altered headers and do not work around blocks (the HTTP policy forbids it). CPI and crude have no working keyless source: cite dated official releases found by web search.
- **News.** WebSearch and WebFetch are allowed for news and context. Every news item needs its publication date and outlet. Prefer primary sources (exchange filings, company releases, regulator orders) over reports of them.
- **Training memory.** You may remember facts about a company. Treat them as hypotheses to verify with tools, never as data.
