"""`python -m tools smoke`: hit live sources for a few companies and print a status table.

Unit tests never touch the network; this command is the only live check.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback

from .common.cache import CACHE_ROOT
from .common.http import SourceError
from .common.provenance import find_bare_numbers, now_iso

DEFAULT_SYMBOLS = "RELIANCE,HDFCBANK,CAMS"


def _run(parser, argv: list[str]) -> tuple[str, dict, float]:
    args = parser.parse_args(argv)
    t0 = time.time()
    try:
        out = args.func(args)
        return "ok", out, time.time() - t0
    except SourceError as e:
        return e.status, {"error": str(e)}, time.time() - t0
    except Exception as e:  # smoke must report, not crash
        return "error", {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=3)}, time.time() - t0


def _note(cmd: str, out: dict) -> str:
    if "error" in out:
        return out["error"][:140]
    if cmd == "prices":
        acts = [a for a in out.get("corporate_actions", []) if (a.get("applied_factor") or {}).get("value")]
        checks = ", ".join(f"{a['ex_date']} {a['kind']} x{a['applied_factor']['value']:.3g} [{a['check']}]" for a in acts) or "no share-count events"
        return f"{out.get('n_rows')} rows to {out.get('range', {}).get('to')}; {checks}; xcheck flag={out.get('crosscheck_last_close', {}).get('flag')}"
    if cmd == "financials":
        q = out.get("quarterly", {})
        flags = [r for r in out.get("crosschecks", {}).get("rows", []) if r[-1]]
        cov = out.get("coverage") or {}
        return (f"{len(q.get('rows', []))} quarters, latest {q.get('rows', [[None]])[0][0] if q.get('rows') else None}; bank_format={out.get('is_bank_format')}; "
                f"crosscheck flags={len(flags)}; missing quarters={cov.get('missing_quarters')}; warnings={len(out.get('warnings', []))}")
    if cmd == "shareholding":
        rows = out.get("shareholding", {}).get("rows", [])
        return f"{len(rows)} quarters; latest {rows[0][0] if rows else None}"
    if cmd == "filings":
        return f"{out.get('n_items')} announcements; {len(out.get('transcripts', []))} transcripts, {len(out.get('presentations', []))} presentations, {len(out.get('annual_reports', []))} ARs"
    if cmd == "events":
        return f"surveillance={out.get('surveillance', {}).get('on_surveillance')}; upcoming meetings={len(out.get('upcoming_board_meetings', []))}"
    if cmd == "resolve":
        e = out.get("entity") or {}
        return f"{out.get('status')}: {e.get('isin')} BSE {e.get('bse_code')} {e.get('index_memberships')}"
    return ""


def cmd_smoke(args) -> dict:
    from .cli import build_parser
    parser = build_parser()
    rows = []
    bare = []
    per_symbol = [
        ("resolve", ["data", "resolve", "{s}"]),
        ("prices", ["data", "prices", "{s}", "--years", "3"]),
        ("financials", ["data", "financials", "{s}", "--quarters", "8", "--years", "6"]),
        ("shareholding", ["data", "shareholding", "{s}", "--quarters", "8"]),
        ("filings", ["data", "filings", "list", "{s}", "--months", "12"]),
        ("events", ["data", "events", "{s}"]),
    ]
    for sym in args.symbols.split(","):
        for name, tmpl in per_symbol:
            status, out, secs = _run(parser, [x.format(s=sym) for x in tmpl])
            if name == "financials" and status == "ok" and not out.get("filings_used"):
                status, out, secs = _run(parser, [x.format(s=sym) for x in tmpl] + ["--basis", "standalone"])
            bare += [f"{name} {sym}: {p}" for p in find_bare_numbers(out)[:3]]
            rows.append({"source_command": name, "symbol": sym, "status": status, "seconds": round(secs, 1), "note": _note(name, out)})
    market = [
        ("index NIFTY 500 (price,TRI,PE)", ["data", "index", "history", "NIFTY 500", "--years", "1"]),
        ("index snapshot (all NSE indices)", ["data", "index", "snapshot", "--names", "Nifty 500,Nifty 50,Nifty Bank"]),
        ("macro (RBI, flows, CPI)", ["data", "macro"]),
    ]
    for name, argv in market:
        status, out, secs = _run(parser, argv)
        note = out.get("error") or (json.dumps(out.get("part_status") or out.get("warnings"))[:140] if (out.get("part_status") or out.get("warnings")) else "")
        if not note and isinstance(out.get("data"), dict):
            note = f"{len(out['data'].get('rows', []))} rows as of {out.get('date') or out['data'].get('as_of')}"
        if name.startswith("macro") and status == "ok":
            cpi = out.get("inflation", {})
            note = f"RBI ok={'policy_repo_rate' in out.get('rbi', {})}; flows ok={'fii_fpi_net' in out.get('flows', {})}; CPI={'unavailable' if 'cpi_yoy' in cpi else 'responded'}"
        bare += [f"{name}: {p}" for p in find_bare_numbers(out)[:3]]
        rows.append({"source_command": name, "symbol": "-", "status": status, "seconds": round(secs, 1), "note": note})
    result = {"run_at": now_iso(), "symbols": args.symbols, "results": rows, "bare_number_violations": bare}
    (CACHE_ROOT / "smoke_status.json").parent.mkdir(parents=True, exist_ok=True)
    (CACHE_ROOT / "smoke_status.json").write_text(json.dumps(result, indent=1))
    if args.table:
        import sys
        w = max(len(r["source_command"]) for r in rows)
        for r in rows:
            print(f"{r['source_command']:<{w}}  {r['symbol']:<9} {r['status']:<11} {r['seconds']:>6}s  {r['note']}", file=sys.stderr)
    return result


def register(groups, leaf) -> None:
    p = leaf(groups, "smoke", "Hit live sources for a few symbols and report a status table (also saved to data/cache/smoke_status.json)")
    p.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    p.add_argument("--table", action="store_true", help="also print a human-readable table to stderr")
    p.set_defaults(func=cmd_smoke)
