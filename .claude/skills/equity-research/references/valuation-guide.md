# Valuation guide

Read this when you write dossier section 8 (valuation) and section 11 (scenarios), when you attack a valuation as the red team, or when a hunter judges whether something "might already be priced in".

## Principles

- **Valuation is a judgment the tools support, never one they make.** The tools compute multiples, percentiles and implied growth with provenance. You choose the method, the peers, the cost of equity and the plausible growth, and you write your reasoning.
- **Use the method that fits the business.** A P/E on peak cyclical earnings, or FCF yield for a bank, is a category error. The sector sections below say what to use.
- **Ask "what has to go right?" before "what is it worth?".** The reverse DCF answers the first question with fewer assumptions. Your scenarios then judge how likely that is.
- **All arithmetic through `compute calc`.** Every multiple you derive by hand, every SOTP line, every scenario return. Commands below are `uv run python -m tools ...`.

## Command order

Run them in this order, because each one reads the cache the previous one fills:

1. `data resolve <SYM>`: identity; check the ISIN.
2. `data prices <SYM> --years 10`, and the same for each peer. Without 10 years cached, percentiles vs own history come back labelled "shorter than 5y".
3. `data financials <SYM>` (and `--basis standalone` for banks' asset quality).
4. `compute ratios <SYM>`: margins, returns, CAGRs, cash conversion, restated EPS and shares.
5. `compute valuation <SYM> --peers A,B,C`: current multiples, percentiles, peer table.
6. `compute reverse_dcf <SYM> --ke <fraction> ...`: implied growth and sensitivity grids.
7. `data macro`: risk-free rate (10-year G-sec yield, with its as-on date) for the cost of equity.

Quote every `warnings` entry these outputs carry (for example, unadjusted price gaps) and say how it affects the numbers.

## Multiples: what `compute valuation` gives you

- `current`: `market_cap`, `ev`, `pe`, `pb`, `ev_ebitda`, `fcf_yield_pct`, as of the last cached close. Inputs are listed under `inputs`, with `formulas`.
- `vs_own_history.<multiple>.5y` / `.10y`: where today's multiple sits in the company's own monthly history. Each month uses only results public by then (quarter end + 45 days; Q4 + 60 days), with the share count restated for bonuses and splits.
- `history_monthly`: the series itself, if you want to describe ranges or regime changes.
- With `--peers`: the same multiples for each peer and today's percentile within the peer set. **You choose the peers** and must write why each is comparable (business mix, size, growth, capital intensity). A peer list that makes the company look cheap is a red flag the red team will test.
- Definitions to remember: P/E uses TTM `pat_owners`; EV = market cap + borrowings − cash − other bank balances − current investments (minority interest is not added: if `balance_sheet.nci` is large, add it with `compute calc` and label the adjusted EV); EBITDA excludes other income; FCF = CFO − capex for the latest public FY. Banks get P/E and P/B only.

Reading percentiles: a low percentile vs own history means cheaper than usual, not cheap. Ask what changed: growth, returns, risk, the rate environment, or the index P/E itself (`compute base_rates` shows where the market sits).

## Sector approaches

### Banks and NBFCs: P/B against ROA and ROE, asset quality and growth

- Use P/B (and P/E as a cross-check). FCF and EV multiples are meaningless for lenders.
- Fundamentals: `compute ratios <SYM> --basis standalone` gives bank-format columns: `nii_to_avg_assets_pct`, `cost_to_income_pct`, `provisions_to_avg_advances_pct`, `roa_pct`, `roe_pct`, `pcr_pct`, `credit_deposit_pct`, `gnpa_pct_filed`, `nnpa_pct_filed`, `car_filed`, `cet1_filed`. Its `not_in_xbrl` block lists what is missing: NIM, CASA ratio and credit cost come from investor presentations with page citations.
- Link P/B to returns: justified P/B = (ROE − g) / (ke − g). Reverse it to the ROE the price implies: implied ROE = P/B × (ke − g) + g. Compute both with `compute calc` and compare the implied ROE with the bank's sustained ROE through a credit cycle, not its best year.
- Asset quality decides whether book value is real: GNPA/NNPA trend, PCR, restructured book, slippages, and unsecured or fast-growing segments. For NBFCs, add ALM (asset-liability mismatch), funding mix and cost of funds from the presentation.
- Growth only adds value when ROE exceeds ke. Fast loan growth with thin capital (low CET1) usually means dilution ahead.

### Insurers: embedded-value-based measures

- Life insurers: P/EV (market cap over Indian Embedded Value), VNB (value of new business) and VNB margin, operating RoEV, persistency. General insurers: combined ratio, investment yield, solvency ratio, P/B against ROE.
- None of these are in XBRL. Extract them from investor presentations and annual reports (`data filings list <SYM> --kind presentations`, `get`, `search "Embedded Value|VNB|persistency|solvency"`), with page citations.
- Market cap comes from `compute valuation` (`current.market_cap`). The implied multiple on new business: (market cap − EV) / VNB, computed with `compute calc`. Interpret it as how many years of today's new-business value the market is paying for.

### Cyclicals: mid-cycle earnings, not peak multiples

- Commodities, metals, cement, chemicals, autos, capital goods and similar: P/E is lowest at peak earnings and highest at the trough. Do not call a peak-earnings stock cheap on P/E.
- Estimate mid-cycle earnings: average margin over a full cycle from `compute ratios` `annual_ratios` (`ebitda_margin_pct`) and older annual reports for the years XBRL lacks; apply it to current capacity or revenue with `compute calc`. State which years you treat as one cycle and why.
- Cross-check with asset-based measures: P/B against through-cycle ROE, EV per unit of capacity (e.g. per tonne) from `current.ev` and capacity cited from the AR or presentation, and replacement cost where cited.
- Run the reverse DCF on the normalised base: `compute reverse_dcf <SYM> --price <P> --base-value <mid-cycle FCF or EPS per share> --base-label "mid-cycle FY.. basis" --ke ...`.

### Holding companies: sum of the parts with a discount

- Value each part: listed holdings at market value (shares held from the AR, price from `data prices`, or the investee's `current.market_cap` × stake), unlisted businesses on a multiple of their own earnings or book, plus holdco cash minus holdco debt. Each line has its source; all arithmetic in `compute calc`.
- Apply a holding-company discount and justify it: tax on realising gains, capital-allocation record, cash leakage to the promoter group, liquidity. Measure today's discount to NAV with `compute calc`. Where you have the inputs, compare with the company's own past discount. Do not quote a "typical" market discount from memory: cite a dated source or leave it as your own stated assumption.
- A narrowing discount needs a catalyst (listing of a subsidiary, buyback, simplification). Without one, the discount can persist for the whole horizon.

### Platforms and early-stage businesses: unit economics

- When earnings and FCF are negative or tiny, multiples and reverse DCF on current cash flow say little. Analyse unit economics: contribution margin per order or user, customer acquisition cost, payback, cohort retention, take rate, GMV growth, and operating leverage in fixed costs. Sources: investor presentations, shareholder letters, DRHP/RHP, with page citations.
- Work out what the price implies at maturity: the revenue in year N that, at a stated mature margin and exit multiple, justifies today's market cap discounted at ke. With `compute calc`: implied revenue_N = market_cap × (1 + ke)^N / (exit multiple × mature margin). Compare that revenue with the cited market size and with the company's current scale.
- Be explicit about the share count: ESOP pools and convertible instruments dilute (`compute ratios` `dilution_history`).

### Other cases

- **Asset-heavy utilities and regulated businesses**: regulated equity, allowed ROE and P/B; dividend yield against the G-sec yield from `data macro`.
- **IT services and export businesses**: revenue in USD (constant currency) as well as INR; INR/USD from `data macro`, with its date; FCF yield and P/E work well.
- **Pharma**: separate the US generics business (price erosion, FDA status from inspection outcomes, with dates) from the domestic business; R&D expensed vs capitalised.
- **Companies with large cash or treasury investments**: look at EV-based multiples and ex-cash P/E (computed with `compute calc`), and check whether the cash is really available to minority shareholders.

## Reverse DCF: proper use

`compute reverse_dcf` solves for the growth rate today's price implies.

Model: base cash flow per share CF0, N years of growth g, F fade years in which growth falls linearly to terminal growth gt, then a Gordon terminal value, all discounted at ke. It solves for g by bisection on [-90%, 200%]. With `--years 0 --fade 0` it solves for the implied perpetual growth instead and returns it as `implied_terminal_growth` (useful for mature businesses).

Ways to call it:
- `compute reverse_dcf <SYM> --ke 0.12` (defaults: `--base fcf`, latest-FY FCF per share on today's share basis, price = last cached close).
- `compute reverse_dcf <SYM> --ke 0.12 --base eps` (TTM restated EPS).
- `compute reverse_dcf --price <P> --base-value <CF0> --base-label "<what CF0 is>" --ke 0.12 --years 10 --fade 5 --terminal-growth 0.05` (your own base, e.g. normalised earnings).

Outputs: `implied_growth`; `what_has_to_go_right` with `cash_flow_multiple_by_end_of_high_growth`, `cash_flow_multiple_by_end_of_fade` and `terminal_value_share_of_price`; grids `sensitivity_ke_x_n` (cost of equity × high-growth years) and `sensitivity_ke_x_gt` (cost of equity × terminal growth).

Steps:
1. **Choose a base that represents distributable cash.** FCF suits capex-light, steady businesses. TTM EPS suits businesses whose capex is temporarily lumpy, but EPS overstates distributable cash when growth needs reinvestment: say so. Use a normalised base for cyclicals. If the base is zero or negative the model does not apply: say so and use a sector method above.
2. **Set ke explicitly.** Start from the 10-year G-sec yield from `data macro` (quote the value and as-on date), add an equity risk premium you state and justify (and a company-specific premium if you think one is warranted), with `compute calc`. Then read the grid rows at ke ± 1-2 points rather than trusting one ke.
3. **Keep gt below ke and below long-run nominal growth of the economy.** State your gt, and read `sensitivity_ke_x_gt`.
4. **Translate the answer into business terms.** "The price implies FCF per share grows at g for N years, reaching `cash_flow_multiple_by_end_of_high_growth` times today's level." Then compare that with:
   - the company's own record (`compute ratios` `growth_cagr`, restated EPS);
   - the industry's growth, from cited sources;
   - management guidance, discounted by its delivery record (dossier section 7);
   - how often companies sustain such growth for that long. The tools have no cross-company base rate for this: say so, and treat long high-growth runs as rare unless you cite evidence.
5. **Read `terminal_value_share_of_price`.** When most of the price is terminal value, the stock is a bet on the distant future and is very sensitive to ke.
6. **Conclude in words**: whether the implied growth looks conservative, demanding or heroic, and why. This feeds section 8 and the variant perception (section 12).

Don'ts:
- Do not iterate inputs until the answer says "cheap". Report the grid.
- Do not present the implied growth as precise; a range across the grid is the honest output.
- Do not use the reverse DCF as a target-price machine. It shows what the market is pricing in, nothing more.

## From valuation to scenarios (dossier section 11)

For bear, base and bull:
- Name the drivers (volumes, margins, multiple) and the evidence for each.
- Compute the horizon total return with `compute calc`, for example: return_pct = ((exit_multiple × forward_earnings_per_share + dividends_per_share) / price − 1) × 100, with every input cited or labelled as your assumption.
- Give each scenario a return range that tiles the whole number line, for the scenario Brier score: bear `[null, x)`, base `[x, y)`, bull `[y, null]`. Returns are the stock's gross total return over the horizon in %, the same measure the ledger scores.
- Scenario **probabilities**, the expected value and the probability of beating the Nifty 500 TRI go only into the conviction file, not the dossier (see `output-schemas.md`). The red team attacks the drivers and returns without seeing your probabilities.
- Compare with the market's own base rates: `compute base_rates` gives the distribution of Nifty 500 TRI returns over the horizon from similar starting valuations, with `n_obs`, `n_independent` and confidence intervals. Your probability of beating the benchmark should be consistent with what the benchmark itself is likely to do.
