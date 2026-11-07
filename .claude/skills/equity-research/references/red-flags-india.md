# Red-flag checklist for Indian listed companies

Read this when you write dossier section 6 (company-analyst) or attack a dossier's governance section (red-team). Every item gets a mark of **pass**, **flag** or **unknown**, with evidence (tool command or document and page) and the period checked.

## How to use it

- **The marks are your judgment.** The "pass/flag" lines below are guides from common practice, not rules, and no code scores them. A flag is not an automatic rejection: write what it means for this business. A pass is not proof of good governance either.
- **Unknown is honest.** Use it when you could not obtain the evidence, and say what you tried. Never mark pass because you found nothing without looking.
- **Trend beats level.** For most items the direction over 8-12 quarters or 3-5 years says more than one reading.
- **Commands.** All commands are `uv run python -m tools ...`. Run `data resolve <SYM>` first and check that each output's `identity.isin` matches. To read a document, list it with `data filings list <SYM> --kind <kind>`, download it with `data filings get <SYM> <url>` (returns a `doc_id`), then `data filings search <SYM> <doc_id> "<regex>"` (page numbers and snippets) and `data filings pages <SYM> <doc_id> <from>-<to>`.
- Numbers you compare (ratios, percentages, growth) come from tools or from `compute calc`. Never do the arithmetic in your head.

Common inputs, fetched once and reused for several items:

| Input | Command |
|---|---|
| Ratios history (days, OCF/PAT, other income, dilution) | `data financials <SYM>` then `compute ratios <SYM>` (banks: add `--basis standalone`) |
| Balance-sheet lines (CWIP, goodwill, loans) | `data financials <SYM> --years 8`, table `balance_sheet` |
| Shareholding and pledge | `data shareholding <SYM> --quarters 12` |
| Announcements, 12 months | `data filings list <SYM> --kind announcements --months 12` |
| Annual report | `data filings list <SYM> --kind annual_reports`, then `get` / `search` / `pages` |
| Surveillance, corporate actions | `data events <SYM>` |
| Rating actions | `data filings list <SYM> --kind ratings --months 24` (fields `ratings`, `rating_actions`) |

## The checklist

### 1. Promoter pledging and its trend

Why: a pledge can force promoter selling in a falling market and signals promoter-level financial stress.
Check: `data shareholding` column `pledged_pct_of_promoter` (with `pledge_evidence`) over 12 quarters; announcements of encumbrance disclosures under the SEBI takeover regulations (search the announcement text for "encumbrance|pledge").
- Pass: zero, or small and falling.
- Flag: rising over the last 4 quarters, or a large share of the promoter stake (a quarter or more is commonly treated as serious), or fresh encumbrance disclosures.
- Unknown: shareholding returned null for the quarters needed. Note: a company with no promoter group (e.g. some banks) shows "no promoter group": mark pass with that note.

### 2. Promoter selling

Why: insiders know the business best, and steady selling outside stated reasons (estate planning, a regulatory minimum public shareholding) is information.
Check: `promoter` column trend in `data shareholding`; announcements for SAST/PIT disclosures, offers for sale, block deals. Bulk and block deals by web search on NSE/BSE pages, with dates.
- Pass: stable or rising promoter holding, or a documented reason for a sale (MPS compliance, a one-off OFS with stated use).
- Flag: repeated sales across quarters, sales just before weak results, or sales while management talks up prospects.
- Unknown: holding data incomplete.

### 3. Auditor resignations or changes; qualified opinions

Why: an auditor resigning mid-term, or a qualified or adverse opinion, is one of the strongest warnings in Indian markets.
Check: announcements (search text for "auditor|statutory auditor|resignation"); in the annual report, `search` for "Qualified Opinion|Basis for Qualified|Adverse Opinion|Emphasis of Matter|Material Uncertainty|Key Audit Matter" and for the CARO annexure ("Companies \(Auditor's Report\) Order").
- Pass: same auditor through its term, rotation on schedule, unmodified opinion, no material CARO remarks.
- Flag: mid-term resignation (read the stated reason), qualified or adverse opinion, going-concern uncertainty, an emphasis of matter on revenue, related parties or receivables, CARO remarks on loans to related parties or undisclosed income.
- Unknown: annual report not obtainable.

### 4. Large or growing related-party transactions (RPTs)

Why: RPTs can move value from minority shareholders to the promoter group (purchases, royalties, loans, rent).
Check: annual report note "Related Party Disclosures" (`search "related party"`), the half-yearly RPT disclosures in announcements, shareholder approvals for material RPTs. Express the largest items as a % of revenue or net worth with `compute calc`.
- Pass: small relative to revenue and net worth, arm's-length and stable; royalty rates stable.
- Flag: RPTs growing faster than revenue, large loans or advances to promoter entities, brand royalty increases, purchases from promoter-owned suppliers on non-transparent terms.
- Unknown: note not readable.

