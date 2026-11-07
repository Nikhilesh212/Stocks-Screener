"""`compute base_rates`: forward-return distribution for an index, conditional on its starting valuation.

Method (stated in every output):
* sample month-end dates; forward return = TRI(first session >= t + H months) / TRI(t) - 1;
* state at t: index P/E (methodology-adjusted, below), P/B, dividend yield, trailing 12-month
  return, drawdown from the running peak;
* P/E percentile = rank of P/E(t) within the whole sample (look-ahead: the full history
  defines the buckets), bucketed into quantiles; the current P/E's bucket is the one reported;
* monthly samples with an H-month horizon overlap: n_obs overstates information by about
  H times. Confidence intervals use n_independent = n_obs / H (months) and the naive
  interval is shown beside it only to make the gap visible.

Index P/E methodology break: NSE moved index P/E from standalone to consolidated
earnings on 31-Mar-2021. In the niftyindices series this is a one-day jump in implied
earnings (TRI change minus P/E change) of about +18% for Nifty 50 and Nifty 500, with no
matching price move. "spliced" divides pre-break P/E by that measured jump (an
approximation: the consolidated/standalone gap was not constant); "post_break" uses only
data from the break; "raw" ignores it (not comparable across the break).
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from ..common.errors import InputError
from ..common.provenance import derived, num
from ..common.units import COUNT, PCT, RATIO
from ._util import load_mandate, mean_ci, records_table, wilson_ci

PE_BREAK_DATE = dt.date(2021, 3, 31)
PE_BREAK_SOURCES = ("measured in the niftyindices P/E and TRI series (one-day implied-earnings jump); "
                    "secondary report: https://cafemutual.com/news/press-news/21438-nifty-valuation-to-become-12-cheaper-from-march-31 "
                    "(no NSE Indices circular located 2026-11-08)")
STATE_VARS = ("pe", "pb", "div_yield", "ret_12m", "drawdown")


def implied_earnings_jump(df: pd.DataFrame, day: dt.date) -> float | None:
    """exp(change in log TRI - change in log P/E) on `day`: >1 means earnings stepped up."""
    d = df.dropna(subset=["tri", "pe"]).sort_values("date").reset_index(drop=True)
    idx = d.index[d["date"] == day]
    if len(idx) == 0 or idx[0] == 0:
        return None
    i = idx[0]
    return float((d.at[i, "tri"] / d.at[i - 1, "tri"]) / (d.at[i, "pe"] / d.at[i - 1, "pe"]))


def large_earnings_jumps(df: pd.DataFrame, threshold: float = 0.10) -> list[dict]:
    d = df.dropna(subset=["tri", "pe"]).sort_values("date")
    de = np.log(d["tri"]).diff() - np.log(d["pe"]).diff()
    hits = d.loc[de.abs() > threshold, "date"]
    return [{"date": x.isoformat(), "implied_earnings_change_pct": num(float(np.expm1(de.loc[i]) * 100), PCT, source="computed from niftyindices TRI and P/E")}
            for i, x in hits.items()]


def adjust_pe(df: pd.DataFrame, method: str) -> tuple[pd.DataFrame, float | None]:
    d = df.copy()
    jump = implied_earnings_jump(d, PE_BREAK_DATE)
    if method == "raw":
        return d, jump
    if method == "post_break":
        return d[d["date"] >= PE_BREAK_DATE].copy(), jump
    if method == "spliced":
        if jump is None:
            raise InputError(f"series does not contain {PE_BREAK_DATE} and the session before it; cannot splice P/E")
        d.loc[d["date"] < PE_BREAK_DATE, "pe"] = d.loc[d["date"] < PE_BREAK_DATE, "pe"] / jump
        return d, jump
    raise InputError(f"unknown --pe-method {method}")


def monthly_samples(df: pd.DataFrame, horizon_months: int) -> pd.DataFrame:
    """Month-end samples with state variables and the forward H-month TRI return."""
    d = df.dropna(subset=["tri"]).sort_values("date").reset_index(drop=True)
    d["date"] = pd.to_datetime(d["date"])
    s = d.set_index("date")
    s["peak"] = s["tri"].cummax()
    s["drawdown"] = (s["tri"] / s["peak"] - 1) * 100
    month_end = s.groupby(s.index.to_period("M")).tail(1)
    out = []
    dates = s.index
    for t, row in month_end.iterrows():
        target = t + pd.DateOffset(months=horizon_months)
        j = dates.searchsorted(target)
        fwd = None
        if j < len(dates) and (dates[j] - target).days <= 7:
            fwd = (s["tri"].iat[j] / row["tri"] - 1) * 100
        back = t - pd.DateOffset(months=12)
        k = dates.searchsorted(back)
        ret12 = (row["tri"] / s["tri"].iat[k] - 1) * 100 if k < len(dates) and (dates[k] - back).days <= 7 and dates[k] < t else None
        out.append({"date": t.date(), "pe": row.get("pe"), "pb": row.get("pb"), "div_yield": row.get("div_yield"), "ret_12m": ret12,
                    "drawdown": row["drawdown"], "fwd_return_pct": fwd})
    return pd.DataFrame(out)


def summarise(fwd: np.ndarray, horizon_months: int) -> dict:
    """Distribution stats with overlap-corrected and naive intervals (all returns in %)."""
    n = len(fwd)
    if n == 0:
        return {"n_obs": 0}
    n_ind = max(n / horizon_months, 1.0)
    pos = float(np.mean(fwd > 0))
    lo, hi = mean_ci(fwd, n_ind)
    nlo, nhi = mean_ci(fwd, n)
    plo, phi = wilson_ci(pos, n_ind)
    q = np.percentile(fwd, [10, 25, 50, 75, 90])
    return {"n_obs": n, "n_independent": round(n_ind, 1), "mean": float(np.mean(fwd)), "median": float(q[2]),
            "p10": float(q[0]), "p25": float(q[1]), "p75": float(q[3]), "p90": float(q[4]),
            "min": float(np.min(fwd)), "max": float(np.max(fwd)),
            "share_positive_pct": pos * 100, "mean_ci95_lo": lo, "mean_ci95_hi": hi,
            "share_positive_ci95_lo_pct": plo * 100, "share_positive_ci95_hi_pct": phi * 100,
            "naive_mean_ci95_lo": nlo, "naive_mean_ci95_hi": nhi}


def apply_where(samples: pd.DataFrame, where: list[str] | None) -> tuple[pd.DataFrame, list[str]]:
    applied = []
    for w in where or []:
        try:
            col, lo, hi = w.split(":")
        except ValueError as e:
            raise InputError(f"--where needs COL:LO:HI (blank = open), got {w!r}") from e
        if col not in STATE_VARS:
            raise InputError(f"--where column must be one of {STATE_VARS}")
        m = samples[col].notna()
        if lo:
            m &= samples[col] >= float(lo)
        if hi:
            m &= samples[col] < float(hi)
        samples = samples[m]
        applied.append(f"{lo or '-inf'} <= {col} < {hi or 'inf'}")
    return samples, applied


def base_rates(df: pd.DataFrame, *, horizon_months: int = 12, buckets: int = 5, pe_method: str = "spliced",
               where: list[str] | None = None, index_name: str = "NIFTY 500") -> dict:
    if df.empty or df["tri"].notna().sum() < 300 or df["pe"].notna().sum() < 300:
        raise InputError("need a long TRI and P/E history; run `data index history NAME --from 1999-01-01 --parts tri,pepb`")
    adj, jump = adjust_pe(df, pe_method)
    samples = monthly_samples(adj, horizon_months)
    latest = samples.dropna(subset=["pe"]).iloc[-1]
    hist = samples.dropna(subset=["pe"])
    pct_rank = hist["pe"].rank(pct=True) * 100
    samples = samples.assign(pe_percentile=pct_rank)
    edges = np.linspace(0, 100, buckets + 1)
    current_pct = float((hist["pe"] < latest["pe"]).mean() * 100 + (hist["pe"] == latest["pe"]).mean() * 50)
    current_bucket = min(max(int(np.searchsorted(edges, current_pct, side="left")) - 1, 0), buckets - 1)
    usable = samples.dropna(subset=["fwd_return_pct", "pe_percentile"])
    usable, applied = apply_where(usable, where)
    rows = []
    for b in range(buckets):
        lo, hi = edges[b], edges[b + 1]
        sel = usable[(usable["pe_percentile"] > lo) & (usable["pe_percentile"] <= hi)] if b else usable[usable["pe_percentile"] <= hi]
        st = summarise(sel["fwd_return_pct"].to_numpy(), horizon_months)
        pe_lo = float(hist["pe"].quantile(lo / 100))
        pe_hi = float(hist["pe"].quantile(hi / 100))
        rows.append({"bucket": f"P/E pct {lo:.0f}-{hi:.0f}", "pe_from": pe_lo, "pe_to": pe_hi, "is_current": b == current_bucket, **st})
    cols = ["bucket", "pe_from", "pe_to", "is_current", "n_obs", "n_independent", "mean", "median", "p10", "p90", "share_positive_pct",
            "mean_ci95_lo", "mean_ci95_hi", "share_positive_ci95_lo_pct", "share_positive_ci95_hi_pct"]
    ret_units = {c: PCT for c in ("mean", "median", "p10", "p90", "share_positive_pct", "mean_ci95_lo", "mean_ci95_hi",
                                   "share_positive_ci95_lo_pct", "share_positive_ci95_hi_pct")}
    src = f"computed from niftyindices {index_name} TRI and P/E history"
    first, last = samples["date"].iloc[0].isoformat(), samples["date"].iloc[-1].isoformat()
    cur = rows[current_bucket]
    uncond = summarise(usable["fwd_return_pct"].to_numpy(), horizon_months)

    def stat_block(st: dict, label: str) -> dict:
        if not st.get("n_obs"):
            return {"n_obs": num(0, COUNT, source="computed"), "note": f"no observations for {label}"}
        blk = {k: derived(st[k], PCT, formula=f"{k} of {horizon_months}-month forward TRI returns, {label}", period=f"{first}..{last}")
               for k in ("mean", "median", "p10", "p25", "p75", "p90", "min", "max", "share_positive_pct")}
        blk["mean_ci95"] = {"lo": derived(st["mean_ci95_lo"], PCT, formula="t-interval with n_independent - 1 dof"),
                            "hi": derived(st["mean_ci95_hi"], PCT, formula="t-interval with n_independent - 1 dof")}
        blk["share_positive_ci95"] = {"lo": derived(st["share_positive_ci95_lo_pct"], PCT, formula="Wilson interval with n_independent"),
                                      "hi": derived(st["share_positive_ci95_hi_pct"], PCT, formula="Wilson interval with n_independent")}
        blk["naive_mean_ci95_overlapping"] = {"lo": derived(st["naive_mean_ci95_lo"], PCT, formula="t-interval treating every overlapping month as independent (TOO NARROW)"),
                                             "hi": derived(st["naive_mean_ci95_hi"], PCT, formula="t-interval treating every overlapping month as independent (TOO NARROW)")}
        blk["n_obs"] = num(st["n_obs"], COUNT, source="computed", notes="overlapping monthly windows")
        blk["n_independent"] = num(st["n_independent"], COUNT, source="computed", notes=f"n_obs / {horizon_months}: roughly the non-overlapping windows")
        return blk

    break_note = {"date": PE_BREAK_DATE.isoformat(), "evidence": PE_BREAK_SOURCES, "method_used": pe_method,
                  "implied_earnings_jump": num(None if jump is None else (jump - 1) * 100, PCT, source="computed", as_of=PE_BREAK_DATE.isoformat(),
                                               notes="TRI change / P/E change on the break date, minus 1")}
    return {
        "index": index_name, "horizon_months": num(horizon_months, "months", source="config/mandate.yaml or --horizon"),
        "sample": {"from": first, "to": last, "sampling": "month-end", "conditions": applied},
        "current_state": {"date": latest["date"].isoformat(),
                          "pe_adjusted": num(float(latest["pe"]), RATIO, as_of=latest["date"].isoformat(), source=src,
                                             notes=f"P/E after '{pe_method}' methodology handling"),
                          "pe_percentile": derived(current_pct, PCT, formula="share of month-end P/E samples below current (ties half)", as_of=latest["date"].isoformat()),
                          "bucket": cur["bucket"],
                          "ret_12m": num(None if pd.isna(latest["ret_12m"]) else float(latest["ret_12m"]), PCT, source=src, as_of=latest["date"].isoformat()),
                          "drawdown": num(float(latest["drawdown"]), PCT, source=src, as_of=latest["date"].isoformat())},
        "conditional_on_current_bucket": stat_block(cur, f"starting P/E in {cur['bucket']}"),
        "unconditional": stat_block(uncond, "all start dates"),
        "by_pe_bucket": records_table(rows, cols, {"pe_from": RATIO, "pe_to": RATIO, **ret_units}, source=src,
                                      notes=f"{horizon_months}-month forward TRI returns in %; n_independent = n_obs/{horizon_months}"),
        "pe_methodology_break": break_note,
        "other_large_one_day_earnings_jumps": large_earnings_jumps(df),
        "warnings": [
            f"Overlapping windows: {uncond.get('n_obs', 0)} monthly observations carry only about {uncond.get('n_independent', 0)} independent "
            f"{horizon_months}-month outcomes. Use n_independent and the overlap-corrected intervals, not n_obs.",
            "Bucket edges use the full sample (look-ahead): an investor in, say, 2004 could not have known these percentiles.",
            "Index P/E before 31-Mar-2021 used standalone earnings; see pe_methodology_break.",
            "Base rates describe the index's past, not any single stock's future.",
        ],
    }


def cmd_base_rates(args) -> dict:
    from ..data.index import load_index
    df = load_index(args.index)
    horizon = args.horizon or int(load_mandate().get("horizon_months") or 12)
    return base_rates(df, horizon_months=horizon, buckets=args.buckets, pe_method=args.pe_method, where=args.where, index_name=args.index.upper())


def register(sub, leaf) -> None:
    p = leaf(sub, "base_rates", "Index forward-return distribution conditional on starting P/E percentile (n, CIs, overlap warning)")
    p.add_argument("--index", default="NIFTY 500", help="index with cached TRI + P/E history (NIFTY 500, NIFTY 50)")
    p.add_argument("--horizon", type=int, help="months (default: mandate horizon_months)")
    p.add_argument("--buckets", type=int, default=5, help="number of P/E percentile buckets")
    p.add_argument("--pe-method", choices=("spliced", "post_break", "raw"), default="spliced",
                   help="handling of the 31-Mar-2021 standalone->consolidated P/E break")
    p.add_argument("--where", action="append", help="extra state filter COL:LO:HI, COL in pe,pb,div_yield,ret_12m,drawdown (repeatable)")
    p.set_defaults(func=cmd_base_rates)
