"""`compute portfolio`: correlation, exposures, concentration, liquidity and a beta stress test for a set of weights.

Facts about a proposed portfolio, no opinion on it. Weights are fractions of
capital; cash = 1 - sum(weights). Returns are daily total returns (dividends
reinvested) from the cached adjusted series, aligned on common sessions.
Mandate checks report whether a limit is breached; they do not change weights.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..common.errors import InputError
from ..common.provenance import derived, missing, num
from ..common.units import INR, INR_CR, PCT, RATIO
from ._util import MANDATE_PATH, load_mandate, records_table, unadjusted_gaps

SIZE_BUCKETS = (("NIFTY 100", "large (Nifty 100)"), ("NIFTY MIDCAP 150", "mid (Nifty Midcap 150)"),
                ("NIFTY SMALLCAP 250", "small (Nifty Smallcap 250)"))
PARTICIPATION = (0.10, 0.15, 0.20)
STRESS_MARKET = -0.20


def size_bucket(memberships: list[str]) -> str:
    for idx, label in SIZE_BUCKETS:
        if idx in memberships:
            return label
    return "other (outside Nifty 500 size indices)"


def daily_returns(series: dict[str, pd.DataFrame], col: str = "tr_index", sessions: int = 252) -> pd.DataFrame:
    """Daily simple returns on the sessions all names share, last `sessions` of them."""
    frames = [s.set_index("date")[col].rename(sym) for sym, s in series.items()]
    wide = pd.concat(frames, axis=1, join="inner").sort_index()
    return wide.pct_change().dropna().tail(sessions)


def beta(stock: pd.Series, market: pd.Series) -> float | None:
    j = pd.concat([stock, market], axis=1, join="inner").dropna()
    if len(j) < 60:
        return None
    var = float(np.var(j.iloc[:, 1], ddof=1))
    return float(np.cov(j.iloc[:, 0], j.iloc[:, 1], ddof=1)[0, 1] / var) if var else None


def momentum_12_1(px: pd.DataFrame, asof: dt.date) -> float | None:
    """Total return from 12 months ago to 1 month ago (skips the latest month)."""
    d = px.set_index("date")["tr_index"].sort_index()
    t12 = (pd.Timestamp(asof) - pd.DateOffset(months=12)).date()
    t1 = (pd.Timestamp(asof) - pd.DateOffset(months=1)).date()
    if d.index[0] > t12 + dt.timedelta(days=7):
        return None
    a = d[d.index >= t12].iloc[0]
    b = d[d.index <= t1].iloc[-1]
    return float(b / a - 1)


def hhi(weights: dict[str, float]) -> tuple[float | None, float | None]:
    """HHI on invested weights renormalised to 1, and effective N = 1/HHI."""
    tot = sum(weights.values())
    if tot <= 0:
        return None, None
    h = sum((w / tot) ** 2 for w in weights.values())
    return h, 1 / h


def analyse(weights: dict[str, float], prices: dict[str, pd.DataFrame], meta: dict[str, dict], index_df: pd.DataFrame | None, *,
            capital_inr: float | None, mandate: dict, values: dict[str, float] | None = None, value_label: str | None = None,
            mandate_source: str = "config/mandate.yaml") -> dict:
    if not weights:
        raise InputError("no holdings")
    if any(w < 0 for w in weights.values()):
        raise InputError("negative weights: the mandate is long-only cash equity")
    syms = list(weights)
    tot = sum(weights.values())
    asof = min(p["date"].max() for p in prices.values())
    a = asof.isoformat()
    rets = daily_returns(prices)
    out: dict[str, Any] = {"as_of": a, "holdings": syms}
    out["weights"] = {s: num(w * 100, PCT, source="caller") for s, w in weights.items()}
    out["cash"] = derived((1 - tot) * 100, PCT, formula="1 - sum(weights)")
    if len(rets) < 60:
        out["correlation"] = missing(f"only {len(rets)} common sessions; need 60", RATIO)
    else:
        c = rets.corr()
        out["correlation"] = records_table([{"symbol": s, **{t: float(c.at[s, t]) for t in syms}} for s in syms], ["symbol", *syms],
                                           {t: RATIO for t in syms}, source="computed from daily total returns",
                                           notes=f"{len(rets)} common sessions {rets.index[0]}..{rets.index[-1]}")
    mkt = None
    if index_df is not None and "tri" in index_df.columns:
        mkt = index_df.dropna(subset=["tri"]).set_index("date")["tri"].sort_index().pct_change().dropna()
    rows, betas = [], {}
    for s in syms:
        px = prices[s].sort_values("date")
        r = px.set_index("date")["tr_index"].pct_change().dropna().tail(252)
        b = beta(r, mkt) if mkt is not None else None
        betas[s] = b
        adv20 = float(px["value_inr"].tail(20).mean()) / 1e7 if len(px) >= 20 else None
        mom = momentum_12_1(px, asof)
        row = {"symbol": s, "weight_pct": weights[s] * 100, "sector": meta[s].get("industry"), "size": size_bucket(meta[s].get("index_memberships", [])),
               "beta_1y": b, "momentum_12_1_pct": mom * 100 if mom is not None else None, "adv_20d_inr_crore": adv20}
        if values is not None:
            row["value_metric"] = values.get(s)
        for p in PARTICIPATION:
            pos = capital_inr * weights[s] if capital_inr else None
            row[f"days_to_exit_at_{int(p * 100)}pct_adv"] = pos / (p * adv20 * 1e7) if pos is not None and adv20 else None
        rows.append(row)
    cols = ["symbol", "weight_pct", "sector", "size", "beta_1y", "momentum_12_1_pct", "adv_20d_inr_crore",
            *(["value_metric"] if values is not None else []), *[f"days_to_exit_at_{int(p * 100)}pct_adv" for p in PARTICIPATION]]
    units = {"weight_pct": PCT, "beta_1y": RATIO, "momentum_12_1_pct": PCT, "adv_20d_inr_crore": INR_CR,
             **{f"days_to_exit_at_{int(p * 100)}pct_adv": "days" for p in PARTICIPATION}}
    if values is not None:
        units["value_metric"] = value_label or "as supplied"
    out["positions"] = records_table(rows, cols, units, source="computed (cached prices, index TRI, resolve)",
                                     notes=("beta vs NIFTY 500 TRI, last 252 sessions; size from index membership; days to exit = "
                                            "capital x weight / (participation x 20d ADV)" + ("" if capital_inr else "; capital_inr not set: days to exit null")))
    by = lambda key: {k: sum(r["weight_pct"] for r in rows if r[key] == k) for k in dict.fromkeys(r[key] for r in rows)}  # noqa: E731
    out["exposure"] = {
        "sector": {k or "unknown": derived(v, PCT, formula="sum of weights") for k, v in by("sector").items()},
        "size": {k: derived(v, PCT, formula="sum of weights") for k, v in by("size").items()},
    }
    known = [s for s in syms if betas[s] is not None]
    if len(known) == len(syms):
        pb = sum(weights[s] * betas[s] for s in syms)
        out["exposure"]["beta"] = derived(pb, RATIO, formula="sum(weight x beta); cash beta 0")
        out["stress"] = {"market_move": num(STRESS_MARKET * 100, PCT, source="fixed scenario"),
                         "beta_implied_portfolio_move": derived(pb * STRESS_MARKET * 100, PCT, formula="portfolio beta x market move",
                                                                notes="linear beta only: ignores correlation spikes, liquidity and gap risk in a sell-off")}
    else:
        out["exposure"]["beta"] = missing(f"beta unavailable for {[s for s in syms if betas[s] is None]} (needs NIFTY 500 TRI cache and 60 sessions)", RATIO)
    moms = [(weights[s], r["momentum_12_1_pct"]) for s, r in zip(syms, rows) if r["momentum_12_1_pct"] is not None]
    out["exposure"]["momentum_12_1"] = (derived(sum(w * m for w, m in moms) / sum(w for w, _ in moms), PCT, formula="weight-averaged 12-1m total return")
                                        if moms else missing("no name has 12 months of prices", PCT))
    if values is not None:
        vs = [(weights[s], values[s]) for s in syms if values.get(s) is not None]
        out["exposure"]["value"] = (derived(sum(w * v for w, v in vs) / sum(w for w, _ in vs), value_label or "as supplied",
                                            formula="weight-averaged supplied value metric") if vs else missing("no value metric supplied", None))
    else:
        out["exposure"]["value"] = missing("pass --value SYM:X,... (e.g. P/E from compute valuation) to summarise value exposure", None)
    h, n_eff = hhi(weights)
    out["concentration"] = {"hhi": derived(h, RATIO, formula="sum((w / sum w)^2) over invested weights"),
                            "effective_n": derived(n_eff, "count", formula="1 / hhi")}
    out["mandate_checks"] = mandate_checks(weights, rows, mandate, tot, source=mandate_source)
    warns = [f"{s}: {w}" for s in syms for w in unadjusted_gaps(prices[s])]
    if warns:
        out["warnings"] = warns
    return out


def mandate_checks(weights: dict[str, float], rows: list[dict], m: dict, tot: float, source: str = "config/mandate.yaml") -> list[dict]:
    """Facts about limits: each check states the limit, the observed value and whether it is breached."""
    checks = []

    def add(name: str, limit: Any, observed: Any, breach: bool | None, unit: str | None, note: str | None = None) -> None:
        checks.append({"check": name, "limit": num(limit, unit, source=source) if isinstance(limit, (int, float)) else limit,
                       "observed": num(observed, unit, source="computed") if isinstance(observed, (int, float)) or observed is None else observed,
                       "breach": breach, "note": note})
    n = len(weights)
    if m.get("max_positions") is not None:
        add("max_positions", m["max_positions"], n, n > m["max_positions"], "count")
    if m.get("min_positions") is not None:
        add("min_positions", m["min_positions"], n, n < m["min_positions"], "count")
    if m.get("max_weight") is not None:
        top = max(weights.values())
        add("max_weight", m["max_weight"] * 100, top * 100, top > m["max_weight"] + 1e-9, PCT)
    if m.get("max_sector_weight") is not None:
        sec: dict[str, float] = {}
        for r in rows:
            sec[r["sector"] or "unknown"] = sec.get(r["sector"] or "unknown", 0) + r["weight_pct"]
        top_s = max(sec, key=sec.get)
        add("max_sector_weight", m["max_sector_weight"] * 100, sec[top_s], sec[top_s] > m["max_sector_weight"] * 100 + 1e-9, PCT, f"largest: {top_s}")
    add("weights_sum_le_1", 100.0, tot * 100, tot > 1 + 1e-9, PCT)
    if not m.get("allow_cash", True):
        add("allow_cash", "cash not allowed", (1 - tot) * 100, (1 - tot) > 1e-9, PCT)
    liq = m.get("liquidity") or {}
    if liq.get("min_adv_inr_crore") is not None:
        low = [r["symbol"] for r in rows if r["adv_20d_inr_crore"] is not None and r["adv_20d_inr_crore"] < liq["min_adv_inr_crore"]]
        add("min_adv_inr_crore", liq["min_adv_inr_crore"], None, bool(low), INR_CR, f"below limit: {low}" if low else "all names at or above")
    if liq.get("max_days_to_exit") is not None:
        p = liq.get("participation_rate", 0.15)
        col = f"days_to_exit_at_{int(round(p * 100))}pct_adv"
        known = [r for r in rows if r.get(col) is not None]
        if not known:
            add("max_days_to_exit", liq["max_days_to_exit"], None, None, "days", "capital_inr not set (or participation rate not in 10/15/20%): not checked")
        else:
            worst = max(known, key=lambda r: r[col])
            add("max_days_to_exit", liq["max_days_to_exit"], worst[col], worst[col] > liq["max_days_to_exit"], "days", f"slowest: {worst['symbol']} at {p:.0%} of ADV")
    ex = set(x.upper() for x in (m.get("exclusions") or []))
    if ex:
        hit = [r["symbol"] for r in rows if r["symbol"].upper() in ex or (r["sector"] or "").upper() in ex]
        add("exclusions", ", ".join(sorted(ex)), ", ".join(hit) or "none", bool(hit), None)
    return checks


def parse_holdings(spec: str | None, path: str | None) -> dict[str, float]:
    if path:
        data = json.loads(Path(path).read_text())
        items = data.get("holdings", data) if isinstance(data, dict) else data
        return {str(h["symbol"]).upper(): float(h["weight"]) for h in items}
    if not spec:
        raise InputError("pass --holdings SYM:w,... or --holdings-file FILE")
    out = {}
    for part in spec.split(","):
        sym, _, w = part.partition(":")
        try:
            out[sym.strip().upper()] = float(w)
        except ValueError as ex:
            raise InputError(f"bad holding {part!r}: use SYM:weight with weight a fraction") from ex
    return out


def cmd_portfolio(args) -> dict:
    from ..common.entity import get_entity
    from ..data.index import load_index
    from ..data.prices import load_adjusted
    weights = parse_holdings(args.holdings, args.holdings_file)
    prices, meta = {}, {}
    for s in weights:
        e = get_entity(s)
        prices[s] = load_adjusted(e.isin)
        meta[s] = {"isin": e.isin, "industry": e.industry, "index_memberships": e.index_memberships}
    try:
        idx = load_index("NIFTY 500")
    except FileNotFoundError:
        idx = None
    mandate_path = Path(args.mandate) if args.mandate else MANDATE_PATH
    if not mandate_path.exists():
        raise InputError(f"mandate file not found: {mandate_path}")
    mandate = load_mandate(mandate_path)
    mandate_src = args.mandate or "config/mandate.yaml"
    capital = args.capital if args.capital is not None else mandate.get("capital_inr")
    values = None
    if args.value:
        values = {k.strip().upper(): float(v) for k, _, v in (p.partition(":") for p in args.value.split(","))}
    out = analyse(weights, prices, meta, idx, capital_inr=capital, mandate=mandate, values=values, value_label=args.value_label,
                  mandate_source=mandate_src)
    out["capital"] = num(capital, INR, source="--capital" if args.capital is not None else f"{mandate_src} capital_inr") if capital else missing(
        "capital_inr not set in mandate and --capital not given", INR)
    out["identities"] = {s: meta[s]["isin"] for s in weights}
    return out


def register(sub, leaf) -> None:
    p = leaf(sub, "portfolio", "correlation, sector/size/beta/momentum exposure, HHI, days to exit at 10-20%% of ADV, -20%% beta stress, mandate checks")
    p.add_argument("--holdings", help="SYM:weight,... with weights as fractions, e.g. 'RELIANCE:0.1,CAMS:0.05'")
    p.add_argument("--holdings-file", help="JSON list of {symbol, weight} (or {holdings: [...]})")
    p.add_argument("--capital", type=float, help="INR; default mandate capital_inr")
    p.add_argument("--mandate", help="mandate YAML for the checks and capital, e.g. runs/<run_id>/mandate.yaml (default config/mandate.yaml)")
    p.add_argument("--value", help="optional SYM:X,... value metric per name (e.g. P/E from compute valuation)")
    p.add_argument("--value-label", help="what --value is, e.g. 'P/E TTM'")
    p.set_defaults(func=cmd_portfolio)
