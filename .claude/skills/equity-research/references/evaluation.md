# Evaluation: how a run is scored, and why only forward evaluation counts

Read this before you state any probability (company-analyst conviction file, main session portfolio), before review or post-mortem work, and whenever you are tempted to force a pick.

## The objective

### Primary objective

Maximise expected excess return over the **Nifty 500 Total Return Index** across the mandate horizon (default 12 months or more). Measure it net of estimated transaction costs and capital-gains tax.

### Constraints

These come from `config/mandate.yaml` (as confirmed for the run in `runs/<run_id>/mandate.yaml`):
- portfolio drawdown tolerance (`max_drawdown_tolerance`);
- maximum weight per position (`max_weight`);
- maximum weight per sector (`max_sector_weight`);
- liquidity: each position must be exitable within `liquidity.max_days_to_exit` days at `liquidity.participation_rate` of average daily traded value, with ADV at least `liquidity.min_adv_inr_crore`;
- universe and exclusions (`universe`, `exclusions`, `avoid_themes`; equity cash only, no F&O, leverage or shorting).

### Calibration

Every pick carries explicit probabilities: the probability of beating the benchmark over the horizon, and bear/base/bull scenario probabilities. Post-mortems score these with a Brier score and a calibration table. Overconfidence is penalised, not rewarded.

### Legitimate outcomes

Fewer picks, holding cash, or "buy the index instead" are all acceptable answers. A forced pick that loses is worse than no pick. A system that must always find winners will invent them.

### Why this is not "maximise profit at any risk"

Taken literally, that objective rewards maximum variance: concentrated small-cap momentum bets that look brilliant in a good year and blow up in a bad one. With one run per occasion, luck and skill become indistinguishable. Excess return under constraints, plus calibration, is what lets the user learn whether the system has an edge.

## Why only forward evaluation is valid

- **Backtests of LLM picks are contaminated.** The model's training data contains what happened after any historical date. "What would you have picked in 2022?" is answered with knowledge of 2023-2026, so it measures memory, not judgment. Never backtest LLM picks on historical dates, and never cite such a backtest as evidence.
- **Live records are noisy.** Live LLM trading benchmarks show most model-seasons do not finish profitable, and rank in one period does not predict rank in the next. Longer and broader tests shrink reported LLM advantages. One good run proves nothing; neither does one bad run.
- **So evidence accumulates only in the ledger.** Picks are frozen with a timestamp before the outcome is known, then tracked against the index. Only many frozen runs, scored the same way, can show an edge.
- What code *can* backtest honestly is mechanical market history with no model judgment in it, such as `compute base_rates` (index forward returns from similar starting valuations). Use it as context, with its stated `n_independent` and confidence intervals, and remember that overlapping windows inflate the apparent sample size.

## How the ledger implements it

All commands are `uv run python -m tools ledger ...`. They write only to `ledger/` (append-only). Dry runs add `--ledger-dir ledger/test` (gitignored). Subagents never run ledger commands; a hook blocks them.

| Command | When | What it does |
|---|---|---|
| `freeze <run_id> --approved "<who, when>"` | Phase 7, only after the user's explicit approval in chat; pass the approval text | Validates `runs/<run_id>/freeze_input.json` (see `output-schemas.md`), appends one `run` record and one `pick` record per pick, with cohorts A-E. Refuses a second freeze of the same run. |
| `mark <run_id> [--as-of D] [--no-fetch]` | any time | Gross total return of each pick and each cohort vs Nifty 500 TRI since entry, and the comparisons A-B, C-A, B-D, D-E, A-E. Writes nothing. |
| `review <run_id> [--as-of D]` | after results or big news | Lists announcements since the last review next to each pick's kill criteria and appends a `review` record. Claude judges whether each criterion fired. |
| `postmortem <run_id> [--force] [--slab-rate R] [--surcharge S] [--as-of D] [--no-fetch]` | at horizon end (`--force` before it, labelled interim) | Net-of-cost-and-tax returns, Brier scores, calibration table, cohort comparison; writes `ledger/postmortems/<run_id>.md` for Claude to fill in. |
| `correct <record_id> --set field=JSON --reason "..."` | when a frozen record is wrong | Appends a correction; the original line is never edited. |

### Entry, returns and costs

