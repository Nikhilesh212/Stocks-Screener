"""`ledger freeze <run_id>`: append approved picks and the run's cohorts to the ledger.

Input: `runs/<run_id>/freeze_input.json` (or --input):

    {"model_id": "...", "horizon_months": 12,            # horizon optional (default: mandate)
     "picks": [{"symbol": "CAMS", "weight": 0.08,
                "thesis": "three sentences",
                "scenarios": [{"name": "bull", "probability": 0.3, "return_pct": 35, "return_range_pct": [20, null]}, ...],
                "p_beat_benchmark": 0.55,
                "kill_criteria": ["..."], "review_dates": ["2027-02-15"]}],
     "cohorts": {"B": ["SYM", ...], "C": [...], "D": [...]}}   # optional; else read from the run folder

Cohorts not listed are read from the run folder: B = every `dossiers/<SYM>.json`
(conviction files skipped), C = `redteam/*.json` whose verdict is "killed" (or
"kill"), D = `candidates.json`. A = the
picks as weighted (cash = 1 - sum of weights); E = Nifty 500 TRI.
Entry is the close of the first trading session after the freeze date; the
price shown at freeze is a reference only.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from ..common.cache import REPO_ROOT
from ..common.errors import InputError
from ..common.provenance import missing, now_iso, num, today_ist
from ..common.units import INR, PCT
from ..compute._util import load_mandate
from . import store
from .market import BENCHMARK

ENTRY_RULE = "close of the first trading session after the freeze date (total return, dividends reinvested)"
COHORT_TEXT = {
    "A": "final portfolio, as weighted (cash earns 0)",
    "B": "equal weight of all deep-dived names",
    "C": "equal weight of names the red team killed",
    "D": "equal weight of the hunters' full candidate list",
    "E": f"{BENCHMARK} TRI",
}
KILL_VERDICTS = {"killed", "kill"}  # red-team verdicts: survives | weakened | killed
READING = ["B ~ A: portfolio construction adds nothing", "C beats A: the red team is destroying value",
           "D ~ B: the deep dives add nothing", "D ~ E: hunting adds nothing"]


def _syms(items) -> list[str]:
    out = []
    for x in items or []:
        s = x.get("symbol") or x.get("nse_symbol") or x.get("isin") if isinstance(x, dict) else x
        if s:
            out.append(str(s).strip().upper())
    return list(dict.fromkeys(out))


def discover_cohorts(run_dir: Path) -> tuple[dict[str, list[str]], list[str]]:
    """B/C/D from the run folder's files; notes say what was found."""
    out: dict[str, list[str]] = {"B": [], "C": [], "D": []}
    notes = []
    for f in sorted((run_dir / "dossiers").glob("*.json")):
        if f.name.endswith(".conviction.json"):
            continue  # probabilities live there, not identity; never read for cohorts
        d = json.loads(f.read_text())
        out["B"] += _syms([d.get("identity", d)])
    for f in sorted((run_dir / "redteam").glob("*.json")):
        d = json.loads(f.read_text())
        if str(d.get("verdict", "")).lower() in KILL_VERDICTS:
            out["C"] += _syms([d.get("identity", d)])
    cand = run_dir / "candidates.json"
    if cand.exists():
        d = json.loads(cand.read_text())
        out["D"] = _syms(d.get("candidates", d) if isinstance(d, dict) else d)
    for k, v in out.items():
        if not v:
            notes.append(f"cohort {k}: nothing found in {run_dir} (empty cohort)")
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}, notes


