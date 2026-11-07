"""`compute technicals`: trend, 52-week range, relative strength, volatility, drawdown, liquidity.

Reads the adjusted price parquet written by `data prices` and the index parquet
written by `data index history`. Facts only: distances and returns, no signals.
Sessions, not calendar days: 50/200-DMA = 50/200 sessions; 52 weeks = 365 calendar days.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from ..common.errors import InputError
from ..common.provenance import derived, missing, num
from ..common.units import INR, INR_CR, PCT, RATIO
from ._util import unadjusted_gaps

SRC = "computed from NSE adjusted daily prices (data prices)"


def _ret_over(series: pd.Series, dates: pd.Series, end: dt.date, months: int) -> tuple[float | None, dt.date | None]:
    start_target = (pd.Timestamp(end) - pd.DateOffset(months=months)).date()
    idx = dates.searchsorted(start_target)
    if idx >= len(dates) or (dates.iloc[idx] - start_target).days > 7:
        return None, None
    end_idx = dates.searchsorted(end, side="right") - 1
    return float(series.iloc[end_idx] / series.iloc[idx] - 1), dates.iloc[idx]


def max_drawdown(values: np.ndarray, dates: list) -> tuple[float, object, object]:
    """Largest peak-to-trough fall (negative fraction) with its peak and trough dates."""
    peak_i, best, best_peak, best_trough = 0, 0.0, 0, 0
    for i, v in enumerate(values):
        if v > values[peak_i]:
            peak_i = i
        dd = v / values[peak_i] - 1
        if dd < best:
            best, best_peak, best_trough = dd, peak_i, i
    return best, dates[best_peak], dates[best_trough]


def realised_vol(closes: np.ndarray) -> float | None:
    """Annualised stdev of daily log returns (252 sessions a year)."""
    if len(closes) < 21:
        return None
    r = np.diff(np.log(closes))
    return float(np.std(r, ddof=1) * math.sqrt(252))


def technicals(px: pd.DataFrame, index_df: pd.DataFrame | None = None, *, index_name: str = "NIFTY 500", dd_years: float = 3.0) -> dict:
    df = px.dropna(subset=["adj_close"]).sort_values("date").reset_index(drop=True)
    if len(df) < 20:
        raise InputError("fewer than 20 price rows cached; run `data prices SYMBOL --years 3`")
    last = df.iloc[-1]
    asof = last["date"]
    a = asof.isoformat()
    close = df["adj_close"].to_numpy()
    out: dict = {"as_of": a, "close": num(float(last["close"]), INR, as_of=a, source="NSE security-wise history")}
    trend = {}
    for n in (50, 200):
        if len(df) >= n:
            ma = float(close[-n:].mean())
            trend[f"dma_{n}"] = derived(ma, INR, formula=f"mean of last {n} adjusted closes", as_of=a)
            trend[f"pct_vs_dma_{n}"] = derived((close[-1] / ma - 1) * 100, PCT, formula=f"adj_close / dma_{n} - 1", as_of=a)
        else:
            trend[f"dma_{n}"] = missing(f"only {len(df)} sessions cached; need {n}", INR)
    if len(df) >= 200:
        ma50, ma200 = close[-50:].mean(), close[-200:].mean()
        trend["dma_50_vs_200_pct"] = derived((ma50 / ma200 - 1) * 100, PCT, formula="dma_50 / dma_200 - 1", as_of=a)
    out["trend"] = trend
    yr = df[df["date"] > asof - dt.timedelta(days=365)]
    hi_i, lo_i = yr["adj_high"].idxmax(), yr["adj_low"].idxmin()
    hi, lo = float(yr.at[hi_i, "adj_high"]), float(yr.at[lo_i, "adj_low"])
    full_year = df["date"].iloc[0] <= asof - dt.timedelta(days=360)
    note = None if full_year else f"price history starts {df['date'].iloc[0]}: less than 52 weeks"
    out["range_52w"] = {
        "high": num(hi, INR, as_of=yr.at[hi_i, "date"].isoformat(), source=SRC, notes=note),
        "low": num(lo, INR, as_of=yr.at[lo_i, "date"].isoformat(), source=SRC, notes=note),
        "pct_below_high": derived((1 - close[-1] / hi) * 100, PCT, formula="1 - adj_close / 52w adj high", as_of=a),
        "pct_above_low": derived((close[-1] / lo - 1) * 100, PCT, formula="adj_close / 52w adj low - 1", as_of=a),
    }
    # relative strength: stock total return (dividends reinvested) vs index TRI over the same sessions
    rs = {}
    dates = df["date"]
    idx = None
    if index_df is not None and "tri" in index_df.columns:
        idx = index_df.dropna(subset=["tri"]).sort_values("date").reset_index(drop=True)
    for m in (3, 6, 12):
        sr, start = _ret_over(df["tr_index"], dates, asof, m)
        if sr is None:
            rs[f"{m}m"] = missing(f"price history shorter than {m} months", PCT)
            continue
        block = {"stock_total_return": derived(sr * 100, PCT, formula=f"tr_index {a} / tr_index {start} - 1", period=f"{start}..{a}")}
        if idx is not None and len(idx) and idx["date"].iloc[0] <= start and idx["date"].iloc[-1] >= asof:
            i0 = idx["date"].searchsorted(start)
            i1 = idx["date"].searchsorted(asof, side="right") - 1
            ir = float(idx["tri"].iloc[i1] / idx["tri"].iloc[i0] - 1)
            block["index_total_return"] = derived(ir * 100, PCT, formula=f"{index_name} TRI {idx['date'].iloc[i1]} / {idx['date'].iloc[i0]} - 1",
                                                  period=f"{idx['date'].iloc[i0]}..{idx['date'].iloc[i1]}")
            block["excess_return_pp"] = derived((sr - ir) * 100, "percentage points", formula="stock_total_return - index_total_return")
            block["relative_strength_ratio"] = derived((1 + sr) / (1 + ir), RATIO, formula="(1 + stock) / (1 + index)")
            if idx["date"].iloc[i1] != asof:
                block["note"] = f"index series ends {idx['date'].iloc[i1]}, stock {a}; refresh `data index history`"
        else:
            block["index_total_return"] = missing(f"{index_name} TRI not cached for {start}..{a}; run `data index history \"{index_name}\"`", PCT)
        rs[f"{m}m"] = block
    out["relative_strength"] = rs
    vol = {}
    for n in (60, 252):
        v = realised_vol(close[-(n + 1):]) if len(close) > n else None
        vol[f"{n}d"] = (derived(v * 100, PCT, formula=f"stdev of last {n} daily log returns x sqrt(252)", as_of=a) if v is not None
                        else missing(f"need {n + 1} sessions, have {len(close)}", PCT))
    out["realised_volatility_annualised"] = vol
    dd_df = df[df["date"] > asof - dt.timedelta(days=int(365.25 * dd_years))]
    mdd, pk, tr = max_drawdown(dd_df["adj_close"].to_numpy(), dd_df["date"].tolist())
    cur_dd = close[-1] / dd_df["adj_close"].max() - 1
    short = dd_df["date"].iloc[0] > asof - dt.timedelta(days=int(365.25 * dd_years) - 7)
    out["drawdown"] = {
        "max": derived(mdd * 100, PCT, formula="largest peak-to-trough fall of adj_close", period=f"{dd_df['date'].iloc[0]}..{a}",
                       notes=f"peak {pk}, trough {tr}" + (f"; cached history shorter than the {dd_years:g}y requested" if short else "")),
        "current_from_peak": derived(cur_dd * 100, PCT, formula="adj_close / max adj_close in window - 1", period=f"{dd_df['date'].iloc[0]}..{a}"),
    }
    liq = {}
    for n in (20, 60):
        tail = df.tail(n)
        if len(tail) < n:
            liq[f"adv_{n}d"] = missing(f"need {n} sessions", INR_CR)
            continue
        liq[f"adv_{n}d"] = derived(float(tail["value_inr"].mean()) / 1e7, INR_CR, formula=f"mean daily traded value over last {n} sessions / 1e7",
                                   period=f"{tail['date'].iloc[0]}..{a}")
        liq[f"median_value_{n}d"] = derived(float(tail["value_inr"].median()) / 1e7, INR_CR, formula=f"median daily traded value over last {n} sessions / 1e7",
                                            period=f"{tail['date'].iloc[0]}..{a}")
    if "delivery_pct" in df.columns and df["delivery_pct"].tail(20).notna().any():
        liq["delivery_pct_20d"] = derived(float(df["delivery_pct"].tail(20).mean()), PCT, formula="mean delivery % over last 20 sessions", as_of=a)
    out["liquidity"] = liq
    gaps = unadjusted_gaps(df)
    if gaps:
        out["warnings"] = gaps
    return out


def cmd_technicals(args) -> dict:
    from ..common.entity import get_entity
    from ..data.index import load_index
    from ..data.prices import load_adjusted
    e = get_entity(args.query)
    px = load_adjusted(e.isin)
    try:
        idx = load_index(args.index)
    except FileNotFoundError:
        idx = None
    out = {"identity": e.identity(), **technicals(px, idx, index_name=args.index.upper(), dd_years=args.drawdown_years)}
    out["source_note"] = "uses the cached series; run `data prices` / `data index history` first to bring them up to date"
    return out


def register(sub, leaf) -> None:
    p = leaf(sub, "technicals", "DMA trend, 52w range, 3/6/12m relative strength vs Nifty 500 TRI, volatility, max drawdown, ADV (cached prices)")
    p.add_argument("query", help="NSE symbol or ISIN")
    p.add_argument("--index", default="NIFTY 500")
    p.add_argument("--drawdown-years", type=float, default=3.0)
    p.set_defaults(func=cmd_technicals)
