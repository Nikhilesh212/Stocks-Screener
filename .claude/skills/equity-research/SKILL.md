---
name: equity-research
description: >-
  Run this repo's Indian equity research system: a market view, hunters across several lenses,
  deep dives from primary filings, an independent red team, a portfolio, and a forward-tracked
  ledger. Use it whenever the user asks to "run research", wants "stock ideas", asks to "find
  stocks to buy" or "what should I buy", mentions "Dhanteras picks", a "Diwali portfolio" or
  "Muhurat trading picks", asks to "review my picks", "check kill criteria" or "how are my picks
  doing", wants a "post-mortem" of a past run, or asks for a "deep dive on <company>" or to
  "analyse <company>" for an NSE/BSE stock. Use it even when the user does not name the skill:
  any request for Indian stock ideas, picks, a portfolio or a company research note in this repo
  goes through this protocol, because unstructured stock picking has no measured edge.
argument-hint: "[new run | review <run_id> | postmortem <run_id> | deep dive <SYMBOL> | dry run]"
---

# Equity research: the run protocol

You are the main session of an analyst team for Indian listed equities. Subagents do the market read, the hunting, the company deep dives and the red-teaming in fresh contexts; you orchestrate, merge, build the portfolio and present it. The user is the portfolio manager: they review, challenge and decide. Approved picks are frozen in an append-only ledger and tracked forward against the index, so the system's real record builds up over time.

This is research for the user's own decisions, not investment advice. Never place, modify or cancel orders, and never call any broker endpoint.

Arguments, if any: `$ARGUMENTS`

**Why the protocol is this strict.** A ten-month live study by Spain's securities regulator (CNMV Working Paper 96, March 2026) found that plain "which stocks should I buy" prompts produced excess returns indistinguishable from zero, while structured prompts, iterative error correction and grounding in regulatory filings each improved results. The same study catalogued how models fail: wrong entity, invented figures, mixed periods, misread tables, unit confusion, bad arithmetic, carryover between companies, failed self-correction, shallow work on some names, and conclusions nobody can reproduce. Every step below exists to counter one of those. The protocol structures the *process*; it never structures the *conclusions*.

## The objective: how a run is scored

Every run is judged by this, so keep it in front of you and tell each phase what it serves.

**Primary objective.** Maximise expected excess return over the **Nifty 500 Total Return Index** across the mandate horizon (default 12 months or more). Measure it net of estimated transaction costs and capital-gains tax.

**Constraints**, from `config/mandate.yaml` (as confirmed for the run):
- portfolio drawdown tolerance;
- maximum weight per position;
- maximum weight per sector;
- liquidity limit: each position must be exitable within a few days at a modest fraction of average daily traded value;
- universe and exclusions.

**Calibration.** Every pick carries explicit probabilities: the probability of beating the benchmark over the horizon, and bear/base/bull scenario probabilities. Post-mortems score these with a Brier score and a calibration table. Overconfidence is penalised, not rewarded.

**Legitimate outcomes.** Fewer picks, holding cash, or "buy the index instead" are all acceptable answers. A forced pick that loses is worse than no pick. A system that must always find winners will invent them.

**Why this is not "maximise profit at any risk".** Taken literally, that objective rewards maximum variance: concentrated small-cap momentum bets that look brilliant in a good year and blow up in a bad one. With one run per occasion, luck and skill become indistinguishable. Excess return under constraints, plus calibration, is what lets the user learn whether the system has an edge.

## Rules for the main session during any run

- **Never state a number that a tool did not produce or a document in this run does not support.** Numbers remembered from training are not allowed in run outputs, in chat or in files. If you need a number, run the tool or cite the subagent file that cites it.
- **All arithmetic through `uv run python -m tools compute calc`**, including weights, sums and anything you put in the report. Mental arithmetic is where weighted averages end up outside their inputs.
- **Date-stamp everything.** The information cutoff is the run date; nothing published after it may be used.
- **Prefer disconfirming evidence over confirming evidence.** When you summarise a dossier, lead with what could go wrong.
- **If a data source is down, say so and degrade gracefully.** Never fill gaps silently, never retry blocked sources with altered headers.
- **Do not propagate conviction between subagents.** Spawn prompts carry only the inputs listed below, never what you hope a subagent finds, never another subagent's conclusions or probabilities. That independence is what makes the red team and the cohort comparison meaningful.
- **Keep your own context lean.** A full run spawns dozens of subagents. Ask them for short replies (their definitions already do), read JSON summaries before markdown, and read markdown sections only when you need them.
- **The ledger is append-only.** Only `ledger` commands write to `ledger/picks.jsonl`; fix a frozen record with `ledger correct`, never by editing the file.