### 5. Contingent liabilities relative to net worth

Why: disputed claims (tax, customs, guarantees for group companies) can crystallise into cash outflows.
Check: annual report note "Contingent liabilities" (`search "contingent liabilit"`), then `compute ratios <SYM> --contingent-liabilities <INR crore> --contingent-source "AR FY26 p.<page>"`, which returns `contingent_liabilities_pct_networth`. Read the break-down: corporate guarantees for group entities matter more than routine tax disputes.
- Pass: small relative to net worth, mostly routine items.
- Flag: large relative to net worth, growing, or including guarantees for promoter-group borrowings.
- Unknown: note not found.

### 6. Capital work-in-progress that never completes

Why: CWIP that sits for years can hide capitalised expenses or money diverted to other uses.
Check: `balance_sheet` columns `cwip` and `ppe` over several years in `data financials`; the AR's CWIP ageing schedule (`search "CWIP|capital work-in-progress|ageing"`); management's commissioning timelines in transcripts.
- Pass: CWIP turns into PPE on the stated timeline.
- Flag: CWIP large relative to PPE for several years, ageing above 2-3 years, repeatedly delayed commissioning.
- Unknown: XBRL lacks the balance sheet and the AR is not readable.

### 7. Receivable or inventory days rising faster than sales

Why: revenue that is not collected may not be real; inventory build-up can precede write-downs.
Check: `compute ratios` columns `receivable_days`, `inventory_days`, `payable_days`, `cash_conversion_cycle_days` over 3-5 years, next to revenue growth (`growth_cagr.revenue`, `annual_ratios.revenue`). Also unbilled revenue and non-current receivables (`trade_receivables_noncurrent`).
- Pass: days stable or falling, or rising with a documented business reason (e.g. a mix shift to government customers, stated in the AR).
- Flag: days rising for two or more years while revenue grows, sharp rise in non-current receivables, large provisions or write-offs.
- Unknown: balance-sheet data missing.

### 8. Operating cash flow persistently well below PAT

Why: profits that never turn into cash are the classic sign of aggressive accounting.
Check: `compute ratios` columns `ocf_pat` and `ocf_ebitda` for every year available; sum several years with `compute calc` (one bad year is normal for a growing company).
- Pass: cumulative OCF close to or above cumulative PAT over 3-5 years.
- Flag: cumulative OCF well below cumulative PAT (a common reading is below about 70-80%) with no capex-free explanation; OCF negative while PAT grows.
- Unknown: cash-flow data missing (XBRL has cash flow only at H1 and FY).
- Banks and NBFCs: OCF is not meaningful; mark "not applicable" and look at asset quality instead.

### 9. Frequent equity dilution and preferential allotments

Why: repeated issuance, especially preferential allotments or warrants to the promoter at low prices, transfers value from minorities.
Check: `compute ratios` columns `share_count_change_pct` and `dilution_history` (restated for bonuses and splits, so only real issuance shows); announcements for "preferential|warrants|QIP|rights|ESOP".
- Pass: little issuance, or issuance at fair prices for clear growth use.
- Flag: share count growing every year, preferential issues or warrants to promoters, large ESOP grants relative to profits.
- Unknown: share data missing.

### 10. Large unexplained other income

Why: other income can flatter profits and may be non-recurring or circular (interest from group loans).
Check: `compute ratios` column `other_income_pct_pbt`; the AR note on other income (`search "other income"`) for its composition.
- Pass: small share of PBT, or explained by treasury income on visible cash.
- Flag: a large and rising share of PBT, interest from related parties, gains booked on asset sales labelled as recurring.
- Unknown: composition not disclosed.

### 11. Goodwill and loans to group entities

Why: goodwill from acquisitions can hide overpayment; loans and investments in group entities can be a channel for value leakage.
Check: `balance_sheet` columns `goodwill`, `loans_current`, `loans_noncurrent`, `noncurrent_investments`; AR notes on loans given, investments in subsidiaries, guarantees and impairment testing (`search "impairment|loans to|corporate guarantee"`).
- Pass: goodwill small or from clearly earning acquisitions; no material loans to promoter entities.
- Flag: goodwill large relative to net worth with weak acquired businesses; loans or guarantees to promoter-group companies; repeated impairments.
- Unknown: notes not readable.

### 12. Credit-rating downgrades

Why: rating agencies see private information (bank lines, covenants); downgrades or "watch negative" often lead equity weakness.
Check: `data filings list <SYM> --kind ratings --months 24` (`ratings` announcements and `rating_actions`); agency releases (CRISIL, ICRA, CARE, India Ratings, Acuite) by web search, each with its date.
- Pass: stable or upgraded.
- Flag: downgrade, outlook to negative, "rating watch with negative implications", a non-cooperation notice, or a switch of agency after a poor rating.
- Unknown: no rating found (a debt-free company may simply have none: say so).

