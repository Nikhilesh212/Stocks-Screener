"""`compute ratios`: return, margin, growth, balance-sheet and earnings-quality metrics.

Input is the output of `data financials` (a JSON file via --input, or computed
from the cache). Every ratio states its formula; anything that needs data the
XBRL filings do not carry (contingent liabilities, CASA, NIM proper) comes back
as null with the reason, unless the caller passes a cited value.

Conventions: averages use opening and closing balances (previous and current
FY end); if the opening balance is missing the closing one is used and the
row says so. Days ratios use 365 days. Money in INR crore.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from ..common.errors import InputError
from ..common.provenance import derived, missing, num
from ..common.units import COUNT, DAYS, INR_CR, PCT, RATIO
from ._util import cagr, fnum, frame, load_json, records_table, safe_div

CORP_FORMULAS = {
    "ebitda": "pbt_before_exceptional + finance_costs + depreciation - other_income (excludes other income)",
    "ebit": "pbt_before_exceptional + finance_costs",
    "ebitda_margin_pct": "ebitda / revenue * 100",
    "pat_margin_pct": "pat / revenue * 100",
    "other_income_pct_pbt": "other_income / pbt * 100",
    "effective_tax_rate_pct": "tax / pbt * 100",
    "roe_pct": "pat_owners / average(equity_owners) * 100",
    "roce_pct": "ebit / average(total_equity + borrowings_noncurrent + borrowings_current) * 100",
    "debt_equity": "(borrowings_noncurrent + borrowings_current) / total_equity",
    "net_debt": "borrowings_noncurrent + borrowings_current - cash - other_bank_balances - current_investments",
    "interest_coverage": "ebit / finance_costs",
    "ocf_ebitda": "cfo / ebitda",
    "ocf_pat": "cfo / pat",
    "fcf": "cfo - capex_ppe - capex_intangibles (capex filed as positive outflows)",
    "receivable_days": "trade_receivables_current / revenue * 365 (closing balance)",
    "inventory_days": "inventories / cogs * 365, cogs = cost_of_materials + purchases_stock_in_trade + change_in_inventories",
    "payable_days": "trade_payables_current / cogs * 365",
    "cash_conversion_cycle_days": "receivable_days + inventory_days - payable_days",
    "shares_crore": "paid_up_capital (INR) / face_value / 1e7",
    "share_count_change_pct": "shares_crore / previous FY shares_crore * 100 - 100 (dilution if > 0)",
}
BANK_FORMULAS = {
    "nii": "interest_earned - interest_expended",
    "nii_to_avg_assets_pct": "nii / average(total_assets) * 100 (PROXY: true NIM needs average interest-earning assets, not in XBRL)",
    "cost_to_income_pct": "operating_expenses / (nii + other_income) * 100",
    "provisions_to_avg_advances_pct": "provisions / average(advances) * 100 (PROXY for credit cost: provisions include non-credit items)",
    "roa_pct": "pat / average(total_assets) * 100",
    "roe_pct": "pat_owners / average(capital + reserves) * 100",
    "pcr_pct": "(gross_npa - net_npa) / gross_npa * 100 (excludes technical write-offs)",
    "credit_deposit_pct": "advances / deposits * 100",
    "gnpa_pct_filed": "as filed in XBRL (unit as filed)",
    "nnpa_pct_filed": "as filed in XBRL (unit as filed)",
    "car_filed": "capital adequacy ratio as filed (unit as filed)",
    "cet1_filed": "CET1 ratio as filed (unit as filed)",
}
CORP_UNITS = {"revenue": INR_CR, "ebitda": INR_CR, "ebit": INR_CR, "pat": INR_CR, "pat_owners": INR_CR, "fcf": INR_CR, "net_debt": INR_CR,
              "ebitda_margin_pct": PCT, "pat_margin_pct": PCT, "other_income_pct_pbt": PCT, "effective_tax_rate_pct": PCT,
              "roe_pct": PCT, "roce_pct": PCT, "debt_equity": RATIO, "interest_coverage": RATIO, "ocf_ebitda": RATIO, "ocf_pat": RATIO,
              "receivable_days": DAYS, "inventory_days": DAYS, "payable_days": DAYS, "cash_conversion_cycle_days": DAYS,
              "shares_crore": "crore shares", "share_count_change_pct": PCT, "eps_basic": "INR/share"}
BANK_UNITS = {"nii": INR_CR, "pat": INR_CR, "pat_owners": INR_CR, "other_income": INR_CR, "nii_to_avg_assets_pct": PCT, "cost_to_income_pct": PCT,
              "provisions_to_avg_advances_pct": PCT, "roa_pct": PCT, "roe_pct": PCT, "pcr_pct": PCT, "credit_deposit_pct": PCT,
              "gnpa_pct_filed": "as filed", "nnpa_pct_filed": "as filed", "car_filed": "as filed", "cet1_filed": "as filed",
              "shares_crore": "crore shares", "share_count_change_pct": PCT, "eps_basic": "INR/share"}
# a bank cannot truly have zero NPAs or zero capital ratio; consolidated filings often carry 0 for "not reported"
BANK_ZERO_MEANS_MISSING = {"gross_npa", "net_npa", "gnpa_pct", "nnpa_pct", "car", "cet1_ratio"}


def _g(row: dict | None, key: str) -> float | None:
    return None if row is None else fnum(row.get(key))


def _add(*xs: float | None) -> float | None:
    """Sum where every term is known; None if any is missing (never treat missing as 0)."""
    vals = [fnum(x) for x in xs]
    return None if any(v is None for v in vals) else sum(vals)


def _avg(open_v: float | None, close_v: float | None) -> tuple[float | None, bool]:
    if close_v is None:
        return None, False
    if open_v is None:
        return close_v, True
    return (open_v + close_v) / 2, False


def _prev_year_end(d: str) -> str:
    x = dt.date.fromisoformat(d)
    return dt.date(x.year - 1, x.month, x.day).isoformat()


def _shares(row: dict) -> float | None:
    cap, fv = _g(row, "paid_up_capital"), _g(row, "face_value")
    return cap / fv / 1e7 if cap and fv else None


def corporate_year(pl: dict, bs: dict | None, bs_open: dict | None, prev_pl: dict | None) -> dict:
    rec: dict[str, Any] = {"period": pl["period"], "period_end": pl["period_end"]}
    rev, oi, fin, dep = _g(pl, "revenue"), _g(pl, "other_income"), _g(pl, "finance_costs"), _g(pl, "depreciation")
    pbt_be = _g(pl, "pbt_before_exceptional")
    if pbt_be is None and _g(pl, "pbt") is not None:
        pbt_be = _add(_g(pl, "pbt"), -(_g(pl, "exceptional_items") or 0.0)) if _g(pl, "exceptional_items") is not None else None
    pbt, pat, tax = _g(pl, "pbt"), _g(pl, "pat"), _g(pl, "tax")
    pat_owners = _g(pl, "pat_owners") if _g(pl, "pat_owners") is not None else pat
    ebitda = _add(pbt_be, fin, dep, -oi if oi is not None else None)
    ebit = _add(pbt_be, fin)
    rec.update(revenue=rev, ebitda=ebitda, ebit=ebit, pat=pat, pat_owners=pat_owners, eps_basic=_g(pl, "eps_basic"))
    rec["ebitda_margin_pct"] = _pct(safe_div(ebitda, rev))
    rec["pat_margin_pct"] = _pct(safe_div(pat, rev))
    rec["other_income_pct_pbt"] = _pct(safe_div(oi, pbt))
    rec["effective_tax_rate_pct"] = _pct(safe_div(tax, pbt))
    notes = []
    eq_avg, used_close = _avg(_g(bs_open, "equity_owners") or _g(bs_open, "total_equity"), _g(bs, "equity_owners") or _g(bs, "total_equity"))
    if used_close:
        notes.append("ROE/ROCE on closing balances (opening missing)")
    rec["roe_pct"] = _pct(safe_div(pat_owners, eq_avg))
    ce_close = _add(_g(bs, "total_equity"), _g(bs, "borrowings_noncurrent"), _g(bs, "borrowings_current"))
    ce_open = _add(_g(bs_open, "total_equity"), _g(bs_open, "borrowings_noncurrent"), _g(bs_open, "borrowings_current"))
    rec["roce_pct"] = _pct(safe_div(ebit, _avg(ce_open, ce_close)[0]))
    debt = _add(_g(bs, "borrowings_noncurrent"), _g(bs, "borrowings_current"))
    rec["debt_equity"] = safe_div(debt, _g(bs, "total_equity"))
    absent = [k for k in ("other_bank_balances", "current_investments") if _g(bs, k) is None]
    cash_like = _add(_g(bs, "cash"), *[_g(bs, k) for k in ("other_bank_balances", "current_investments") if k not in absent])
    rec["net_debt"] = _add(debt, -cash_like if cash_like is not None else None)
    if absent and rec["net_debt"] is not None:
        notes.append(f"net_debt excludes {absent} (not filed)")
    rec["interest_coverage"] = safe_div(ebit, fin)
    cfo = _g(pl, "cfo")
    rec["ocf_ebitda"] = safe_div(cfo, ebitda)
    rec["ocf_pat"] = safe_div(cfo, pat)
    rec["fcf"] = _add(cfo, -(_g(pl, "capex_ppe")) if _g(pl, "capex_ppe") is not None else None,
                      -(_g(pl, "capex_intangibles") or 0.0))
    cogs = _add(_g(pl, "cost_of_materials") or 0.0, _g(pl, "purchases_stock_in_trade") or 0.0, _g(pl, "change_in_inventories") or 0.0)
    if not cogs:
        cogs = None
        notes.append("no material/purchase lines (services?): inventory and payable days not computed")
    rec["receivable_days"] = _times(safe_div(_g(bs, "trade_receivables_current"), rev), 365)
    rec["inventory_days"] = _times(safe_div(_g(bs, "inventories"), cogs), 365)
    rec["payable_days"] = _times(safe_div(_g(bs, "trade_payables_current"), cogs), 365)
    rec["cash_conversion_cycle_days"] = _add(rec["receivable_days"], rec["inventory_days"], -rec["payable_days"] if rec["payable_days"] is not None else None)
    rec["shares_crore"] = _shares(pl)
    prev_sh = _shares(prev_pl) if prev_pl else None
    rec["share_count_change_pct"] = _pct(safe_div(rec["shares_crore"], prev_sh), minus_one=True)
    rec["notes"] = "; ".join(notes) or None
    return rec


def bank_year(pl: dict, bs: dict | None, bs_open: dict | None, prev_pl: dict | None) -> dict:
    rec: dict[str, Any] = {"period": pl["period"], "period_end": pl["period_end"]}
    nii = _add(_g(pl, "interest_earned"), -_g(pl, "interest_expended") if _g(pl, "interest_expended") is not None else None)
    oi, pat = _g(pl, "other_income"), _g(pl, "pat")
    pat_owners = _g(pl, "pat_owners") if _g(pl, "pat_owners") is not None else pat
    rec.update(nii=nii, other_income=oi, pat=pat, pat_owners=pat_owners, eps_basic=_g(pl, "eps_basic"))
    notes = []
    ta, used = _avg(_g(bs_open, "total_assets"), _g(bs, "total_assets"))
    if used:
        notes.append("averages use closing balances (opening missing)")
    rec["nii_to_avg_assets_pct"] = _pct(safe_div(nii, ta))
    rec["cost_to_income_pct"] = _pct(safe_div(_g(pl, "operating_expenses"), _add(nii, oi)))
    rec["provisions_to_avg_advances_pct"] = _pct(safe_div(_g(pl, "provisions"), _avg(_g(bs_open, "advances"), _g(bs, "advances"))[0]))
    rec["roa_pct"] = _pct(safe_div(pat, ta))
    nw = lambda b: _add(_g(b, "capital"), _g(b, "reserves"))  # noqa: E731
    rec["roe_pct"] = _pct(safe_div(pat_owners, _avg(nw(bs_open), nw(bs))[0]))
    rec["credit_deposit_pct"] = _pct(safe_div(_g(bs, "advances"), _g(bs, "deposits")))
    filed = {k: (None if _g(pl, k) == 0 and k in BANK_ZERO_MEANS_MISSING else _g(pl, k)) for k in ("gross_npa", "net_npa", "gnpa_pct", "nnpa_pct", "car", "cet1_ratio")}
    if any(_g(pl, k) == 0 for k in BANK_ZERO_MEANS_MISSING):
        notes.append("asset-quality/capital fields filed as 0 treated as not reported (common in consolidated filings; use --basis standalone)")
    g, n = filed["gross_npa"], filed["net_npa"]
    rec["pcr_pct"] = _pct(safe_div(_add(g, -n if n is not None else None), g))
    rec["gnpa_pct_filed"], rec["nnpa_pct_filed"] = filed["gnpa_pct"], filed["nnpa_pct"]
    rec["car_filed"], rec["cet1_filed"] = filed["car"], filed["cet1_ratio"]
    rec["shares_crore"] = _shares(pl)
    prev_sh = _shares(prev_pl) if prev_pl else None
    rec["share_count_change_pct"] = _pct(safe_div(rec["shares_crore"], prev_sh), minus_one=True)
    rec["notes"] = "; ".join(notes) or None
    return rec


def _pct(x: float | None, minus_one: bool = False) -> float | None:
    if x is None:
        return None
    return (x - 1) * 100 if minus_one else x * 100


def _times(x: float | None, k: float) -> float | None:
    return None if x is None else x * k


def growth(records: list[dict], items: list[str], spans=(3, 5, 10)) -> dict:
    """CAGR over N fiscal years ending at the latest FY in `records` (ascending)."""
    out: dict = {}
    if not records:
        return out
    by_end = {r["period"]: r for r in records}
    latest = records[-1]
    for item in items:
        out[item] = {}
        for n in spans:
            fy_num = int(latest["period"][2:]) - n
            start = by_end.get(f"FY{fy_num:02d}")
            if start is None:
                out[item][f"{n}y"] = missing(f"needs FY{fy_num:02d}; XBRL history starts {records[0]['period']} (older years: annual reports)", PCT,
                                             source="computed", period=f"FY{fy_num:02d}-{latest['period']}")
                continue
            v, why = cagr(start.get(item), latest.get(item), n)
            out[item][f"{n}y"] = (missing(why, PCT, source="computed") if v is None else
                                  derived(v * 100, PCT, formula=f"({item} {latest['period']} / {item} {start['period']})^(1/{n}) - 1",
                                          inputs={start["period"]: num(start.get(item), INR_CR if item != "eps_basic" else "INR/share", source="data financials",
                                                                       period=start["period"]),
                                                  latest["period"]: num(latest.get(item), INR_CR if item != "eps_basic" else "INR/share", source="data financials",
                                                                        period=latest["period"])},
                                          period=f"{start['period']}-{latest['period']}"))
    return out


def ttm(quarterly: list[dict], items: list[str]) -> dict:
    """Trailing-twelve-month sums from the latest four consecutive quarters."""
    q = sorted(quarterly, key=lambda r: r["period_end"], reverse=True)[:4]
    if len(q) < 4:
        return {i: missing("fewer than 4 quarters available", INR_CR, source="computed") for i in items} | {"quarters": [r["period"] for r in q]}
    ends = [dt.date.fromisoformat(r["period_end"]) for r in q]
    if (ends[0] - ends[3]).days > 300:
        return {i: missing(f"latest 4 quarters are not consecutive: {[r['period'] for r in q]}", INR_CR, source="computed") for i in items}
    out: dict = {"quarters": [r["period"] for r in q]}
    for i in items:
        vals = [fnum(r.get(i)) for r in q]
        unit = "INR/share" if i.startswith("eps") else INR_CR
        out[i] = (missing(f"{i} missing in {[r['period'] for r, v in zip(q, vals) if v is None]}", unit, source="computed") if any(v is None for v in vals)
                  else derived(sum(vals), unit, formula=f"sum of {i} over {', '.join(r['period'] for r in q)}", period=f"TTM to {q[0]['period']}",
                               as_of=q[0]["period_end"]))
    return out


def quarterly_ebitda(row: dict) -> float | None:
    oi = _g(row, "other_income")
    return _add(_g(row, "pbt_before_exceptional"), _g(row, "finance_costs"), _g(row, "depreciation"), -oi if oi is not None else None)


def compute(fin: dict, *, contingent_liabilities_cr: float | None = None, contingent_source: str | None = None) -> dict:
    """All ratios from a `data financials` result."""
    if not fin.get("annual"):
        raise InputError("financials input has no annual table; run `data financials` first")
    is_bank = bool(fin.get("is_bank_format"))
    annual = frame(fin["annual"]).to_dict("records")
    annual = sorted(annual, key=lambda r: r["period_end"])
    bs_rows = {r["period_end"]: r for r in frame(fin.get("balance_sheet")).to_dict("records")}
    recs = []
    for i, pl in enumerate(annual):
        bs = bs_rows.get(pl["period_end"])
        bs_open = bs_rows.get(_prev_year_end(pl["period_end"]))
        prev = annual[i - 1] if i > 0 and annual[i - 1]["period"] == f"FY{int(pl['period'][2:]) - 1:02d}" else None
        recs.append((bank_year if is_bank else corporate_year)(pl, bs, bs_open, prev))
    formulas = BANK_FORMULAS if is_bank else CORP_FORMULAS
    units = BANK_UNITS if is_bank else CORP_UNITS
    cols = ["period", "period_end", *[c for c in units if any(r.get(c) is not None for r in recs) or c in formulas], "notes"]
    cols = list(dict.fromkeys(cols))
    src = f"computed from NSE XBRL results ({fin.get('basis', 'basis unknown')})"
    out = {
        "basis": fin.get("basis"), "is_bank_format": is_bank,
        "annual_ratios": records_table(list(reversed(recs)), cols, {c: units[c] for c in cols if c in units}, source=src,
                                       notes="null = input not filed or ratio undefined (never imputed); see formulas"),
        "formulas": formulas,
        "growth_cagr": growth(recs, ["nii", "pat_owners", "eps_basic"] if is_bank else ["revenue", "ebitda", "pat_owners", "eps_basic"]),
    }
    q = frame(fin.get("quarterly")).to_dict("records")
    if not is_bank:
        for r in q:
            r["ebitda"] = quarterly_ebitda(r)
        out["ttm"] = ttm(q, ["revenue", "ebitda", "pat", "pat_owners", "eps_basic"])
        qm = [{"period": r["period"], "period_end": r["period_end"], "revenue": r.get("revenue"),
               "ebitda_margin_pct": _pct(safe_div(r["ebitda"], r.get("revenue"))), "pat_margin_pct": _pct(safe_div(r.get("pat"), r.get("revenue")))}
              for r in sorted(q, key=lambda r: r["period_end"], reverse=True)]
        out["quarterly_margins"] = records_table(qm, ["period", "period_end", "revenue", "ebitda_margin_pct", "pat_margin_pct"],
                                                 {"revenue": INR_CR, "ebitda_margin_pct": PCT, "pat_margin_pct": PCT}, source=src)
        latest_bs = max(bs_rows.values(), key=lambda r: r["period_end"]) if bs_rows else None
        nw = _g(latest_bs, "total_equity")
        if contingent_liabilities_cr is None:
            out["contingent_liabilities_pct_networth"] = missing("contingent liabilities are not in results XBRL; pass --contingent-liabilities with the annual-report figure and cite its page", PCT)
        else:
            out["contingent_liabilities_pct_networth"] = derived(safe_div(contingent_liabilities_cr, nw) * 100 if nw else None, PCT,
                                                                 formula="contingent_liabilities / total_equity * 100",
                                                                 inputs={"contingent_liabilities": num(contingent_liabilities_cr, INR_CR, source=contingent_source or "caller-supplied (cite!)"),
                                                                         "total_equity": num(nw, INR_CR, source="data financials", as_of=latest_bs["period_end"] if latest_bs else None)})
    else:
        out["ttm"] = ttm(q, ["interest_earned", "pat", "pat_owners", "eps_basic"])
        out["not_in_xbrl"] = {k: missing(v, PCT) for k, v in {
            "nim": "needs average interest-earning assets: take from the investor presentation (cite page)",
            "casa_ratio": "not in results XBRL: take from the investor presentation (cite page)",
            "credit_cost": "needs credit-only provisions: take from the presentation; provisions_to_avg_advances_pct is a proxy"}.items()}
    out["dilution_history"] = records_table([{"period": r["period"], "shares_crore": r.get("shares_crore"), "share_count_change_pct": r.get("share_count_change_pct")}
                                             for r in reversed(recs)], ["period", "shares_crore", "share_count_change_pct"],
                                            {"shares_crore": "crore shares", "share_count_change_pct": PCT}, source=src,
                                            notes="from paid-up capital / face value; bonus and split change this without dilution, check corporate actions")
    return out


def load_financials(args) -> dict:
    if getattr(args, "input", None):
        fin = load_json(args.input)
    else:
        from ..common.entity import get_entity
        from ..data.financials import statements
        e = get_entity(args.query)
        fin = {"identity": e.identity(), "basis": args.basis, **statements(e, args.basis, args.quarters, args.years)}
    if fin.get("status") not in (None, "ok"):
        raise InputError(f"financials input has status {fin.get('status')}: {fin.get('error')}")
    return fin


def cmd_ratios(args) -> dict:
    fin = load_financials(args)
    return {"identity": fin.get("identity"), **compute(fin, contingent_liabilities_cr=args.contingent_liabilities, contingent_source=args.contingent_source)}


def add_financials_args(p) -> None:
    p.add_argument("query", nargs="?", help="NSE symbol or ISIN (omit if --input is given)")
    p.add_argument("--input", help="JSON written by `data financials ... --out FILE` (no fetching)")
    p.add_argument("--basis", choices=("consolidated", "standalone"), default="consolidated")
    p.add_argument("--quarters", type=int, default=12)
    p.add_argument("--years", type=int, default=11)


def register(sub, leaf) -> None:
    p = leaf(sub, "ratios", "ROCE/ROE/ROA, margins, CAGRs, leverage, cash conversion, working-capital days, dilution; bank metrics")
    add_financials_args(p)
    p.add_argument("--contingent-liabilities", type=float, help="INR crore, from the annual report (cite with --contingent-source)")
    p.add_argument("--contingent-source", help="e.g. 'AR FY26 p.212'")
    p.set_defaults(func=cmd_ratios)