- **Entry** is the close of the first trading session after the freeze date. The price shown at freeze is a reference only, so nobody can pick a favourable entry after the fact.
- **Returns are total returns** (dividends reinvested), from adjusted prices.
- **Cohort A** holds cash for `1 − sum(weights)`; cash earns 0. Cohorts B, C and D are equal-weight buy-and-hold. A member without prices is excluded from the cohort mean and named in the output (a survivorship risk to mention).
- **Costs and tax** (post-mortem only): round-trip costs from `config/costs.yaml` (brokerage and DP charge there are defaults to confirm once a broker is chosen; statutory rates have sources and dates). Capital-gains tax by holding period: short-term if held 12 months or less, long-term above that. Short- and long-term results are netted across picks and one annual LTCG exemption is applied at portfolio level, shown with and without the exemption. Dividend tax only with `--slab-rate`; surcharge with `--surcharge` (capped as the law caps it).
- `mark` is gross; only `postmortem` is net. Say which one you quote.

### Cohorts: which stage adds value

| Cohort | Contents | Source in the run folder |
|---|---|---|
| A | Final portfolio, as weighted (cash earns 0) | `freeze_input.json` picks |
| B | Equal weight of all deep-dived names | `dossiers/<SYMBOL>.json` |
| C | Equal weight of names the red team killed | `redteam/<SYMBOL>.json` with `"verdict": "killed"` |
| D | Equal weight of the hunters' full candidate list | `candidates.json` |
| E | Nifty 500 TRI | the benchmark |

How to read the comparisons:
- **B ≈ A**: portfolio construction adds nothing.
- **C beats A**: the red team is destroying value.
- **D ≈ B**: the deep dives add nothing.
- **D ≈ E**: hunting adds nothing.
- **A vs E**: the headline excess return.

One run's cohort gaps are mostly noise. Read them across runs, and write in each post-mortem what the gap would have to look like over several runs before it changes the process.

### Calibration scoring

**Brier score for `p_beat_benchmark`**: mean over picks of (p − outcome)², where outcome = 1 if the pick's gross total return beat the benchmark's total return over the same window, else 0. 0 is perfect; 0.25 is what always saying 0.5 scores; above 0.25 is worse than a coin. Example of why overconfidence costs: saying 0.9 and losing scores 0.81; saying 0.6 and losing scores 0.36.

**Scenario Brier score** (multi-class): for each pick, sum over bear/base/bull of (p_k − 1[scenario k realised])², averaged over picks. The realised scenario is the one whose `return_range_pct` contains the pick's gross total return over the horizon (lower bound inclusive, upper bound exclusive, `null` = open). It is computed only when every scenario of a pick has a range, so the ranges must tile the number line: bear `[null, x)`, base `[x, y)`, bull `[y, null]`.

**Calibration table**: forecasts grouped into bins 0-0.2, 0.2-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0, with the mean forecast and the observed frequency in each. A calibrated forecaster's 0.6-0.8 bin wins about 70% of the time. With few picks per run, pool runs before drawing conclusions.

What this means when you set probabilities:
- Anchor on the base rate. Index returns are driven by a minority of big winners, so a typical single stock is at least as likely to lag the index as to beat it, and costs and tax widen the gap. Start at or below 0.5 and move up only as far as the evidence carries you, and write why. The benchmark's own likely range is in `compute base_rates`.
- Probabilities near 0 or 1 need overwhelming evidence. High confidence on a stock with a "weakened" red-team verdict is a contradiction to resolve, not to ignore.
- Calibration is scored per pick. A good portfolio does not rescue badly calibrated individual probabilities.

## Review and post-mortem practice

- **Review mode**: for each pick, judge each kill criterion as fired, not fired or unclear, citing the announcement or result with its date and page. Recommend hold, trim, exit or re-underwrite; the user decides. Write `runs/<run_id>/reviews/<YYYY-MM-DD>.md`.
- **Post-mortem mode**: fill in `ledger/postmortems/<run_id>.md`. Separate **decision quality** (was the reasoning sound given what was knowable at the cutoff? were the documents read? did the red team catch real problems?) from **outcome** (what the price did). A good decision can lose and a bad one can win. Analyse calibration and the cohort comparison.
- **Lessons**: distil at most five durable lessons into `ledger/lessons.md`. Merge or replace older lessons instead of letting the file grow. A lesson is about process ("we under-weighted receivable build-up in mid-caps"), not about a stock ("avoid X").