def validate(inp: dict) -> list[str]:
    errs = []
    picks = inp.get("picks")
    if not isinstance(picks, list):
        return ["`picks` must be a list (empty is allowed: index or cash is a valid outcome)"]
    tot = 0.0
    for i, p in enumerate(picks):
        tag = f"picks[{i}] {p.get('symbol')}"
        w = p.get("weight")
        if not isinstance(w, (int, float)) or w <= 0:
            errs.append(f"{tag}: weight must be > 0 (fraction of capital)")
        else:
            tot += w
        if not str(p.get("thesis", "")).strip():
            errs.append(f"{tag}: thesis missing")
        pb = p.get("p_beat_benchmark")
        if not isinstance(pb, (int, float)) or not 0 <= pb <= 1:
            errs.append(f"{tag}: p_beat_benchmark must be a probability in [0, 1]")
        sc = p.get("scenarios") or []
        if not sc:
            errs.append(f"{tag}: scenarios missing")
        elif abs(sum(float(s.get("probability", 0)) for s in sc) - 1) > 0.01:
            errs.append(f"{tag}: scenario probabilities sum to {sum(float(s.get('probability', 0)) for s in sc):.3f}, not 1")
        if not p.get("kill_criteria"):
            errs.append(f"{tag}: kill_criteria missing")
        for d in p.get("review_dates") or []:
            try:
                dt.date.fromisoformat(d)
            except (TypeError, ValueError):
                errs.append(f"{tag}: review date {d!r} is not YYYY-MM-DD")
    if tot > 1 + 1e-9:
        errs.append(f"weights sum to {tot:.4f} > 1 (no leverage)")
    syms = [str(p.get("symbol", "")).upper() for p in picks]
    if len(set(syms)) != len(syms):
        errs.append("duplicate symbols in picks")
    return errs


def _last(df: pd.DataFrame, col: str, until: dt.date) -> tuple[float | None, str | None]:
    """Last value on or before `until`."""
    d = df.dropna(subset=[col]) if col in df else df.iloc[0:0]
    d = d[d["date"] <= until]
    if d.empty:
        return None, None
    r = d.sort_values("date").iloc[-1]
    return float(r[col]), r["date"].isoformat()


def _scenario(s: dict) -> dict:
    rng = s.get("return_range_pct") or [None, None]
    return {"name": s.get("name"), "probability": num(float(s["probability"]), "probability", source="analyst (run)"),
            "return_pct": num(s.get("return_pct"), PCT, source="analyst (run)"),
            "return_range_lo_pct": num(rng[0], PCT, source="analyst (run)"), "return_range_hi_pct": num(rng[1], PCT, source="analyst (run)")}


