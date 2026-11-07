# Output schemas: every file a run writes

Read the section for the file you are about to write, and follow it exactly. Other agents and the ledger code read these files by path and by field name: a renamed field or a moved file breaks the run.

## Run folder

`run_id` = `YYYY-MM-DD-<short-slug>` (the date is the information cutoff), e.g. `2026-10-15-dhanteras`. The main session creates `runs/<run_id>/` in Phase 0; agents may only write inside an existing run folder.

| Path under `runs/<run_id>/` | Written by | Read by |
|---|---|---|
| `mandate.yaml` | main session (Phase 0: the mandate as confirmed for this run) | all agents |
| `lessons_applied.md` | main session (Phase 0) | main session |
| `market_view.md` | market-strategist | main session, hunters, analysts |
| `market/` | market-strategist (optional working files, e.g. tool output saved with `--out`) | market-strategist |
| `hunters/<lens_slug>.md`, `hunters/<lens_slug>.json` | hunter (one pair per lens) | main session |
| `candidates.json` | main session (Phase 2; **cohort D**) | ledger |
| `shortlist.md` | main session (Phase 2) | user |
| `dossiers/<SYMBOL>.md` | company-analyst | red-team, main session |
| `dossiers/<SYMBOL>.json` | company-analyst (**cohort B**) | red-team, main session, ledger |
| `dossiers/<SYMBOL>.conviction.json` | company-analyst | main session only (red team is blocked from it) |
| `dossiers/work/<SYMBOL>/` | company-analyst (optional working files) | company-analyst |
| `redteam/<SYMBOL>.md`, `redteam/<SYMBOL>.json` | red-team (**cohort C** = verdict `killed`) | main session, ledger |
| `redteam/work/<SYMBOL>/` | red-team (optional working files) | red-team |
| `dossiers/round1/`, `redteam/round1/` | main session: copies of the first dossier and red-team files before a re-analysis | user, post-mortem |
| `portfolio_holdings.json` | main session (input to `compute portfolio --holdings-file`) | tools |
| `portfolio.md` | main session (Phase 5) | user |
| `final_report.md` | main session (Phase 5-6) | user |
| `freeze_input.json` | main session (Phase 7, after approval) | `ledger freeze` |
| `reviews/<YYYY-MM-DD>.md` | main session (review mode) | user, post-mortem |

`SYMBOL` is the NSE symbol in upper case exactly as `data resolve` returns it (`entity.nse_symbol`). `lens_slug` is short lower-case, e.g. `quality`, `value`, `momentum`, `policy`, `smallmid`, `contrarian`.

Never write anywhere else. Hooks block writes outside each agent's area, and the tools' `--out FILE` must also point inside it.

## Conventions for every file

**Two kinds of numbers.**
- *Facts* (anything fetched or computed): in JSON, a provenance object copied from the tool output, at least `{"value", "unit", "period", "as_of", "source"}` plus `source_url`, `source_doc`, `page`, `notes` when present. In markdown, the number followed by a citation.
- *Judgments* (your scenario returns, probabilities, weights, confidence): plain numbers in JSON, explained in the markdown. Never dress a judgment up as a fact or a fact as a judgment.

**Citations in markdown**, placed right after the number or claim:
- tool: `[T: compute ratios CAMS; FY26; consolidated]` (enough to re-run the command)
- document: `[D: AR FY26 p.212]`, with the document's title, URL and `doc_id` listed in Sources
- web: `[W: <outlet>, <YYYY-MM-DD>, <URL>]`
- arithmetic: `[C: compute calc "(a-b)/b*100" a=<value> b=<value>]`

**Missing values**: `null` in JSON with a reason next to it (`"notes"` or a sibling `"*_why_null"` field); "not available: <reason>" in markdown. Never zero, never a guess.

**Dates** are ISO `YYYY-MM-DD`; fiscal periods use FY26 / Q2FY27; money is INR crore unless labelled; per-share values in INR.

The JSON schemas below use JSON Schema notation. `ProvNum` is defined once:

```json
{"$defs": {"ProvNum": {
  "type": "object",
  "required": ["value", "unit", "source"],
  "properties": {
    "value": {"type": ["number", "null"]}, "unit": {"type": "string"},
    "period": {"type": ["string", "null"]}, "as_of": {"type": ["string", "null"]},
    "source": {"type": "string"}, "source_url": {"type": ["string", "null"]},
    "source_doc": {"type": ["string", "null"]}, "page": {"type": ["integer", "null"]},
    "notes": {"type": ["string", "null"]}, "label": {"type": "string", "description": "what this number is, added by you"}
  }}}}
```