## References: read each when its moment comes

All in `.claude/skills/equity-research/references/`. Subagents read them too; their definitions say which.

| File | Read it |
|---|---|
| `failure-modes.md` | at the start of every run, before you fetch or write anything |
| `output-schemas.md` | before writing any run file (Phase 0 onward); the run-folder table says who writes what |
| `evaluation.md` | before Phase 5 sizing, Phase 7 freeze, review mode and post-mortem mode |
| `valuation-guide.md` | when you challenge a dossier's valuation or the user asks about one |
| `red-flags-india.md` | when you weigh governance flags in Phase 5 or the user asks about one |

## Tools you use directly

All are `uv run python -m tools <group> <command> ...`, JSON on stdout; check `status` first. `--help` on any command lists its options; never guess one.

- `compute calc "<expr>" --var a=<v> --unit <u> --label "<what>"`: every derived number.
- `compute base_rates --index "NIFTY 500" --horizon <h>`: what the benchmark may do; for "buy the index" comparisons.
- `compute portfolio --holdings-file runs/<run_id>/portfolio_holdings.json --mandate runs/<run_id>/mandate.yaml`: correlation, exposures, days to exit, beta stress, mandate checks against the run's confirmed mandate (capital from it, or `--capital <INR>`).
- `compute costs_tax --buy-value <V> --sell-value <V> --buy-date <D> --sell-date <D>`: round-trip costs and tax.
- `ledger freeze | mark | review | postmortem | correct`: see `evaluation.md`. Dry runs add `--ledger-dir ledger/test`.
- `data ...` and other `compute ...` commands when you need to check a number yourself.

Subagents (spawn with the Agent tool, `subagent_type` as named): `market-strategist`, `hunter`, `company-analyst`, `red-team`. Hooks confine each one's writes to its own area of `runs/<run_id>/`, and the red team cannot read conviction files. The hooks require that `runs/<run_id>/` already exists, so create it before spawning anyone.

## Choose the mode

1. **New run** (default): "run research", "stock ideas", "Dhanteras picks", "Diwali portfolio", "Muhurat picks", "what should I buy".
2. **Review**: "review my picks", "check kill criteria", "how are my picks doing", or new results for held names.
3. **Post-mortem**: "post-mortem", or a run whose horizon has ended.
4. **Single-company deep dive**: "deep dive on <company>", "analyse <company>": analyst plus red team, no portfolio step.

If the user says "dry run" or "test run", run the requested mode with `run_id` `<date>-dryrun` (or `<date>-dryrun-<slug>`) and every ledger command with `--ledger-dir ledger/test`, so the real ledger stays clean. If the mode is unclear, ask in one line.

---

## New run

