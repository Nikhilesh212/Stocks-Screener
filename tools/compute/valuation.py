"""`compute valuation`: P/E, EV/EBITDA, P/B and FCF yield now, against own history and a peer set.

History is sampled at month ends. At each sample date t only filings that were
public by t are used: a quarter counts from period_end + 45 days (Q4/annual:
+60 days), the SEBI LODR deadlines. Market cap at t = adj_close(t) x filed
shares x share_basis_factor(filing period end), so a bonus or split between the
filing and t cannot distort it. Banks: P/E and P/B only.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from ..common.errors import InputError
from ..common.provenance import derived, missing, num
from ..common.units import INR, INR_CR, PCT, RATIO
from ._util import frame, percentile_rank, records_table, safe_div, share_actions, unadjusted_gaps
from .ratios import _add, _g, _shares, quarterly_ebitda, share_basis_factor

LAG_DAYS = {"q": 45, "q4": 60}
MULTIPLES = ("pe", "pb", "ev_ebitda", "fcf_yield_pct")
FORMULAS = {
    "market_cap": "adj_close(t) x filed shares (paid-up / face value) x share_basis_factor(filing period end)",
    "pe": "market_cap / TTM pat_owners (latest 4 consecutive quarters public by t)",
    "pb": "market_cap / equity_owners (banks: capital + reserves) at the latest balance sheet public by t",
    "ev": "market_cap + borrowings - cash - other bank balances - current investments (minority interest not added)",
    "ev_ebitda": "ev / TTM EBITDA (EBITDA excludes other income)",
    "fcf_yield_pct": "(cfo - capex) of the latest FY public by t / market_cap * 100",
}


def public_from(period_end: str) -> dt.date:
    d = dt.date.fromisoformat(period_end)
    return d + dt.timedelta(days=LAG_DAYS["q4"] if d.month == 3 else LAG_DAYS["q"])


def _avail(rows: list[dict], t: dt.date | None) -> list[dict]:
    """Rows public by t (all rows if t is None), newest first."""
    keep = [r for r in rows if t is None or public_from(r["period_end"]) <= t]
    return sorted(keep, key=lambda r: r["period_end"], reverse=True)


def fundamentals_at(fin: dict, actions: list, t: dt.date | None, is_bank: bool) -> dict:
    """What an investor could know at t: TTM earnings, book, net debt, FCF, share count (today's basis)."""
    q = _avail(frame(fin.get("quarterly")).to_dict("records"), t)
    a = _avail(frame(fin.get("annual")).to_dict("records"), t)
    bs = _avail(frame(fin.get("balance_sheet")).to_dict("records"), t)
    out: dict[str, Any] = {"notes": []}
    last4 = q[:4]
    if len(last4) == 4 and (dt.date.fromisoformat(last4[0]["period_end"]) - dt.date.fromisoformat(last4[3]["period_end"])).days <= 300:
        pats = [_g(r, "pat_owners") if _g(r, "pat_owners") is not None else _g(r, "pat") for r in last4]
        out["ttm_pat_owners"] = None if any(v is None for v in pats) else sum(pats)
        ebs = [quarterly_ebitda(r) for r in last4]
        out["ttm_ebitda"] = None if is_bank or any(v is None for v in ebs) else sum(ebs)
        out["ttm_quarters"] = [r["period"] for r in last4]
    else:
        out["ttm_pat_owners"] = out["ttm_ebitda"] = None
        out["notes"].append("no 4 consecutive public quarters")
    sh_row = next((r for r in q + a if _shares(r) is not None), None)
    out["shares_today_basis_crore"] = _shares(sh_row) * share_basis_factor(sh_row["period_end"], actions) if sh_row else None
    out["shares_from"] = sh_row["period"] if sh_row else None
    b = bs[0] if bs else None
    out["bs_as_of"] = b["period_end"] if b else None
    if is_bank:
        out["book"] = _add(_g(b, "capital"), _g(b, "reserves"))
        out["net_debt"] = out["fcf"] = None
    else:
        out["book"] = _g(b, "equity_owners") if _g(b, "equity_owners") is not None else _g(b, "total_equity")
        debt = _add(_g(b, "borrowings_noncurrent"), _g(b, "borrowings_current"))
        cash = _add(_g(b, "cash"), *[_g(b, k) for k in ("other_bank_balances", "current_investments") if _g(b, k) is not None])
        out["net_debt"] = _add(debt, -cash if cash is not None else None)
        fy = a[0] if a else None
        cfo, capex = _g(fy, "cfo"), _g(fy, "capex_ppe")
        out["fcf"] = _add(cfo, -capex if capex is not None else None, -(_g(fy, "capex_intangibles") or 0.0))
        out["fcf_period"] = fy["period"] if fy else None
    return out


def multiples(price_adj: float, f: dict, is_bank: bool) -> dict:
    mcap = price_adj * f["shares_today_basis_crore"] if f.get("shares_today_basis_crore") else None
    pat = f.get("ttm_pat_owners")
    m = {"market_cap": mcap,
         "pe": safe_div(mcap, pat) if pat is not None and pat > 0 else None,
         "pb": safe_div(mcap, f.get("book")) if (f.get("book") or 0) > 0 else None}
    if is_bank:
        m["ev"] = m["ev_ebitda"] = m["fcf_yield_pct"] = None
        return m
    ev = _add(mcap, f.get("net_debt"))
    eb = f.get("ttm_ebitda")
    m["ev"] = ev
    m["ev_ebitda"] = safe_div(ev, eb) if eb is not None and eb > 0 else None
    fy = safe_div(f.get("fcf"), mcap)
    m["fcf_yield_pct"] = fy * 100 if fy is not None else None
    return m


def month_end_dates(px: pd.DataFrame) -> list[dt.date]:
    d = pd.Series(pd.to_datetime(px["date"]))
    return [x.date() for x in d.groupby(d.dt.to_period("M")).max()]


def history(fin: dict, px: pd.DataFrame, actions: list, is_bank: bool) -> list[dict]:
    closes = dict(zip(px["date"], px["adj_close"]))
    rows = []
    for t in month_end_dates(px):
        f = fundamentals_at(fin, actions, t, is_bank)
        rows.append({"date": t.isoformat(), "adj_close": float(closes[t]), **multiples(float(closes[t]), f, is_bank)})
    return rows


def _why_null(name: str, f: dict, is_bank: bool) -> str:
    if is_bank and name in ("ev_ebitda", "fcf_yield_pct"):
        return "not meaningful for banks (debt is raw material)"
    if name == "pe":
        return "TTM earnings missing or not positive" if f.get("ttm_pat_owners") is None or f["ttm_pat_owners"] <= 0 else "share count missing"
    if name == "pb":
        return "book value missing or not positive"
    if name == "ev_ebitda":
        return "TTM EBITDA or net debt missing, or EBITDA not positive"
    return "FCF (cfo or capex) not filed"


def valuation(fin: dict, px: pd.DataFrame, actions: list | None, *, peers: dict[str, dict] | None = None) -> dict:
    if not fin.get("quarterly"):
        raise InputError("financials have no quarterly table; run `data financials` first")
    is_bank = bool(fin.get("is_bank_format"))
    actions = actions or []
    px = px.dropna(subset=["adj_close"]).sort_values("date").reset_index(drop=True)
    if px.empty:
        raise InputError("no cached prices; run `data prices` first")
    asof = px["date"].iloc[-1]
    a = asof.isoformat()
    f_now = fundamentals_at(fin, actions, None, is_bank)
    now = multiples(float(px["adj_close"].iloc[-1]), f_now, is_bank)
    inputs = {
        "price": num(float(px["close"].iloc[-1]), INR, as_of=a, source="NSE security-wise history (data prices)"),
        "shares_today_basis": derived(f_now["shares_today_basis_crore"], "crore shares", formula="paid_up_capital / face_value / 1e7 x share_basis_factor",
                                      period=f_now["shares_from"]),
        "ttm_pat_owners": derived(f_now["ttm_pat_owners"], INR_CR, formula="sum of 4 quarters", period=", ".join(f_now.get("ttm_quarters", []))),
        "book": num(f_now["book"], INR_CR, as_of=f_now["bs_as_of"], source="data financials (balance sheet)"),
    }
    if not is_bank:
        inputs["ttm_ebitda"] = derived(f_now["ttm_ebitda"], INR_CR, formula="sum of 4 quarters of EBITDA (ex other income)",
                                       period=", ".join(f_now.get("ttm_quarters", [])))
        inputs["net_debt"] = num(f_now["net_debt"], INR_CR, as_of=f_now["bs_as_of"], source="data financials (balance sheet)")
        inputs["fcf"] = derived(f_now["fcf"], INR_CR, formula="cfo - capex", period=f_now.get("fcf_period"))
    current = {"market_cap": derived(now["market_cap"], INR_CR, formula=FORMULAS["market_cap"], as_of=a)}
    if not is_bank:
        current["ev"] = derived(now["ev"], INR_CR, formula=FORMULAS["ev"], as_of=a)
    units = {"pe": RATIO, "pb": RATIO, "ev_ebitda": RATIO, "fcf_yield_pct": PCT}
    for k in MULTIPLES:
        current[k] = (derived(now[k], units[k], formula=FORMULAS[k], as_of=a) if now[k] is not None
                      else missing(_why_null(k, f_now, is_bank), units[k], source="computed", formula=FORMULAS[k]))

    hist = history(fin, px, actions, is_bank)
    first = dt.date.fromisoformat(hist[0]["date"])
    vs_own: dict = {}
    for k in MULTIPLES:
        vs_own[k] = {}
        for yrs in (5, 10):
            start = asof - dt.timedelta(days=int(365.25 * yrs))
            sample = [h[k] for h in hist if dt.date.fromisoformat(h["date"]) > start and h[k] is not None]
            short = first > start + dt.timedelta(days=31)
            note = (f"only {len(sample)} monthly observations from {first}: shorter than {yrs}y "
                    f"(extend with `data prices SYM --years {yrs}`; XBRL financials start about FY19)") if short else None
            if now[k] is None:
                vs_own[k][f"{yrs}y"] = missing(_why_null(k, f_now, is_bank), PCT, source="computed")
                continue
            if len(sample) < 12:
                why = f"fewer than 12 monthly observations ({len(sample)})"
                vs_own[k][f"{yrs}y"] = missing(f"{why}; {note}" if note else why, PCT, source="computed")
                continue
            s = pd.Series(sample)
            vs_own[k][f"{yrs}y"] = {
                "percentile": derived(percentile_rank(now[k], sample), PCT, formula=f"share of monthly {k} values <= current (ties half)",
                                      period=f"{max(first, start)}..{a}", notes=note),
                "n_obs": num(len(sample), "count", source="computed"),
                "median": derived(float(s.median()), units[k], formula=f"median monthly {k}"),
                "min": derived(float(s.min()), units[k], formula=f"min monthly {k}"),
                "max": derived(float(s.max()), units[k], formula=f"max monthly {k}"),
            }
    out = {"as_of": a, "is_bank_format": is_bank, "current": current, "inputs": inputs, "formulas": FORMULAS,
           "vs_own_history": vs_own,
           "history_monthly": records_table(hist, ["date", "adj_close", "market_cap", *MULTIPLES],
                                            {"adj_close": INR, "market_cap": INR_CR, **units}, source="computed",
                                            notes="month-end samples; fundamentals public by each date (+45d quarters, +60d Q4); null = undefined")}
    if f_now["notes"]:
        out["notes"] = f_now["notes"]
    gaps = unadjusted_gaps(px)
    if gaps:
        out["warnings"] = gaps
    if peers is not None:
        out["vs_peers"] = peer_compare(now, peers, units)
    return out


def peer_compare(now: dict, peers: dict[str, dict], units: dict) -> dict:
    """Peers' current multiples, the peer median, and where this company sits among them. The peer set is the caller's."""
    rows = [{"symbol": s, **{k: (p.get(k) if isinstance(p, dict) else None) for k in MULTIPLES}, "note": p.get("error") if isinstance(p, dict) else None}
            for s, p in peers.items()]
    out: dict = {"peers": records_table(rows, ["symbol", *MULTIPLES, "note"], units, source="computed (same method, each peer's cache)",
                                        notes="peer set supplied by the caller")}
    for k in MULTIPLES:
        vals = [r[k] for r in rows if r[k] is not None]
        if now[k] is None or not vals:
            out[k] = missing(f"needs this company's {k} and at least one peer value ({len(vals)} peers have it)", PCT, source="computed")
            continue
        out[k] = {"percentile_vs_peers": derived(percentile_rank(now[k], vals), PCT, formula=f"share of peer {k} values <= this company's"),
                  "peer_median": derived(float(pd.Series(vals).median()), units[k], formula=f"median of peer {k}"),
                  "n_peers": num(len(vals), "count", source="computed")}
    return out


def _load(query: str, basis: str) -> tuple[dict, dict, pd.DataFrame, list | None, str]:
    from ..common.entity import get_entity
    from ..data.financials import statements
    from ..data.prices import load_adjusted
    e = get_entity(query)
    fin = {"basis": basis, **statements(e, basis, 12, 11)}
    px = load_adjusted(e.isin)
    first = min((r[1] for r in fin.get("annual", {}).get("rows", [])), default=None)
    q_first = min((r[1] for r in fin.get("quarterly", {}).get("rows", [])), default=None)
    actions, note = share_actions(e.identity(), min(x for x in (first, q_first) if x) if (first or q_first) else None)
    return e.identity(), fin, px, actions, note


def cmd_valuation(args) -> dict:
    ident, fin, px, actions, note = _load(args.query, args.basis)
    peers = None
    if args.peers:
        peers = {}
        for s in [x.strip() for x in args.peers.split(",") if x.strip()]:
            try:
                _, pf, ppx, pa, _ = _load(s, args.basis)
                pbank = bool(pf.get("is_bank_format"))
                pnow = multiples(float(ppx.dropna(subset=["adj_close"])["adj_close"].iloc[-1]), fundamentals_at(pf, pa or [], None, pbank), pbank)
                peers[s] = pnow
            except Exception as ex:  # one peer's missing cache must not sink the comparison
                peers[s] = {"error": f"{type(ex).__name__}: {ex}"}
    out = valuation(fin, px, actions, peers=peers)
    return {"identity": ident, "basis": args.basis, "share_basis_note": note, **out}


def register(sub, leaf) -> None:
    p = leaf(sub, "valuation", "P/E, EV/EBITDA, P/B, FCF yield now; percentile vs own 5/10y monthly history and vs a caller-supplied peer set")
    p.add_argument("query", help="NSE symbol or ISIN (uses cached prices and financials)")
    p.add_argument("--basis", choices=("consolidated", "standalone"), default="consolidated")
    p.add_argument("--peers", help="comma-separated peer symbols chosen by the analyst, e.g. 'KFINTECH,CDSL'")
    p.set_defaults(func=cmd_valuation)