`Identity` (copied from `data resolve`): `{"isin": str, "nse_symbol": str, "bse_code": str|null, "legal_name": str}`, all required except `bse_code`.

---

## market_view.md (market-strategist)

```markdown
# Market view: <run_id>
Information cutoff: <YYYY-MM-DD>. Horizon: <n> months. Benchmark: Nifty 500 TRI.

## Summary (ten lines at most)
<the ten-line summary the main session shows the user>

## 1. Valuation versus history and base rates
- Nifty 500 and Nifty 50 P/E, P/B, dividend yield today, and percentile vs history [T: data index history ...]
- Forward-return base rates from similar starting valuations: mean, median, p10-p90, share positive, n_obs, n_independent, 95% CI [T: compute base_rates --index "NIFTY 500" --horizon <n>]
- The overlapping-window warning, and the 31-Mar-2021 P/E methodology break (method used)

## 2. Earnings cycle
## 3. Rates and liquidity
RBI policy rate, 10-year G-sec yield, INR/USD with as-on dates [T: data macro]; CPI and crude from dated official releases [W: ...]
## 4. Flows: domestic (SIP, DII) versus FII
## 5. Policy and event calendar within the horizon
| Date or window | Event | Why it matters |
## 6. Consensus, crowded and hated areas
Sector index valuations [T: data index snapshot]; dated sources for positioning
## 7. The strategist's view
View, confidence (low/medium/high) and what would change it
## 8. Implications for hunting
Lenses that look most promising now, and areas to be careful in, with reasons
## Sources
```

## hunters/<lens_slug>.md and .json (hunter)

Markdown: lens, method (what you searched and why, which screens with which parameters), then one block per candidate with the four required parts (why it fits the lens, why the market might be mispricing it, why it might already be priced in, key data points with citations), then names considered and rejected with one-line reasons. 8-15 candidates; fewer is acceptable if the lens is barren, and say so.

JSON:
```json
{"type": "object",
 "required": ["run_id", "lens", "lens_slug", "as_of", "method", "candidates"],
 "properties": {
  "run_id": {"type": "string"}, "lens": {"type": "string"}, "lens_slug": {"type": "string"},
  "as_of": {"type": "string"},
  "method": {"type": "array", "items": {"type": "object", "required": ["step", "why"],
             "properties": {"step": {"type": "string", "description": "command or search used"}, "why": {"type": "string"}}}},
  "candidates": {"type": "array", "items": {"type": "object",
    "required": ["symbol", "isin", "legal_name", "why_fits_lens", "why_mispriced", "why_priced_in", "key_data"],
    "properties": {
      "symbol": {"type": "string"}, "isin": {"type": "string"}, "legal_name": {"type": "string"},
      "why_fits_lens": {"type": "string"}, "why_mispriced": {"type": "string"}, "why_priced_in": {"type": "string"},
      "key_data": {"type": "array", "items": {"$ref": "#/$defs/ProvNum"}},
      "liquidity_adv_20d": {"$ref": "#/$defs/ProvNum"},
      "concerns": {"type": "string"}}}},
  "considered_and_rejected": {"type": "array", "items": {"type": "object",
    "properties": {"symbol": {"type": "string"}, "reason": {"type": "string"}}}}}}
```

## candidates.json and shortlist.md (main session, Phase 2)

`candidates.json` is cohort D: every de-duplicated hunter candidate that passed the mandate's hard exclusions. The ledger reads the `candidates` key and takes each item's `symbol`.

```json
{"type": "object", "required": ["run_id", "as_of", "candidates"],
 "properties": {
  "run_id": {"type": "string"}, "as_of": {"type": "string"},
  "candidates": {"type": "array", "items": {"type": "object", "required": ["symbol", "isin", "lenses", "shortlisted"],
    "properties": {"symbol": {"type": "string"}, "isin": {"type": "string"}, "legal_name": {"type": "string"},
                   "lenses": {"type": "array", "items": {"type": "string"}, "description": "lens slugs that found it"},
                   "shortlisted": {"type": "boolean"}, "reason": {"type": "string", "description": "why kept or dropped"}}}},
  "excluded_by_mandate": {"type": "array", "items": {"type": "object",
    "properties": {"symbol": {"type": "string"}, "rule": {"type": "string", "description": "the mandate field that excludes it"}}}}}}
```