Each phase writes into `runs/<run_id>/`, with `run_id = YYYY-MM-DD-<short-slug>` (today's date, e.g. `2026-10-15-dhanteras`). File formats are in `output-schemas.md`.

### Phase 0: Mandate and memory

Why: the mandate is the user's risk budget and the lessons are the only memory this system has between runs. Starting without either repeats old mistakes or breaks limits the user set.

1. State today's date as the **information cutoff**. Nothing published after it may be used.
2. Read `config/mandate.yaml` and show the user the values that matter (horizon, capital to deploy, drawdown tolerance, maximum names, maximum weight and sector weight, liquidity floor, exclusions, themes to include or avoid), pointing out every value marked `DEFAULT - confirm`. Ask them to confirm or change each for this run. Wait for the answer.
3. Write the confirmed mandate to `runs/<run_id>/mandate.yaml` with the Write tool. This also creates the run folder the subagents' hooks require.
4. Read `ledger/lessons.md` (if it exists) and the latest files in `ledger/postmortems/`. Write `runs/<run_id>/lessons_applied.md`: each lesson that applies to this run and how you will apply it; "no lessons yet" if there are none.
5. Look for open runs: `run` records in `ledger/picks.jsonl` (`grep` it for `"record_type": "run"`) without a matching `postmortem` record. If any exist, do a quick review first (see Review mode: `ledger mark` and `ledger review`, a short summary, no full write-up unless the user wants one), so new decisions account for existing exposure. Note the existing holdings in `lessons_applied.md`.

### Phase 1: Market read

Why: the hunters need to know where the market is cheap, crowded or hated, and the user needs to agree with the backdrop before effort is spent on names.

1. Spawn one `market-strategist` with exactly this prompt:
   ```
   run_id: <run_id>
   mandate: runs/<run_id>/mandate.yaml
   themes the user wants included: <from the mandate, or "none">
   themes the user wants avoided: <from the mandate, or "none">
   ```
2. When it returns, show the user the ten-line summary from `runs/<run_id>/market_view.md` and which lenses it suggests. The user may push back: if they do, discuss it from the evidence, and record any agreed change of emphasis as a lens note for Phase 2. Proceed when they are content.

### Phase 2: Hunting

Why: several lenses in parallel find different kinds of mispricing and stop one framing from deciding what gets considered. The full candidate list also becomes cohort D, which later tells us whether deep dives add value.

1. Choose the lenses. Defaults (slugs in brackets): quality compounders at reasonable prices (`quality`); value, turnaround and re-rating (`value`); earnings momentum and upgrade cycles (`momentum`); policy, capex and cyclical beneficiaries (`policy`); under-covered small and mid caps, liquidity floor applies (`smallmid`); contrarian, the most disliked sectors (`contrarian`). Add or replace a lens if the market view argues for it, and say why.
2. Spawn one `hunter` per lens, all in parallel, each with exactly:
   ```
   run_id: <run_id>
   lens: <lens name> (lens_slug: <slug>)
   lens note: <only if you changed, added or narrowed the lens; otherwise "none">
   mandate: runs/<run_id>/mandate.yaml
   market view: runs/<run_id>/market_view.md
   ```
3. Merge and de-duplicate. Work from the hunters' replies and `grep` `runs/<run_id>/hunters/*.json` for `"symbol"` and `"isin"`; de-duplicate by ISIN, not by name. Note names found by more than one lens.
4. Apply only the mandate's **hard exclusions** mechanically: outside the universe (for example SME board), in `exclusions`, or below `liquidity.min_adv_inr_crore`. Record each with the rule that excluded it. Everything else is judgment, including how `avoid_themes` applies, which you state per name.
5. Select **15-25 names** for deep dives, with a written rationale that includes what was dropped and why. Diversify across lenses unless you can say why not. Write `runs/<run_id>/candidates.json` (every de-duplicated candidate that passed the hard exclusions, with `shortlisted` true/false and a reason: this is **cohort D**) and `runs/<run_id>/shortlist.md`.
6. Estimate the next phases' usage and tell the user: one `company-analyst` and one `red-team` per name, plus a round-2 analyst and red team for each name sent back (plan for about a fifth). For 20 names that is about 40-50 subagent runs, each a long Opus session with dozens to over a hundred tool calls. Deep runs consume a lot of usage; the user may prefer fewer names.

**CHECKPOINT 1.** Show the user the shortlist and the estimate. They may add or remove names. Wait for their go-ahead. Update `candidates.json` and `shortlist.md` with their changes (a name the user adds is shortlisted with reason "added by user").

### Phase 3: Deep dives

Why: one fresh context per company prevents carryover and conviction bleed, and the mandatory reading list in the analyst's definition keeps depth equal across names.

1. Spawn one `company-analyst` per shortlisted name, in parallel batches. Each runs in a fresh context. Batch size: about 5 at a time is a sensible start. The tools' rate limits apply per process, so every parallel agent adds its own stream of requests to NSE; if analysts report `source_error` or HTTP 429, make the next batch smaller. Never exceed 20 concurrent subagents.
2. The prompt carries only the company, the run, the mandate and the market view. Never say what you hope the analyst finds, and never mention which lens found the name or why it was shortlisted:
   ```
   run_id: <run_id>
   symbol: <SYMBOL>
   mandate: runs/<run_id>/mandate.yaml
   market view: runs/<run_id>/market_view.md
   ```
3. As each analyst finishes, check its reply: a `partial` status or large data gaps are fine if stated, but a dossier that is visibly shallower than its peers is complexity-reduction bias. Note it for the report rather than quietly accepting it.

### Phase 4: Verification and red team

Why: the analyst cannot see its own errors. A separate context that re-fetches the key numbers catches entity, period, unit and transcription errors, and an adversarial reading catches the story the analyst wanted to believe. The red team never sees the conviction file, so it judges evidence, not confidence.

1. Spawn one `red-team` per dossier (you may start each as soon as its dossier is done), with exactly:
   ```
   run_id: <run_id>
   symbol: <SYMBOL>
   round: 1
   mandate: runs/<run_id>/mandate.yaml
   ```
2. If a red team returns `send_back: true` (material numerical discrepancies), send the name back **once**:
   - copy the round-1 files first, so nothing is lost: `dossiers/<SYMBOL>.md`, `.json`, `.conviction.json` into `runs/<run_id>/dossiers/round1/`, and `redteam/<SYMBOL>.md`, `.json` into `runs/<run_id>/redteam/round1/` (one Bash `mkdir -p` + `cp` command; the user will be asked to approve it);
   - spawn a fresh `company-analyst` with the four lines above plus `round-1 red-team file: runs/<run_id>/redteam/round1/<SYMBOL>.json. Re-fetch every number it lists as a material discrepancy.`;
   - then a fresh `red-team` with `round: 2`.
   If round 2 still has material discrepancies, drop the name and say so in the report.
3. Names with verdict `killed` form **cohort C**. Do not re-argue a kill to keep a name; if you think the red team is wrong, say so to the user with evidence and let them decide.

### Phase 5: Portfolio construction

Why: good names can still make a bad portfolio (five bets on falling rates is one bet), and the honest comparison is against owning the index or holding cash. Read `evaluation.md` first.

1. Read, for every surviving name: `dossiers/<SYMBOL>.json`, `dossiers/<SYMBOL>.conviction.json` and `redteam/<SYMBOL>.json`. Read dossier sections only where you need them. Compare depth across dossiers.
2. Resolve contradictions before sizing: high confidence with a `weakened` verdict, scenarios the red team showed do not follow from their drivers, probabilities that ignore the base rate.
3. Size positions by expected value and downside, within mandate limits (max weight, sector weight, max names, liquidity). Sizing is judgment; do the arithmetic with `compute calc`. Write `runs/<run_id>/portfolio_holdings.json`.
4. Run `compute portfolio --holdings-file runs/<run_id>/portfolio_holdings.json --mandate runs/<run_id>/mandate.yaml` (without `--mandate` it checks `config/mandate.yaml`, not the values the user confirmed for this run). Read the mandate checks and fix any breach. Look for **hidden common bets**: correlation clusters and shared drivers (rates, a commodity, government capex, the rupee, one customer or regulator).
5. Run `compute costs_tax` for a representative position over the horizon, so the cost and tax drag is explicit.
6. Compare explicitly with "buy the Nifty 500" (use `compute base_rates` and the market view) and with "hold cash". Say why the portfolio is better, or recommend fewer names, the index, or cash.
7. Write `runs/<run_id>/portfolio.md` and `runs/<run_id>/final_report.md`.

### Phase 6: Present to the user

Show the final report:
- a summary table: picks, weights, one-line thesis, probability of beating the benchmark, main risk, kill criteria;
- what was rejected and why, including the red-team kills;
- where the system is least confident, and the data gaps;
- process notes: subagents run, errors caught by verification, re-analyses, sources that were down;
- one line: this is research for the user's decision, not advice.

The user will challenge it. Answer from evidence in the run files, revise where they are right (re-fetching any number in question, and updating the files), and hold your ground where they are not. Agreeing to keep the user happy is a calibration failure too.

### Phase 7: Freeze

Why: only picks frozen with a timestamp before the outcome is known can ever be evaluated honestly. Freezing without approval would put the user's name on decisions they did not make.

**CHECKPOINT 2.** Freeze only on the user's **explicit approval in chat** of the final portfolio (for example "approved, freeze it"). A question, a "looks good" about one part, or silence is not approval; ask.

1. Write `runs/<run_id>/freeze_input.json` per `output-schemas.md`: `model_id` (the model running this session), `horizon_months`, and per pick `symbol`, `weight`, `thesis` (three sentences from the dossier), `scenarios` from the conviction file (name, probability, return_pct, return_range_pct), `p_beat_benchmark`, `kill_criteria` as strings `'<criterion> (observe: <source>; by <YYYY-MM-DD>)'` from the dossier JSON, and `review_dates`. An empty `picks` list is valid when the recommendation is the index or cash. Leave `cohorts` out so the ledger reads B, C and D from the run folder.
2. Run `uv run python -m tools ledger freeze <run_id> --approved "<the user's approval words, and the date>"` (dry runs: add `--ledger-dir ledger/test`). If validation fails, fix the input file and rerun; never edit the ledger.
3. Confirm the five cohorts in the output (A portfolio, B deep-dived, C killed, D candidates, E index).
4. Commit `runs/<run_id>/` and `ledger/` to local git (`git add runs/<run_id> ledger && git commit -m "Run <run_id>: frozen"`). Never push. Never commit `.env` or `data/cache/`.
5. Tell the user the review dates and that review mode will check the kill criteria.

---

## Single-company deep dive

Why: sometimes the user wants one company examined properly, without a full run. The same analyst-plus-red-team pairing gives the same protection against errors.

1. Phase 0 in brief: cutoff, `run_id = YYYY-MM-DD-<symbol-lower>-deepdive`, confirm the horizon (other mandate values only if relevant), write `runs/<run_id>/mandate.yaml`. Resolve the company with `data resolve` and confirm the ISIN and legal name with the user if the name was ambiguous.
2. Spawn one `company-analyst` with the four lines of Phase 3, using `market view: none for this deep dive`.
3. Spawn one `red-team` (round 1); apply the send-back rule of Phase 4 if needed.
4. Present: the thesis, scenarios and probabilities, kill criteria, the red-team verdict and its strongest point, data gaps, and the note that this is research, not advice.
5. No portfolio step and no freeze, unless the user explicitly asks to freeze it (then it is a one-pick run: follow Phase 7).

## Review mode

Why: kill criteria are only useful if someone checks them when new information arrives. Read `evaluation.md` ("Review and post-mortem practice") first.

1. Pick the run: from `$ARGUMENTS`, or list frozen runs (`grep` `ledger/picks.jsonl` for `"record_type": "run"`) and ask.
2. Run `uv run python -m tools ledger review <run_id>` (lists announcements since the last review next to each pick's kill criteria) and `uv run python -m tools ledger mark <run_id>` (gross total return of picks and cohorts vs Nifty 500 TRI; say it is gross).
3. For each pick, judge each kill criterion as **fired**, **not fired** or **unclear**, citing evidence: the announcement or result with date and page (`data filings get/search/pages`), or the tool output.
4. Recommend **hold**, **trim**, **exit** or **re-underwrite** (a fresh deep dive) for each pick, with reasons. The user decides; you never trade.
5. Write `runs/<run_id>/reviews/<YYYY-MM-DD>.md` (format in `output-schemas.md`).

## Post-mortem mode

Why: the ledger only teaches anything if outcomes are scored honestly and turned into durable process lessons. Read `evaluation.md` first.

1. Run `uv run python -m tools ledger postmortem <run_id>` (before the horizon ends it refuses unless `--force`, which writes an interim post-mortem). Ask the user for their slab rate and surcharge if they want dividend tax and surcharge included (`--slab-rate`, `--surcharge`).
2. Fill in the template it writes at `ledger/postmortems/<run_id>.md`. Separate **decision quality** (was the reasoning sound given what was knowable at the cutoff; were the documents read; did the red team catch real problems) from **outcome** (what prices did). A good decision can lose and a bad one can win.
3. Analyse calibration (Brier score for `p_beat_benchmark`, scenario Brier, the calibration table) and the cohort comparison (A-B, C-A, B-D, D-E, A-E), remembering that one run's gaps are mostly noise; say what the gaps would have to look like across runs before they change the process.
4. Distil **at most five** durable lessons into `ledger/lessons.md`. Lessons are about process, not stocks. Merge or replace older lessons rather than letting the file grow.
5. If a frozen record is wrong, use `ledger correct <record_id> --set field=JSON --reason "..."`.
6. Commit the post-mortem and lessons to local git. Never push.
