"""`ledger mark` and `ledger postmortem`: cohort returns vs the benchmark, costs, tax and calibration.

Entry is the close of the first trading session after the freeze date. Returns
are total returns (dividends reinvested) from each name's adjusted series; the
benchmark is the Nifty 500 TRI over the same dates. Cohort A is weighted with
cash earning 0; B, C and D are equal-weight buy-and-hold (the mean of member
returns). A member without prices is reported and left out of its cohort's
mean, never counted as 0.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd

from ..common.errors import InputError
from ..common.provenance import derived, missing, now_iso, num, today_ist
from ..common.units import INR, PCT
from ..compute import costs_tax
from ..compute._util import records_table
from . import store
from .freeze import READING

NOTIONAL_CAPITAL = 1_000_000.0
CAL_BINS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


def entry_date(series: pd.DataFrame, frozen: dt.date) -> dt.date | None:
    after = series[series["date"] > frozen]["date"]
    return after.min() if len(after) else None


def total_return(series: pd.DataFrame, col: str, start: dt.date, end: dt.date) -> tuple[float | None, dt.date | None, str | None]:
    """col(end') / col(start) - 1 with end' the last session on or before `end`."""
    s = series.dropna(subset=[col]).sort_values("date")
    a = s[s["date"] == start]
    b = s[s["date"] <= end]
    if a.empty:
        return None, None, f"no {col} on entry date {start}"
    if b.empty or b["date"].iloc[-1] < start:
        return None, None, "no data after entry"
    return float(b[col].iloc[-1] / a[col].iloc[0] - 1), b["date"].iloc[-1], None


def member_returns(members: list[dict], market, frozen: dt.date, end: dt.date) -> list[dict]:
    rows = []
    for m in members:
        px = market.prices(m["isin"], frozen - dt.timedelta(days=10))
        d0 = entry_date(px, frozen) if len(px) else None
        if d0 is None:
            rows.append({**m, "entry_date": None, "tr": None, "price_return": None, "last_date": None, "why": "no session after the freeze date in the price series"})
            continue
        tr, last, why = total_return(px, "tr_index", d0, end)
        pr, _, _ = total_return(px, "adj_close", d0, end)
        entry_px = float(px[px["date"] == d0]["close"].iloc[0])
        rows.append({**m, "entry_date": d0, "entry_close": entry_px, "tr": tr, "price_return": pr, "last_date": last, "why": why})
    return rows


def bench_return(market, d0: dt.date, end: dt.date) -> tuple[float | None, dt.date | None, str | None]:
    idx = market.index_tri()
    if idx.empty:
        return None, None, "benchmark TRI not available"
    s = idx[idx["date"] >= d0]
    if s.empty:
        return None, None, "benchmark TRI has no data after entry"
    return total_return(idx, "tri", s["date"].min(), end)


def cohort_returns(run: dict, market, end: dt.date) -> tuple[dict, dict[str, list[dict]], dict]:
    frozen = dt.date.fromisoformat(run["frozen_at"][:10])
    rows: dict[str, list[dict]] = {}
    out: dict[str, Any] = {}
    for k in ("A", "B", "C", "D"):
        members = run["cohorts"][k]["members"]
        rows[k] = member_returns(members, market, frozen, end)
    d0s = [r["entry_date"] for rs in rows.values() for r in rs if r["entry_date"]]
    d0 = min(d0s) if d0s else None
    if d0 is None:
        cal = market.index_tri()
        d0 = entry_date(cal, frozen) if len(cal) else None
    b, b_last, b_why = bench_return(market, d0, end) if d0 else (None, None, "no session after freeze yet")
    bench = {"tr": b, "last_date": b_last, "why": b_why, "entry_date": d0}
    a_rows = rows["A"]
    if not a_rows:
        out["A"] = {"value": 0.0, "why": None, "n": 0, "n_with_data": 0, "note": "no picks: 100% cash (0 return assumed)"}
    elif any(r["tr"] is None for r in a_rows):
        out["A"] = {"value": None, "why": f"missing returns for {[r['symbol'] for r in a_rows if r['tr'] is None]}", "n": len(a_rows), "n_with_data": 0}
    else:
        out["A"] = {"value": sum(r["weight"]["value"] * r["tr"] for r in a_rows), "why": None, "n": len(a_rows), "n_with_data": len(a_rows),
                    "note": "weighted; cash earns 0"}
    for k in ("B", "C", "D"):
        good = [r["tr"] for r in rows[k] if r["tr"] is not None]
        miss = [r["symbol"] for r in rows[k] if r["tr"] is None]
        out[k] = {"value": sum(good) / len(good) if good else None, "why": None if good else ("empty cohort" if not rows[k] else "no member has returns"),
                  "n": len(rows[k]), "n_with_data": len(good),
                  "note": f"excluded (no prices): {miss}; survivorship risk" if miss else "equal weight, buy and hold"}
    out["E"] = {"value": b, "why": b_why, "n": 1, "n_with_data": 1 if b is not None else 0, "note": run["cohorts"]["E"]["index"]}
    return out, rows, bench


def _pct(x: float | None, formula: str, why: str | None = None, **kw) -> dict:
    return derived(x * 100, PCT, formula=formula, **kw) if x is not None else missing(why or "inputs missing", PCT, source="computed")


def _comparisons(c: dict) -> dict:
    pairs = {"A_minus_B": ("A", "B"), "C_minus_A": ("C", "A"), "B_minus_D": ("B", "D"), "D_minus_E": ("D", "E"), "A_minus_E": ("A", "E")}
    out = {}
    for name, (x, y) in pairs.items():
        vx, vy = c[x]["value"], c[y]["value"]
        out[name] = (derived((vx - vy) * 100, "percentage points", formula=f"cohort {x} return - cohort {y} return")
                     if vx is not None and vy is not None else missing(f"cohort {x} or {y} has no return", "percentage points", source="computed"))
    out["how_to_read"] = READING
    return out


def _cohort_block(c: dict, bench: dict, as_of: str) -> dict:
    out = {}
    for k, v in c.items():
        blk = {"total_return": _pct(v["value"], f"cohort {k} total return since entry", v["why"], as_of=as_of),
               "n_members": num(v["n"], "count", source="ledger"), "n_with_returns": num(v["n_with_data"], "count", source="computed"),
               "note": v.get("note")}
        if k != "E":
            blk["excess_vs_E"] = (derived((v["value"] - bench["tr"]) * 100, "percentage points", formula=f"cohort {k} - Nifty 500 TRI")
                                  if v["value"] is not None and bench["tr"] is not None else missing("cohort or benchmark return missing", "percentage points", source="computed"))
        out[k] = blk
    return out


def _pick_table(picks: list[dict], rows_a: list[dict], bench: dict) -> dict:
    by_isin = {r["isin"]: r for r in rows_a}
    recs = []
    for p in picks:
        r = by_isin.get(p["isin"], {})
        tr = r.get("tr")
        nxt = min((d for d in p.get("review_dates", []) if d >= today_ist().isoformat()), default=None)
        recs.append({"symbol": p["symbol"], "isin": p["isin"], "weight_pct": p["weight"]["value"] * 100,
                     "entry_date": r.get("entry_date").isoformat() if r.get("entry_date") else None, "entry_close": r.get("entry_close"),
                     "total_return_pct": tr * 100 if tr is not None else None,
                     "benchmark_return_pct": bench["tr"] * 100 if bench["tr"] is not None else None,
                     "excess_pp": (tr - bench["tr"]) * 100 if tr is not None and bench["tr"] is not None else None,
                     "p_beat_benchmark": p["p_beat_benchmark"]["value"], "n_kill_criteria": len(p.get("kill_criteria", [])),
                     "next_review": nxt, "why_null": r.get("why")})
    cols = ["symbol", "isin", "weight_pct", "entry_date", "entry_close", "total_return_pct", "benchmark_return_pct", "excess_pp",
            "p_beat_benchmark", "n_kill_criteria", "next_review", "why_null"]
    return records_table(recs, cols, {"weight_pct": PCT, "entry_close": INR, "total_return_pct": PCT, "benchmark_return_pct": PCT,
                                      "excess_pp": "percentage points", "p_beat_benchmark": "probability", "n_kill_criteria": "count"},
                         source="computed from cached adjusted prices (dividends reinvested) and Nifty 500 TRI")


def mark(run_id: str, *, ledger_dir: str | None, market, as_of: dt.date | None = None) -> dict:
    run, picks, _ = store.run_records(run_id, ledger_dir)
    end = as_of or today_ist()
    c, rows, bench = cohort_returns(run, market, end)
    last = bench["last_date"].isoformat() if bench["last_date"] else None
    return {"run_id": run_id, "frozen_at": run["frozen_at"], "entry_date": bench["entry_date"].isoformat() if bench["entry_date"] else None,
            "as_of": last, "horizon_end": run["horizon_end"],
            "cohorts": _cohort_block(c, bench, last), "comparisons": _comparisons(c), "picks": _pick_table(picks, rows["A"], bench),
            "cohort_members": {k: [{"symbol": r["symbol"], "total_return_pct": _pct(r["tr"], "total return since entry", r["why"])} for r in rows[k]]
                               for k in ("B", "C", "D")},
            "notes": list(getattr(market, "notes", [])) + ["marks are gross of costs and tax; `ledger postmortem` nets them"]}


# ---------------------------------------------------------------- postmortem

def brier(probs: list[float], outcomes: list[int]) -> float | None:
    if not probs:
        return None
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs)


def calibration(probs: list[float], outcomes: list[int]) -> list[dict]:
    rows = []
    for lo, hi in zip(CAL_BINS, CAL_BINS[1:]):
        sel = [(p, o) for p, o in zip(probs, outcomes) if lo <= p < hi or (hi == 1.0 and p == 1.0)]
        rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(sel), "mean_forecast": sum(p for p, _ in sel) / len(sel) if sel else None,
                     "observed_frequency": sum(o for _, o in sel) / len(sel) if sel else None})
    return rows


def scenario_outcome(scenarios: list[dict], ret_pct: float) -> int | None:
    """Index of the scenario whose return range contains the outcome, if every scenario has a range."""
    for i, s in enumerate(scenarios):
        lo, hi = s["return_range_lo_pct"]["value"], s["return_range_hi_pct"]["value"]
        if lo is None and hi is None:
            return None
        if (lo is None or ret_pct >= lo) and (hi is None or ret_pct < hi):
            return i
    return None


def portfolio_tax(lots: list[dict], cfg: dict, sell_date: dt.date, surcharge: float = 0.0) -> dict:
    """Net short- and long-term results across picks (short-term losses also offset long-term gains), then tax with and
    without one annual LTCG exemption."""
    st = sum(l["gain"] for l in lots if l["kind"] == "STCG")
    lt = sum(l["gain"] for l in lots if l["kind"] == "LTCG")
    if st < 0:
        lt, st = lt + st, 0.0
    lt = max(lt, 0.0)
    e = lambda n: float(costs_tax.entry(cfg, "tax", n, sell_date)["value"])  # noqa: E731
    sur = min(surcharge, e("surcharge_cap_cg"))
    mult = (1 + sur) * (1 + e("cess"))
    ex = e("ltcg_exemption_inr_per_fy")
    without = (st * e("stcg_equity_rate") + lt * e("ltcg_equity_rate")) * mult
    with_ex = (st * e("stcg_equity_rate") + max(0.0, lt - ex) * e("ltcg_equity_rate")) * mult
    return {"net_stcg": st, "net_ltcg": lt, "tax_without_exemption": without, "tax_with_exemption": with_ex, "exemption": ex}


def postmortem(run_id: str, *, ledger_dir: str | None, market, force: bool = False, surcharge: float = 0.0, slab_rate: float | None = None,
               as_of: dt.date | None = None, cfg: dict | None = None, write: bool = True) -> dict:
    run, picks, other = store.run_records(run_id, ledger_dir)
    cfg = cfg or costs_tax.load_costs()
    horizon_end = dt.date.fromisoformat(run["horizon_end"])
    end = as_of or today_ist()
    interim = end < horizon_end
    if interim and not force:
        raise InputError(f"horizon ends {horizon_end}; pass --force for an interim postmortem (it will be labelled interim)")
    end = min(end, horizon_end)
    rec_id = f"{run_id}:postmortem" + (f"-interim-{end.isoformat()}" if interim else "")
    if write and any(r["record_id"] == rec_id for r in other):
        raise InputError(f"{rec_id} already recorded; the ledger is append-only (use `ledger correct`)")
    c, rows, bench = cohort_returns(run, market, end)
    capital = (run.get("capital_inr") or {}).get("value") or NOTIONAL_CAPITAL
    lots, pick_rows, probs, outs, sc_scores = [], [], [], [], []
    costs_total, pnl_without, divs, div_tax = 0.0, 0.0, 0.0, 0.0
    by_isin = {r["isin"]: r for r in rows["A"]}
    for p in picks:
        r = by_isin.get(p["isin"]) or {"tr": None, "why": "pick not in cohort A"}
        if r["tr"] is None:
            pick_rows.append({"symbol": p["symbol"], "why_null": r["why"]})
            continue
        pos = capital * p["weight"]["value"]
        sell = pos * (1 + r["price_return"])
        t = costs_tax.trade(pos, sell, r["entry_date"], r["last_date"], surcharge=surcharge, cfg=cfg)
        cost = t["costs"]["total"]["value"]
        tax_wo = t["tax"]["tax_without_exemption"]["value"]
        div = pos * (r["tr"] - r["price_return"])  # dividends reinvested, approximated as cash
        dtax = div * slab_rate if slab_rate is not None else None
        net = sell - pos - cost - tax_wo + div - (dtax or 0.0)
        costs_total += cost
        pnl_without += net
        divs += div
        div_tax += dtax or 0.0
        lots.append({"kind": t["tax"]["kind"], "gain": t["tax"]["gain"]["value"]})
        beat = int(bench["tr"] is not None and r["tr"] > bench["tr"])
        probs.append(p["p_beat_benchmark"]["value"])
        outs.append(beat)
        k = scenario_outcome(p["scenarios"], r["tr"] * 100)
        if k is not None:
            sc_scores.append(sum((s["probability"]["value"] - (1 if i == k else 0)) ** 2 for i, s in enumerate(p["scenarios"])))
        pick_rows.append({"symbol": p["symbol"], "kind": t["tax"]["kind"], "gross_tr_pct": r["tr"] * 100,
                          "benchmark_pct": bench["tr"] * 100 if bench["tr"] is not None else None,
                          "gross_excess_pp": (r["tr"] - bench["tr"]) * 100 if bench["tr"] is not None else None,
                          "costs_inr": cost, "cg_tax_no_exemption_inr": tax_wo, "dividends_inr": div,
                          "net_return_pct": net / pos * 100,
                          "net_excess_pp": (net / pos - bench["tr"]) * 100 if bench["tr"] is not None else None,
                          "p_beat_benchmark": p["p_beat_benchmark"]["value"], "beat": beat,
                          "realised_scenario": p["scenarios"][k]["name"] if k is not None else None, "why_null": None})
    pt = portfolio_tax(lots, cfg, end, surcharge) if lots else None
    a_net = {}
    if pt and len(lots) == len(picks):
        # per-pick nets carry per-pick tax without the exemption; add it back, then apply portfolio-level tax
        per_pick_tax = sum(r["cg_tax_no_exemption_inr"] for r in pick_rows if r.get("cg_tax_no_exemption_inr") is not None)
        before_tax = pnl_without + per_pick_tax
        for label, tax in (("with_exemption", pt["tax_with_exemption"]), ("without_exemption", pt["tax_without_exemption"])):
            r_net = (before_tax - tax) / capital
            a_net[label] = {"net_return": derived(r_net * 100, PCT, formula="(pnl after costs and dividend tax - portfolio CG tax) / capital; cash earns 0"),
                            "net_excess_vs_E": derived((r_net - bench["tr"]) * 100, "percentage points", formula="net return - Nifty 500 TRI")
                            if bench["tr"] is not None else missing("benchmark missing", "percentage points", source="computed"),
                            "cg_tax": derived(tax, INR, formula="portfolio-level: losses netted, one annual LTCG exemption" if label == "with_exemption"
                                              else "portfolio-level: losses netted, no exemption")}
    last = bench["last_date"].isoformat() if bench["last_date"] else None
    cal = calibration(probs, outs)
    out = {
        "run_id": run_id, "interim": interim, "as_of": last, "marked_to": end.isoformat(), "entry_date": bench["entry_date"].isoformat() if bench["entry_date"] else None,
        "horizon_end": run["horizon_end"],
        "capital": num(capital, INR, source="ledger run record" if (run.get("capital_inr") or {}).get("value") else "notional (capital_inr not set)"),
        "picks": records_table(pick_rows, ["symbol", "kind", "gross_tr_pct", "benchmark_pct", "gross_excess_pp", "costs_inr", "cg_tax_no_exemption_inr",
                                           "dividends_inr", "net_return_pct", "net_excess_pp", "p_beat_benchmark", "beat", "realised_scenario", "why_null"],
                               {"gross_tr_pct": PCT, "benchmark_pct": PCT, "gross_excess_pp": "percentage points", "costs_inr": INR,
                                "cg_tax_no_exemption_inr": INR, "dividends_inr": INR, "net_return_pct": PCT, "net_excess_pp": "percentage points",
                                "p_beat_benchmark": "probability", "beat": "0/1"},
                               source="computed (prices cache, Nifty 500 TRI, config/costs.yaml)",
                               notes="per pick: costs and CG tax without the exemption (the exemption is per person per FY; see portfolio). "
                                     "Dividends = TR minus price return on the position, approximated as cash. "
                                     + ("Dividend tax at --slab-rate." if slab_rate is not None else "Dividend tax not deducted (pass --slab-rate).")),
        "portfolio_A": {"gross_return": _pct(c["A"]["value"], "weighted gross TR", c["A"]["why"]),
                        "costs_total": derived(costs_total, INR, formula="sum of per-pick round-trip costs"),
                        "dividends": derived(divs, INR, formula="sum of per-pick dividend approximations"),
                        "dividend_tax": derived(div_tax, INR, formula="dividends x --slab-rate") if slab_rate is not None
                        else missing("slab rate unknown; pass --slab-rate", INR),
                        **({"net": a_net} if a_net else {"net": missing("some picks lack returns or no picks", PCT, source="computed")}),
                        **({"net_stcg": derived(pt["net_stcg"], INR, formula="sum of short-term results after loss set-off"),
                            "net_ltcg": derived(pt["net_ltcg"], INR, formula="sum of long-term results after loss set-off")} if pt else {})},
        "cohorts": _cohort_block(c, bench, last), "comparisons": _comparisons(c),
        "calibration": {
            "brier_p_beat_benchmark": derived(brier(probs, outs), "score (0 best, 0.25 = always 0.5)", formula="mean((p - outcome)^2), outcome = gross TR > benchmark TR")
            if probs else missing("no picks with returns", None, source="computed"),
            "n_forecasts": num(len(probs), "count", source="computed"),
            "table": records_table(cal, ["bin", "n", "mean_forecast", "observed_frequency"], {"n": "count", "mean_forecast": "probability",
                                                                                              "observed_frequency": "share"}, source="computed",
                                   notes="few picks per run: pool runs before reading calibration"),
            "brier_scenarios": derived(sum(sc_scores) / len(sc_scores), "score (multi-class, 0 best)", formula="mean over picks of sum_k (p_k - 1[k realised])^2")
            if sc_scores else missing("scenarios carry no return ranges (or no picks), so the realised scenario is unknown", None, source="computed"),
        },
        "notes": list(getattr(market, "notes", [])) + ([f"INTERIM: horizon ends {horizon_end}"] if interim else []),
    }
    if write:
        out["template"] = write_template(run, out, ledger_dir)
        store.append([{"record_type": "postmortem", "record_id": rec_id,
                       "run_id": run_id, "at": now_iso(), "interim": interim, "as_of": last,
                       "cohorts": out["cohorts"], "portfolio_A": out["portfolio_A"], "calibration": {k: v for k, v in out["calibration"].items() if k != "table"},
                       "template": out["template"]}], ledger_dir)
    return out


def _v(x: dict | None, fmt: str = "{:.2f}") -> str:
    v = x.get("value") if isinstance(x, dict) else None
    return fmt.format(v) if v is not None else f"n/a ({(x or {}).get('notes') or 'missing'})"


def write_template(run: dict, pm: dict, ledger_dir: str | None) -> str:
    d = store.ledger_path(ledger_dir).parent / "postmortems"
    name = f"{run['run_id']}{'.interim-' + pm['marked_to'] if pm['interim'] else ''}.md"
    path = d / name
    if path.exists():
        raise InputError(f"{path} exists; postmortem templates are written once")
    lines = [f"# Post-mortem: {run['run_id']}{' (INTERIM)' if pm['interim'] else ''}", "",
             f"Frozen {run['frozen_at']}; entry {pm['entry_date']}; marked to {pm['as_of']}; horizon end {run['horizon_end']}.", "",
             "## Numbers (from `ledger postmortem`, do not edit)", "", "| Cohort | Total return % | Excess vs E (pp) | Members with returns |", "|---|---|---|---|"]
    for k, blk in pm["cohorts"].items():
        lines.append(f"| {k}: {run['cohort_definitions'][k]} | {_v(blk['total_return'])} | {_v(blk.get('excess_vs_E')) if k != 'E' else '-'} | "
                     f"{blk['n_with_returns']['value']}/{blk['n_members']['value']} |")
    net = pm["portfolio_A"].get("net")
    if isinstance(net, dict) and "with_exemption" in net:
        lines += ["", f"Portfolio A net return: {_v(net['with_exemption']['net_return'])}% with the LTCG exemption, "
                      f"{_v(net['without_exemption']['net_return'])}% without."]
    lines += ["", "Comparisons (pp): " + ", ".join(f"{k} {_v(v)}" for k, v in pm["comparisons"].items() if k != "how_to_read"),
              "", "How to read: " + "; ".join(READING) + ".",
              "", f"Brier (p beat benchmark): {_v(pm['calibration']['brier_p_beat_benchmark'], '{:.3f}')} over {pm['calibration']['n_forecasts']['value']} picks.",
              "", "## Per pick (fill in)", ""]
    for p in pm["picks"]["rows"]:
        lines += [f"### {p[0]}", "- What happened vs the thesis:", "- Did a kill criterion fire? When was it noticed?",
                  "- Was the scenario probability well calibrated?", "- Lesson:", ""]
    lines += ["## Pipeline (fill in)", "- Hunting (D vs E):", "- Deep dives (B vs D):", "- Red team (C vs A):", "- Portfolio construction (A vs B):",
              "", "## What to change next run (fill in)", ""]
    d.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    return str(path)