`shortlist.md`: the 15-25 names for deep dives in a table (`symbol | legal name | lenses | why selected`), names found by more than one lens, the dropped names with reasons, and the estimated number of subagent runs for Phases 3-4.

## dossiers/<SYMBOL>.md (company-analyst)

Use these headings in this order. Every number carries a citation.

```markdown
# <SYMBOL>: <legal name>
Run: <run_id>. Information cutoff: <YYYY-MM-DD>. Basis: consolidated (unless stated). Status: complete | partial (<why>)

## 1. Identity and liquidity
| ISIN | NSE symbol | BSE code | Legal name | Industry | Board/series | Index memberships |   [T: data resolve <SYM>]
Liquidity: ADV 20d and 60d, median traded value 20d, delivery % [T: compute technicals <SYM>]; versus the mandate floor.

## 2. What the business does and how it makes money
Segments, revenue mix, customers, pricing power; segment numbers with page citations.

## 3. Industry structure, competitive position, moat
Market share, competitors, barriers to entry, or why there is no moat.

## 4. Financial history
Tables from tools with provenance: revenue, EBITDA, PAT (owners), margins, ROE, ROCE, debt/equity, FCF, restated EPS; quarterly table for the last 8 quarters. State years missing from XBRL and where older years came from.

## 5. Earnings quality
OCF/PAT, OCF/EBITDA, working-capital days and their trend, other income share, exceptional items, effective tax rate, dilution.

## 6. Governance and red flags
The 17-row table from red-flags-india.md: `| # | Item | Mark | Evidence | What it means here |`, then a short paragraph.

## 7. Management
Capital-allocation record; guidance versus delivery table `| Date said | Source (doc, page) | Promise | Outcome | Source |`; promoter behaviour.

## 8. Valuation
Multiples vs own history and vs the peers you chose (with why each peer); reverse DCF (ke and how you set it, implied growth, the grids in words, terminal-value share); your own view of plausible growth, with reasoning. Sector method per valuation-guide.md.

## 9. Catalysts and dated events within the horizon
| Date or window | Event | Source | Expected effect |   [T: data events <SYM>]

## 10. Technical and entry context
Trend vs 50/200 DMA, 52-week range, 3/6/12m relative strength vs Nifty 500 TRI, volatility, max drawdown [T: compute technicals <SYM>].

## 11. Scenarios
For bear, base and bull: drivers, evidence, horizon total return % (computed with compute calc, inputs cited) and return range. Ranges tile the number line: bear [null, x), base [x, y), bull [y, null].
Probabilities, expected value and probability of beating the benchmark: in the conviction file (withheld from the red team).

## 12. Variant perception
What this analysis believes that the market does not, the evidence, and the strongest reason it might be wrong.

## 13. Kill criteria
Specific, observable, dated conditions that would invalidate the thesis: `| Criterion | How to observe it (source) | Check by (date) |`. Thesis in three sentences right above the table.

## 14. Open questions and data gaps
Including anything not read and any depth you could not reach for lack of context or time.

## 15. Sources
Every document (title, period, URL, doc_id, pages used), every web item (outlet, date, URL), every tool command run.