def build_records(run_id: str, inp: dict, market, *, approval: str, run_dir: Path | None, frozen_at: str | None = None) -> tuple[list[dict], list[str]]:
    errs = validate(inp)
    if errs:
        raise InputError("freeze input invalid: " + "; ".join(errs))
    frozen_at = frozen_at or now_iso()
    fdate = dt.date.fromisoformat(frozen_at[:10])
    run_mandate = run_dir / "mandate.yaml" if run_dir is not None else None
    if run_mandate is not None and run_mandate.exists():
        mandate, mandate_src = load_mandate(run_mandate), f"runs/{run_id}/mandate.yaml"
    else:
        mandate, mandate_src = load_mandate(), "config/mandate.yaml"
    horizon = int(inp.get("horizon_months") or mandate.get("horizon_months") or 12)
    notes: list[str] = []
    cohorts_in = {k: _syms(v) for k, v in (inp.get("cohorts") or {}).items() if k in ("B", "C", "D")}
    missing_keys = [k for k in ("B", "C", "D") if k not in cohorts_in]
    if missing_keys:
        if run_dir is None or not run_dir.exists():
            raise InputError(f"cohorts {missing_keys} not listed in the input and no run folder to read them from")
        found, n = discover_cohorts(run_dir)
        notes += n
        for k in missing_keys:
            cohorts_in[k] = found[k]
    ident: dict[str, dict] = {}
    for s in {*(str(p["symbol"]).upper() for p in inp["picks"]), *(x for v in cohorts_in.values() for x in v)}:
        ident[s] = market.resolve(s)
    bench = market.index_tri(BENCHMARK)
    b_val, b_date = _last(bench, "tri", fdate)
    picks = []
    for p in inp["picks"]:
        sym = str(p["symbol"]).upper()
        idn = ident[sym]
        px = market.prices(idn["isin"], fdate - dt.timedelta(days=30))
        ref, ref_date = _last(px, "close", fdate)
        picks.append({
            "record_type": "pick", "record_id": f"{run_id}:{idn['isin']}", "run_id": run_id, "frozen_at": frozen_at,
            "model_id": inp.get("model_id"), "isin": idn["isin"], "symbol": idn["symbol"], "legal_name": idn.get("legal_name"),
            "weight": num(float(p["weight"]), "fraction of capital", source="analyst (run), approved by user"),
            "reference_price": (num(ref, INR, as_of=ref_date, source="NSE close (data prices cache)", notes="reference only; entry is the next-session close")
                                if ref is not None else missing("no cached price at freeze", INR)),
            "entry_rule": ENTRY_RULE,
            "thesis": p["thesis"], "scenarios": [_scenario(s) for s in p["scenarios"]],
            "p_beat_benchmark": num(float(p["p_beat_benchmark"]), "probability", source="analyst (run)"),
            "kill_criteria": p["kill_criteria"], "review_dates": p.get("review_dates") or [],
            "benchmark_at_freeze": num(b_val, "index points", as_of=b_date, source=f"niftyindices {BENCHMARK} TRI"),
        })
    weights = {pk["isin"]: pk["weight"]["value"] for pk in picks}
    cash = 1 - sum(weights.values())
    member = lambda syms: [{"symbol": ident[s]["symbol"], "isin": ident[s]["isin"]} for s in syms]  # noqa: E731
    horizon_end = (pd.Timestamp(fdate) + pd.DateOffset(months=horizon)).date().isoformat()
    run = {
        "record_type": "run", "record_id": f"{run_id}:run", "run_id": run_id, "frozen_at": frozen_at, "model_id": inp.get("model_id"),
        "approval": approval, "horizon_months": num(horizon, "months", source=f"freeze input or {mandate_src}"), "horizon_end": horizon_end,
        "entry_rule": ENTRY_RULE, "benchmark": f"{BENCHMARK} TRI",
        "benchmark_at_freeze": num(b_val, "index points", as_of=b_date, source=f"niftyindices {BENCHMARK} TRI"),
        "cohorts": {
            "A": {"members": [{"symbol": pk["symbol"], "isin": pk["isin"], "weight": pk["weight"]} for pk in picks],
                  "cash": num(cash, "fraction of capital", source="1 - sum(weights)")},
            "B": {"members": member(cohorts_in["B"])}, "C": {"members": member(cohorts_in["C"])},
            "D": {"members": member(cohorts_in["D"])}, "E": {"index": f"{BENCHMARK} TRI"},
        },
        "cohort_definitions": COHORT_TEXT, "how_to_read": READING,
        "capital_inr": num(mandate.get("capital_inr"), INR, source=mandate_src) if mandate.get("capital_inr") else missing(
            "capital_inr not set; postmortem uses a notional INR 10 lakh for costs", INR),
        "notes": notes + list(getattr(market, "notes", [])),
    }
    return [run, *picks], notes


def freeze(run_id: str, *, input_path: str | None, approval: str, ledger_dir: str | None, market, frozen_at: str | None = None) -> dict:
    if not approval or not approval.strip():
        raise InputError("freeze needs --approved '<who/when the user approved>': it runs only after explicit user approval")
    run_dir = REPO_ROOT / "runs" / run_id
    path = Path(input_path) if input_path else run_dir / "freeze_input.json"
    if not path.exists():
        raise InputError(f"no freeze input at {path}")
    inp = json.loads(path.read_text())
    existing = [r for r in store.read_all(ledger_dir) if r.get("run_id") == run_id and r.get("record_type") == "run"]
    if existing:
        raise InputError(f"run {run_id} is already frozen ({existing[0]['frozen_at']}); use `ledger correct` for changes")
    records, notes = build_records(run_id, inp, market, approval=approval, run_dir=run_dir, frozen_at=frozen_at)
    p = store.append(records, ledger_dir)
    return {"ledger": str(p), "run_id": run_id, "n_records": len(records), "n_picks": len(records) - 1,
            "run": records[0], "picks": records[1:], "notes": notes}


def today() -> dt.date:
    return today_ist()
