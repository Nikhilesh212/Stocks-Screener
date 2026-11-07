"""Quarterly and annual financial statements parsed from exchange XBRL filings.

Sources (NSE):
* integrated-filing-results  (SEBI integrated filing, Q3FY25 onward)
* corporates-financial-results period=Quarterly / Annual (legacy XBRL, Ind AS era)

Coverage, stated plainly: P&L for every quarter filed in Ind AS XBRL; balance
sheet and cash flow only at half-year and year end (that is all SEBI requires in
results). Pre-Ind-AS (before ~FY17) filings use another taxonomy and are skipped;
older history must come from annual reports, cited by page.
All money in INR crore (XBRL holds absolute rupees). Per-share items in INR.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from ..common.cache import fetch
from ..common.entity import Entity, get_entity, same_issuer_equity
from ..common.http import SourceError
from ..common.periods import fy_label, months_between, parse_date, period_label
from ..common.provenance import table, today_ist
from ..common.sources import TTL_LIST, nse_api
from ..common.units import CRORE, INR_CR
from . import xbrl

CORP = {
    "revenue": ["RevenueFromOperations"], "other_income": ["OtherIncome"], "total_income": ["Income"],
    "cost_of_materials": ["CostOfMaterialsConsumed"], "purchases_stock_in_trade": ["PurchasesOfStockInTrade"],
    "change_in_inventories": ["ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade"],
    "employee_cost": ["EmployeeBenefitExpense"], "finance_costs": ["FinanceCosts"],
    "depreciation": ["DepreciationDepletionAndAmortisationExpense"], "other_expenses": ["OtherExpenses"],
    "total_expenses": ["Expenses"], "pbt_before_exceptional": ["ProfitBeforeExceptionalItemsAndTax"],
    "exceptional_items": ["ExceptionalItemsBeforeTax"], "pbt": ["ProfitBeforeTax"], "tax": ["TaxExpense"],
    "share_of_associates_jv": ["ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod"],
    "pat": ["ProfitLossForPeriod"], "pat_owners": ["ProfitOrLossAttributableToOwnersOfParent"],
    "pat_minority": ["ProfitOrLossAttributableToNonControllingInterests"],
    "eps_basic": ["BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsLossPerShareFromContinuingOperations"],
    "eps_diluted": ["DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "DilutedEarningsLossPerShareFromContinuingOperations"],
    "paid_up_capital": ["PaidUpValueOfEquityShareCapital"], "face_value": ["FaceValueOfEquityShareCapital"],
    "debt_equity_reported": ["DebtEquityRatio"], "interest_coverage_reported": ["InterestServiceCoverageRatio"],
    "cfo": ["CashFlowsFromUsedInOperatingActivities"], "cfi": ["CashFlowsFromUsedInInvestingActivities"],
    "cff": ["CashFlowsFromUsedInFinancingActivities"],
    "capex_ppe": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "capex_intangibles": ["PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"],
    "dividends_paid": ["DividendsPaidClassifiedAsFinancingActivities"],
    "share_issue_proceeds": ["ProceedsFromIssuingSharesClassifiedAsFinancingActivities"],
    "ppe": ["PropertyPlantAndEquipment"], "cwip": ["CapitalWorkInProgress"], "goodwill": ["Goodwill"],
    "other_intangibles": ["OtherIntangibleAssets"], "noncurrent_investments": ["NoncurrentInvestments"],
    "current_investments": ["CurrentInvestments"], "inventories": ["Inventories"],
    "trade_receivables_current": ["TradeReceivablesCurrent"], "trade_receivables_noncurrent": ["TradeReceivablesNoncurrent"],
    "cash": ["CashAndCashEquivalents"], "other_bank_balances": ["BankBalanceOtherThanCashAndCashEquivalents"],
    "loans_current": ["LoansCurrent"], "loans_noncurrent": ["LoansNoncurrent"], "current_assets": ["CurrentAssets"],
    "total_assets": ["Assets"], "equity_share_capital": ["EquityShareCapital"], "other_equity": ["OtherEquity"],
    "equity_owners": ["EquityAttributableToOwnersOfParent"], "nci": ["NonControllingInterest"], "total_equity": ["Equity"],
    "borrowings_noncurrent": ["BorrowingsNoncurrent"], "borrowings_current": ["BorrowingsCurrent"],
    "trade_payables_current": ["TradePayablesCurrent"], "current_liabilities": ["CurrentLiabilities"],
    "total_liabilities": ["Liabilities"],
}
BANK = {
    "interest_earned": ["InterestEarned"], "interest_expended": ["InterestExpended"], "other_income": ["OtherIncome"],
    "total_income": ["Income"], "employee_cost": ["EmployeesCost"], "operating_expenses": ["OperatingExpenses"],
    "operating_profit_pre_provision": ["OperatingProfitBeforeProvisionAndContingencies"],
    "provisions": ["ProvisionsOtherThanTaxAndContingencies"], "exceptional_items": ["ExceptionalItems"],
    "pbt": ["ProfitLossFromOrdinaryActivitiesBeforeTax"], "tax": ["TaxExpense"], "pat": ["ProfitLossForThePeriod"],
    "pat_owners": ["ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates"],
    "eps_basic": ["BasicEarningsPerShareAfterExtraordinaryItems"], "eps_diluted": ["DilutedEarningsPerShareAfterExtraordinaryItems"],
    "paid_up_capital": ["PaidUpValueOfEquityShareCapital"], "face_value": ["FaceValueOfEquityShareCapital"],
    "gross_npa": ["GrossNonPerformingAssets"], "net_npa": ["NonPerformingAssets"], "gnpa_pct": ["PercentageOfGrossNpa"],
    "nnpa_pct": ["PercentageOfNpa"], "cet1_ratio": ["CET1Ratio"], "at1_ratio": ["AdditionalTier1Ratio"],
    "car": ["CapitalAdequacyRatioBaselIII", "CapitalAdequacyRatio"], "roa_reported": ["ReturnOnAssets"],
    "govt_holding_pct": ["PercentageOfShareHeldByGovernmentOfIndia"],
    "cfo": ["CashFlowsFromUsedInOperatingActivities"], "cfi": ["CashFlowsFromUsedInInvestingActivities"],
    "cff": ["CashFlowsFromUsedInFinancingActivities"],
    "advances": ["Advances"], "deposits": ["Deposits"], "investments": ["Investments"], "borrowings": ["Borrowings"],
    "capital": ["Capital"], "reserves": ["ReservesAndSurplus"], "total_assets": ["Assets"],
    "cash_and_rbi_balances": ["CashAndBalancesWithReserveBankOfIndia"],
    "balances_with_banks": ["BalancesWithBanksAndMoneyAtCallAndShortNotice"], "fixed_assets": ["FixedAssets"],
}
PER_SHARE = {"eps_basic", "eps_diluted", "face_value"}
RATIO_ITEMS = {"debt_equity_reported", "interest_coverage_reported", "gnpa_pct", "nnpa_pct", "cet1_ratio", "at1_ratio", "car", "roa_reported", "govt_holding_pct"}
RAW_INR = {"paid_up_capital"}  # kept in INR so share count stays exact
CROSSCHECK_TOL = 0.02


def _basis_flag(basis: str) -> str:
    return "Consolidated" if basis == "consolidated" else "Non-Consolidated"


def list_filings(e: Entity, basis: str) -> tuple[list[dict], list[str]]:
    want = _basis_flag(basis)
    out, warns = [], []
    page = 1
    while True:
        try:
            data, f = nse_api("integrated-filing-results", {"index": "equities", "symbol": e.nse_symbol, "page": page, "size": 20},
                              key=f"{e.isin}/nse_results/integrated_p{page}.json", ttl_hours=TTL_LIST)
        except SourceError as ex:
            warns.append(f"integrated filings list unavailable: {ex}")
            break
        rows = (data or {}).get("data", [])
        for r in rows:
            if r.get("consolidated") == want and r.get("xbrl") and "Financial" in (r.get("type") or ""):
                out.append({"period_end": parse_date(r["qe_Date"]), "xbrl": r["xbrl"], "broadcast": r.get("broadcast_Date"),
                            "family": "integrated", "revised": r.get("type_Sub") not in (None, "Original")})
        total = int((data or {}).get("totalCount") or 0)
        if not rows or page * 20 >= total or page >= 5:
            break
        page += 1
    for period in ("Quarterly", "Annual"):
        try:
            data, f = nse_api("corporates-financial-results", {"index": "equities", "symbol": e.nse_symbol, "period": period},
                              key=f"{e.isin}/nse_results/legacy_{period}.json", ttl_hours=TTL_LIST)
        except SourceError as ex:
            warns.append(f"legacy {period} results list unavailable: {ex}")
            continue
        for r in data or []:
            if r.get("isin") and not same_issuer_equity(r["isin"], e.isin):
                continue
            if r.get("consolidated") != want or not r.get("xbrl") or "Ind-AS" not in (r.get("indAs") or ""):
                continue
            out.append({"period_end": parse_date(r["toDate"]), "xbrl": r["xbrl"], "broadcast": r.get("broadCastDate"),
                        "family": f"legacy_{period.lower()}", "bank_flag": r.get("bank"), "revised": False})
    return out, warns


def _pick(filings: list[dict], period_end: dt.date, prefer_annual: bool = False) -> dict | None:
    cands = [f for f in filings if f["period_end"] == period_end]
    if not cands:
        return None

    def score(f):
        fam = {"integrated": 2, "legacy_annual": 1 if prefer_annual else 0, "legacy_quarterly": 0 if prefer_annual else 1}[f["family"]]
        b = parse_date(f["broadcast"]) if f.get("broadcast") else dt.date.min
        return (fam, b or dt.date.min)
    return max(cands, key=score)


def _extract(inst: xbrl.Instance, mapping: dict) -> list[tuple[str, str, dt.date | None, dt.date, float, str]]:
    """(item, kind, start, end, value_in_output_unit, unit) for every non-dimensional fact we map."""
    out = []
    for item, aliases in mapping.items():
        for tag in aliases:
            vals = xbrl.values_by_period(inst, tag)
            if not vals:
                continue
            for c, v, unit in vals:
                if item in PER_SHARE:
                    val, u = v, "INR/share"
                elif item in RATIO_ITEMS:
                    val, u = v, "as filed (pure)"
                elif item in RAW_INR:
                    val, u = v, "INR"
                else:
                    val, u = v / CRORE, INR_CR
                out.append((item, "instant" if c.instant else "duration", c.start, c.end, val, u))
            break
    return out


def statements(e: Entity, basis: str, quarters: int, years: int) -> dict:
    filings, warns = list_filings(e, basis)
    if not filings:
        return {"warnings": warns + [f"no {basis} Ind AS XBRL filings found"], "filings_used": []}
    ends = sorted({f["period_end"] for f in filings}, reverse=True)
    q_ends = ends[:quarters]
    fy_ends = [d for d in ends if d.month == 3 and d.day == 31][:years]
    h1_ends = [d for d in ends if d.month == 9 and d.day == 30][:years]
    targets = sorted(set(q_ends) | set(fy_ends) | set(h1_ends), reverse=True)

    is_bank = False
    values: dict[tuple[str, str], tuple[float, str, str, dt.date]] = {}
    conflicts: list[dict] = []
    used = []
    for end in targets:
        f = _pick(filings, end, prefer_annual=end in fy_ends)
        try:
            doc = fetch(f["xbrl"], key=f"{e.isin}/xbrl/{f['xbrl'].rsplit('/', 1)[-1]}", ttl_hours=None)
            inst = xbrl.parse(doc.content)
        except (SourceError, Exception) as ex:  # one bad filing must not sink the table
            warns.append(f"{end}: could not read XBRL {f['xbrl']}: {ex}")
            continue
        if any(fct.name == "InterestEarned" for fct in inst.facts):
            is_bank = True
        isin_in_doc = inst.text.get("ISIN")
        if isin_in_doc and not same_issuer_equity(isin_in_doc, e.isin):
            warns.append(f"{end}: XBRL ISIN {isin_in_doc} != {e.isin}; filing skipped (entity mismatch)")
            continue
        used.append({"period_end": end.isoformat(), "family": f["family"], "xbrl": f["xbrl"], "broadcast": f.get("broadcast")})
        for item, kind, s, t, val, unit in _extract(inst, BANK if is_bank else CORP):
            label = f"as of {t.isoformat()}" if kind == "instant" else period_label(s, t)
            key = (label, item)
            primary = t == end
            if key in values:
                old = values[key]
                if old[0] and abs(val / old[0] - 1) > CROSSCHECK_TOL if old[0] else val != 0:
                    conflicts.append({"period": label, "item": item, "kept": old[0], "other": val, "kept_source": old[2], "other_source": f["xbrl"]})
                if not primary:
                    continue
            values[key] = (val, unit, f["xbrl"], t)

    def build(period_filter, columns_kind: str):
        labels = sorted({k[0] for k in values if period_filter(k[0])}, key=lambda l: values_end(l), reverse=True)
        items = list((BANK if is_bank else CORP).keys())
        present = [i for i in items if any((l, i) in values for l in labels)]
        rows = []
        for l in labels:
            src = next((values[(l, i)][2] for i in present if (l, i) in values), None)
            rows.append([l, values_end(l).isoformat(), *[values[(l, i)][0] if (l, i) in values else None for i in present], src])
        units = {i: next(values[(l, i)][1] for l in labels if (l, i) in values) for i in present}
        return table(["period", "period_end", *present, "source_xbrl"], rows, units=units,
                     source=f"NSE XBRL results filings ({basis})", as_of=rows[0][1] if rows else None,
                     notes=f"{columns_kind}; null = not reported in that filing (never imputed)")

    ends_by_label = {k[0]: v[3] for k, v in values.items()}

    def values_end(label):
        return ends_by_label[label]

    quarterly = build(lambda l: l.startswith("Q"), "quarterly P&L (3-month periods)")
    annual = build(lambda l: l.startswith("FY"), "annual P&L and cash flow (12-month periods)")
    half = build(lambda l: l.startswith("H1"), "half-year (H1) P&L and cash flow")
    bs = build(lambda l: l.startswith("as of"), "balance sheet at half-year and year ends")

    checks = []
    rev_item = "interest_earned" if is_bank else "revenue"
    for fy_end in fy_ends:
        fy = fy_label(fy_end)
        qs = [f"Q{n}{fy}" for n in (1, 2, 3, 4)]
        for item in (rev_item, "pat"):
            if (fy, item) in values and all((q, item) in values for q in qs):
                total = sum(values[(q, item)][0] for q in qs)
                annual_v = values[(fy, item)][0]
                diff = abs(total / annual_v - 1) if annual_v else None
                checks.append({"check": f"sum of quarters vs annual {item} {fy}", "sum_quarters": total, "annual": annual_v, "unit": INR_CR,
                               "diff_pct": None if diff is None else round(diff * 100, 3), "flag": diff is None or diff > CROSSCHECK_TOL})
    return {"is_bank_format": is_bank, "quarterly": quarterly, "annual": annual, "half_year": half, "balance_sheet": bs,
            "crosschecks": {"kind": "table", "columns": ["check", "sum_quarters", "annual", "unit", "diff_pct", "flag"], "units": {"sum_quarters": INR_CR, "annual": INR_CR, "diff_pct": "%"},
                            "rows": [[c["check"], c["sum_quarters"], c["annual"], c["unit"], c["diff_pct"], c["flag"]] for c in checks],
                            "source": "computed from the tables above", "retrieved_at": quarterly["retrieved_at"]},
            "restatements_or_conflicts": {"kind": "table", "columns": ["period", "item", "kept", "other", "kept_source", "other_source"], "units": {"kept": "as item", "other": "as item"},
                                          "rows": [[c[k] for k in ("period", "item", "kept", "other", "kept_source", "other_source")] for c in conflicts],
                                          "source": "values for the same period differing >2% across filings", "retrieved_at": quarterly["retrieved_at"]},
            "filings_used": used, "warnings": warns}


def cmd_financials(args) -> dict:
    e = get_entity(args.query)
    res = statements(e, args.basis, args.quarters, args.years)
    out = {"identity": e.identity(), "basis": args.basis, "as_of_request": today_ist().isoformat(),
           "coverage_note": ("Ind AS XBRL only. Balance sheet and cash flow exist only at H1 and FY ends. "
                             "Older years and items not in XBRL (segment detail, contingent liabilities, related parties) must come from annual reports with page cites."),
           **res}
    if args.basis == "consolidated" and not res.get("filings_used"):
        out["hint"] = "no consolidated filings; company may not have subsidiaries. Retry with --basis standalone."
    return out


def register(sub, leaf) -> None:
    p = leaf(sub, "financials", "Quarterly/annual P&L, balance sheet, cash flow from exchange XBRL (INR crore)")
    p.add_argument("query", help="NSE symbol or ISIN")
    p.add_argument("--basis", choices=("consolidated", "standalone"), default="consolidated")
    p.add_argument("--quarters", type=int, default=12)
    p.add_argument("--years", type=int, default=8)
    p.set_defaults(func=cmd_financials)