## Reading log
| Item | Status (read / partly read / not obtainable) | Document and pages | Notes |
Rows: latest annual report (business, MD&A, RPT note, contingent liabilities, auditor's report); last 4-8 quarterly results; last 2-4 concall transcripts; latest investor presentation; shareholding trend; credit-rating actions; exchange announcements of the last 12 months.

## Corrections log
| What | Old value | New value | Cause | Source of the new value |
```

## dossiers/<SYMBOL>.json (company-analyst)

The machine summary. The ledger reads `identity.nse_symbol` for cohort B; the red team verifies `key_numbers`.

```json
{"type": "object",
 "required": ["run_id", "as_of", "identity", "basis", "status", "thesis", "key_numbers", "scenarios", "kill_criteria", "review_dates", "red_flags", "reading_log"],
 "properties": {
  "run_id": {"type": "string"}, "as_of": {"type": "string", "description": "information cutoff"},
  "identity": {"$ref": "Identity"},
  "basis": {"enum": ["consolidated", "standalone"]},
  "status": {"enum": ["complete", "partial"]}, "status_note": {"type": "string"},
  "sector": {"type": "string"},
  "thesis": {"type": "string", "description": "three sentences"},
  "key_numbers": {"type": "array", "minItems": 8, "maxItems": 12, "description": "the most decision-relevant facts, each with label",
                  "items": {"$ref": "#/$defs/ProvNum"}},
  "liquidity": {"type": "object", "properties": {"adv_20d": {"$ref": "#/$defs/ProvNum"}, "median_value_20d": {"$ref": "#/$defs/ProvNum"}}},
  "valuation": {"type": "object", "description": "copied from compute valuation / reverse_dcf",
    "properties": {"pe": {"$ref": "#/$defs/ProvNum"}, "pb": {"$ref": "#/$defs/ProvNum"}, "ev_ebitda": {"$ref": "#/$defs/ProvNum"},
                   "fcf_yield_pct": {"$ref": "#/$defs/ProvNum"}, "pe_percentile_own_5y": {"$ref": "#/$defs/ProvNum"},
                   "implied_growth": {"$ref": "#/$defs/ProvNum"}, "ke_used": {"$ref": "#/$defs/ProvNum"}}},
  "scenarios": {"type": "array", "minItems": 3, "maxItems": 3, "description": "NO probabilities here",
    "items": {"type": "object", "required": ["name", "drivers", "return_pct", "return_range_pct"],
      "properties": {"name": {"enum": ["bear", "base", "bull"]}, "drivers": {"type": "string"},
                     "return_pct": {"type": "number", "description": "judgment: gross total return over the horizon, %"},
                     "return_range_pct": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": ["number", "null"]}}}}},
  "variant_perception": {"type": "string"},
  "kill_criteria": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["criterion", "observe", "by"],
    "properties": {"criterion": {"type": "string"}, "observe": {"type": "string", "description": "source or tool to check"},
                   "by": {"type": "string", "description": "YYYY-MM-DD"}}}},
  "review_dates": {"type": "array", "items": {"type": "string", "description": "YYYY-MM-DD, e.g. after each results date"}},
  "catalysts": {"type": "array", "items": {"type": "object", "properties": {"date": {"type": "string"}, "event": {"type": "string"}}}},
  "red_flags": {"type": "array", "items": {"type": "object", "required": ["item", "mark", "evidence"],
    "properties": {"item": {"type": "string"}, "mark": {"enum": ["pass", "flag", "unknown"]}, "evidence": {"type": "string"}}}},
  "reading_log": {"type": "array", "items": {"type": "object", "required": ["item", "status"],
    "properties": {"item": {"type": "string"}, "status": {"enum": ["read", "partly read", "not obtainable"]},
                   "doc": {"type": "string"}, "notes": {"type": "string"}}}},
  "data_gaps": {"type": "array", "items": {"type": "string"}},
  "corrections": {"type": "array", "items": {"type": "object"}}}}
```

## dossiers/<SYMBOL>.conviction.json (company-analyst)

Kept apart so the red team judges the evidence, not the analyst's confidence. Scenario names, returns and ranges must equal those in `<SYMBOL>.json`; this file adds the probabilities.

```json
{"type": "object",
 "required": ["run_id", "symbol", "isin", "as_of", "horizon_months", "scenarios", "expected_return_pct", "p_beat_benchmark", "confidence"],
 "properties": {
  "run_id": {"type": "string"}, "symbol": {"type": "string"}, "isin": {"type": "string"}, "as_of": {"type": "string"},
  "horizon_months": {"type": "integer"},
  "scenarios": {"type": "array", "minItems": 3, "maxItems": 3, "description": "probabilities sum to 1 (check with compute calc)",
    "items": {"type": "object", "required": ["name", "probability", "return_pct", "return_range_pct"],
      "properties": {"name": {"enum": ["bear", "base", "bull"]}, "probability": {"type": "number", "minimum": 0, "maximum": 1},
                     "return_pct": {"type": "number"},
                     "return_range_pct": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": ["number", "null"]}}}}},
  "expected_return_pct": {"$ref": "#/$defs/ProvNum", "description": "the compute calc output for sum(p_k * return_k)"},
  "p_beat_benchmark": {"type": "number", "minimum": 0, "maximum": 1,
                       "description": "probability the stock's total return beats Nifty 500 TRI over the horizon"},
  "benchmark_context": {"type": "string", "description": "what compute base_rates says the benchmark may do, with n"},
  "confidence": {"enum": ["low", "medium", "high"]},
  "confidence_reasons": {"type": "string"},
  "what_would_change_my_mind": {"type": "string"}}}
```

## redteam/<SYMBOL>.md and .json (red-team)

```markdown
# Red team: <SYMBOL> (<legal name>), round <1|2>
Run: <run_id>. Date: <YYYY-MM-DD>. Verdict: survives | weakened | killed

## Verdict and reasons
## 1. Verification
Identity check (ISIN, legal name vs data resolve); period alignment; units and basis.
| # | Number (label) | Dossier value and citation | Re-fetched value and command | Difference [C: compute calc] | Material? |
List every discrepancy with its size. Say whether the dossier should go back for re-analysis.
## 2. Bear case (as a short-seller would write it)
## 3. What the bull case ignores or underweights
## 4. Is the variant perception really non-consensus? (evidence of what consensus believes, dated)
## 5. Are the kill criteria real or decorative? (observable? dated? would they fire before the damage is done?)
## 6. Depth and reading-log gaps
## Sources
```

The ledger reads `verdict`; only `killed` puts the name in cohort C.

```json
{"type": "object",
 "required": ["run_id", "as_of", "round", "identity", "verdict", "verdict_reasons", "verification", "send_back"],
 "properties": {
  "run_id": {"type": "string"}, "as_of": {"type": "string"}, "round": {"enum": [1, 2]},
  "identity": {"$ref": "Identity"},
  "verdict": {"enum": ["survives", "weakened", "killed"]},
  "verdict_reasons": {"type": "array", "items": {"type": "string"}},
  "identity_check": {"type": "string", "description": "ok, or the mismatch"},
  "verification": {"type": "array", "minItems": 8, "items": {"type": "object",
    "required": ["label", "dossier_value", "refetched", "material"],
    "properties": {"label": {"type": "string"}, "dossier_value": {"description": "as written in the dossier"},
                   "refetched": {"$ref": "#/$defs/ProvNum"}, "command": {"type": "string"},
                   "difference_pct": {"$ref": "#/$defs/ProvNum"}, "material": {"type": "boolean"}, "note": {"type": "string"}}}},
  "send_back": {"type": "boolean", "description": "true if material numerical discrepancies need a fresh analyst"},
  "bear_case": {"type": "string"},
  "ignored_by_bull": {"type": "array", "items": {"type": "string"}},
  "variant_perception_test": {"type": "object", "properties": {"assessment": {"enum": ["non-consensus", "consensus", "unclear"]}, "why": {"type": "string"}}},
  "kill_criteria_test": {"type": "array", "items": {"type": "object",
    "properties": {"criterion": {"type": "string"}, "assessment": {"enum": ["real", "decorative"]}, "why": {"type": "string"}}}}}}
```

**Re-analysis (round 2).** Before sending a dossier back, the main session copies `dossiers/<SYMBOL>.md/.json/.conviction.json` and `redteam/<SYMBOL>.md/.json` into `dossiers/round1/` and `redteam/round1/`. The fresh analyst then overwrites `dossiers/<SYMBOL>.*`, and the round-2 red team overwrites `redteam/<SYMBOL>.*` with `"round": 2`. The files at the top level are always the latest; the ledger never reads the `round1/` folders.

## portfolio_holdings.json, portfolio.md (main session, Phase 5)

`portfolio_holdings.json`: `{"holdings": [{"symbol": "SYM", "weight": 0.08}, ...]}`, weights as fractions of capital; cash = 1 − sum. Run `compute portfolio --holdings-file runs/<run_id>/portfolio_holdings.json`.

```markdown
# Portfolio: <run_id>
## Holdings
| Symbol | Weight | Cash weight | Sizing rationale (expected value, downside, conviction, liquidity) | Red-team verdict |
## Mandate checks [T: compute portfolio ...]
Max weight, max sector weight, liquidity (days to exit at the participation rate), positions count; any breach and its fix.
## Exposures and hidden common bets
Sector, size, beta, momentum, value; correlation clusters; shared macro drivers (rates, commodity, government capex, INR).
## Stress
Beta-implied loss in a -20% market; compare with the mandate drawdown tolerance.
## Costs and tax
Round-trip costs and tax by holding period [T: compute costs_tax ...]
## Versus the alternatives
Why this beats "buy the Nifty 500" and "hold cash", or why fewer names / no names is the recommendation.
```

## final_report.md (main session, Phase 6)

```markdown
# Research report: <run_id>
Information cutoff <YYYY-MM-DD>. Horizon <n> months. Benchmark Nifty 500 TRI.
## Summary table
| Pick | Weight | One-line thesis | P(beat benchmark) | Main risk | Kill criteria |
## Market view in brief
## What was rejected and why (including red-team kills)
## Where the system is least confident; data gaps
## Process notes (agents run, failures caught by verification, re-analyses)
This is research for your decision, not investment advice.
```

## freeze_input.json (main session, Phase 7, only after the user's explicit approval)

Read by `uv run python -m tools ledger freeze <run_id> --approved "<who/when>"` (dry runs add `--ledger-dir ledger/test`). Validation rejects the freeze if any rule fails.

```json
{"type": "object", "required": ["model_id", "picks"],
 "properties": {
  "model_id": {"type": "string", "description": "the model that ran the analysis"},
  "horizon_months": {"type": "integer", "description": "optional; default from config/mandate.yaml"},
  "picks": {"type": "array", "description": "may be empty: the index or cash is a valid outcome",
    "items": {"type": "object", "required": ["symbol", "weight", "thesis", "scenarios", "p_beat_benchmark", "kill_criteria"],
      "properties": {
        "symbol": {"type": "string"},
        "weight": {"type": "number", "exclusiveMinimum": 0, "description": "fraction of capital; all weights sum to <= 1"},
        "thesis": {"type": "string", "description": "three sentences"},
        "scenarios": {"type": "array", "description": "from the conviction file; probabilities sum to 1 +- 0.01",
          "items": {"type": "object", "required": ["name", "probability", "return_pct"],
            "properties": {"name": {"type": "string"}, "probability": {"type": "number"}, "return_pct": {"type": "number"},
                           "return_range_pct": {"type": "array", "items": {"type": ["number", "null"]}}}}},
        "p_beat_benchmark": {"type": "number", "minimum": 0, "maximum": 1},
        "kill_criteria": {"type": "array", "minItems": 1, "items": {"type": "string",
          "description": "one string per criterion: '<criterion> (observe: <source>; by <YYYY-MM-DD>)'"}},
        "review_dates": {"type": "array", "items": {"type": "string", "description": "YYYY-MM-DD"}}}}},
  "cohorts": {"type": "object", "description": "optional; omit to let the ledger read the run folder",
    "properties": {"B": {"type": "array", "items": {"type": "string"}}, "C": {"type": "array", "items": {"type": "string"}},
                   "D": {"type": "array", "items": {"type": "string"}}}}}}
```

Rules the validator enforces: weights > 0 and summing to at most 1; no duplicate symbols; scenario probabilities sum to 1 within 0.01; `p_beat_benchmark` in [0, 1]; thesis and at least one kill criterion per pick; review dates parse as dates. Without `cohorts`, B = symbols of `dossiers/*.json` (conviction files skipped), C = `redteam/*.json` with verdict `killed`, D = `candidates.json`. Leave cohorts out unless the folder is incomplete.

## reviews/<YYYY-MM-DD>.md (main session, review mode)

```markdown
# Review <YYYY-MM-DD>: run <run_id>
Ledger output: [T: ledger review <run_id>]; marks: [T: ledger mark <run_id>]
## <SYMBOL>
| Kill criterion | Fired / not fired / unclear | Evidence (announcement, date, page) |
Recommendation: hold | trim | exit | re-underwrite, with reasons. The user decides.
```

## Ledger records (written only by the ledger commands; for reference)

`ledger/picks.jsonl` (or `ledger/test/picks.jsonl`) is append-only; numbers in it are provenance objects. `record_type` is one of:
- `run` (`<run_id>:run`): frozen_at, model_id, approval, horizon, benchmark level at freeze, cohorts A-E with members, entry rule;
- `pick` (`<run_id>:<ISIN>`): ISIN, symbol, legal name, weight, reference price, thesis, scenarios, p_beat_benchmark, kill criteria, review dates;
- `review` (`<run_id>:review:<date>`): window and the announcements listed against kill criteria;
- `postmortem` (`<run_id>:postmortem`, interim `<run_id>:postmortem-interim-<date>`);
- `correction` (`<record_id>:correctionN`): `corrects`, `changes`, `reason`; readers apply it, the original line is never edited (`ledger correct`).

Post-mortem templates go to `ledger/postmortems/<run_id>.md` (interim: `<run_id>.interim-<date>.md`). See `evaluation.md`.