### 13. ASM/GSM surveillance listing

Why: NSE/BSE put stocks under Additional or Graded Surveillance Measures for abnormal price or volume moves or weak fundamentals; this brings trading restrictions and is a speculation signal.
Check: `data events <SYM>`, field `surveillance` (`on_surveillance`, `entries`, `sources`).
- Pass: not on any list.
- Flag: currently on ASM or GSM (note the stage), or listed in the last 12 months.
- Unknown: surveillance sources failed (the output says so).

### 14. SME-board or illiquid status

Why: SME-platform stocks and thinly traded names can be impossible to exit at a fair price; the mandate excludes the SME platform by default.
Check: `data resolve <SYM>` fields `board` and `series`; `compute technicals <SYM>` block `liquidity` (`adv_20d`, `median_value_20d`, `adv_60d`, `delivery_pct_20d`); compare with `config/mandate.yaml` `liquidity` (`min_adv_inr_crore`, `max_days_to_exit`, `participation_rate`). The main session checks days-to-exit with `compute portfolio`.
- Pass: main board, ADV comfortably above the mandate floor.
- Flag: SME board (a mandate exclusion), ADV near or below the floor, or a median far below the mean (a few large days inflate the average).
- Unknown: price history missing.

### 15. Frequent changes in accounting policy

Why: policy changes (revenue recognition, depreciation lives, capitalisation, consolidation scope) can manufacture earnings growth.
Check: AR "Significant accounting policies" and "changes in accounting policies" (`search "change in accounting|changed the|reclassif|restat"`); auditor's emphasis of matter; `restatements_or_conflicts` in `data financials`; a change of financial year-end or of consolidation scope.
- Pass: no material changes, or changes required by a new standard and explained.
- Flag: voluntary changes that raise profit, repeated restatements, frequent reclassification between operating and other income.
- Unknown: AR not readable.

### 16. Large unresolved tax or regulatory disputes

Why: big disputes (income tax, GST, customs, SEBI, CCI, environmental) can lead to cash payments, licence loss or management bans.
Check: contingent-liability break-down in the AR; announcements for "order|penalty|show cause|SEBI|litigation"; web search for regulator orders (SEBI, CCI, NCLT, RBI, sector regulators), each with its date and the regulator's own document where possible.
- Pass: routine disputes, small relative to net worth, nothing against promoters or key managers.
- Flag: material demands or penalties, SEBI orders against promoters or directors, insolvency proceedings involving group companies.
- Unknown: could not search adequately.

### 17. Management guidance repeatedly missed

Why: management credibility is a core input for every forecast; a history of missed guidance means discounting today's guidance.
Check: the last 4-8 concall transcripts (`data filings list <SYM> --kind transcripts`, `get`, `search "guid|expect|target|outlook|margin"`) and presentations; record each promise with its date and page, then the outcome from `data financials` or later results. Put the table in dossier section 7 (guidance versus delivery).
- Pass: guidance mostly met or beaten, misses explained candidly.
- Flag: repeated misses, guidance quietly dropped, targets moved without acknowledgement.
- Unknown: fewer than two transcripts obtainable.

## Further checks worth running when relevant

| Item | Where to look | Flag when |
|---|---|---|
| Senior turnover (CFO, company secretary, independent directors) | announcements: "resignation", "cessation" | several departures within 12-24 months, especially with vague reasons |
| Delayed results or filings | announcements and event calendar (`data events`) | results filed late or postponed board meetings |
| Cash and debt both high | `balance_sheet` cash, `current_investments`, borrowings | large idle cash alongside large borrowings at high cost |
| Low effective tax rate | `compute ratios` `effective_tax_rate_pct` | far below statutory without tax-holiday disclosure |
| Recurring exceptional items | `data financials` `exceptional_items` | "one-off" charges in most years |
| Royalty or brand fees to the promoter (MNC subsidiaries, group brands) | AR RPT note | rate increases, or fees large relative to profit |
| Subsidiary sprawl | AR list of subsidiaries; consolidated vs standalone gap | many loss-making step-down subsidiaries, standalone profits far above consolidated |
| Promoter remuneration | AR corporate-governance report | pay large relative to profit, commission rising while profits fall |

## Writing the section

For each of the 17 items (and any further check you ran), write one row:

`| # | Item | Mark (pass/flag/unknown) | Evidence (command or doc + page, period) | What it means here |`

Then a short paragraph: which flags matter for this thesis and why, and which unknowns could change the conclusion.
