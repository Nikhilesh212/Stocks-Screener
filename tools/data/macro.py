"""Macro snapshot with release/as-of dates.

* RBI homepage "Current Rates": policy repo, SDF, MSF, bank rate, CRR, SLR,
  INR reference rates, call money range and G-sec yields (each with RBI's as-on date).
* NSE FII/DII cash-market provisional flows (latest day only; history accumulates
  in the cache each time this runs).
* CPI: MOSPI API is tried; if unreachable the field is null with the reason, and
  the run must cite a dated MOSPI press release found via WebSearch instead.
Data is revised and released with lags: always carry the as_of / release date.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from ..common.cache import CACHE_ROOT, fetch
from ..common.http import SourceError
from ..common.periods import parse_date
from ..common.provenance import missing, num, today_ist
from ..common.sources import TTL_LIVE, nse_api
from ..common.units import INR_CR, PCT

RBI_HOME = "https://www.rbi.org.in/"
MOSPI_CPI = "https://api.mospi.gov.in/api/cpi/getCPIIndex"


def _rbi_text() -> tuple[str, str, str]:
    f = fetch(RBI_HOME, key="_market/rbi/home.html", ttl_hours=6.0)
    t = re.sub(r"<[^>]+>", " ", f.text())
    t = re.sub(r"&nbsp;", " ", t)
    return re.sub(r"\s+", " ", t), f.url, f.retrieved_at


def rbi_rates() -> dict:
    t, url, ts = _rbi_text()
    out = {}

    def grab(label, pattern, unit=PCT, key=None):
        m = re.search(pattern, t, re.I)
        out[key or label] = num(float(m.group(1)), unit, source="RBI homepage Current Rates", source_url=url, retrieved_at=ts,
                                as_of=None, notes="RBI shows the currently effective rate; check RBI press releases for the effective date") if m else \
            missing(f"pattern for {label} not found on RBI homepage", unit, source_url=url)

    grab("policy_repo_rate", r"Policy Repo Rate\s*:\s*([\d.]+)\s*%")
    grab("sdf_rate", r"Standing Deposit Facility Rate\s*:\s*([\d.]+)\s*%")
    grab("msf_rate", r"Marginal Standing Facility Rate\s*:\s*([\d.]+)\s*%")
    grab("crr", r"CRR\s*:\s*([\d.]+)\s*%")
    grab("slr", r"SLR\s*:\s*([\d.]+)\s*%")
    grab("inr_per_usd", r"INR\s*/\s*1\s*USD\s*:\s*([\d.]+)", unit="INR per USD (RBI reference rate)")
    asof_m = re.search(r"as on ([A-Z][a-z]+ \d{1,2}, \d{4})", t)
    gs_asof = dt.datetime.strptime(asof_m.group(1), "%B %d, %Y").date().isoformat() if asof_m else None
    gsecs = re.findall(r"([\d.]+)% GS (\d{4})\s*:\s*([\d.]+)%", t)
    if gsecs:
        target = today_ist().year + 10
        coupon, year, yld = min(gsecs, key=lambda g: abs(int(g[1]) - target))
        out["gsec_10y_proxy_yield"] = num(float(yld), PCT, as_of=gs_asof, source="RBI homepage Government Securities Market", source_url=url, retrieved_at=ts,
                                          notes=f"{coupon}% GS {year} (closest listed maturity to 10 years); RBI 'as on' date applies to market trends block")
        out["gsec_curve"] = [{"bond": f"{c}% GS {y}", "yield": num(float(v), PCT, as_of=gs_asof, source="RBI homepage", source_url=url, retrieved_at=ts)} for c, y, v in gsecs]
    else:
        out["gsec_10y_proxy_yield"] = missing("G-sec block not found on RBI homepage", PCT, source_url=url)
    return out


def fii_dii() -> dict:
    data, f = nse_api("fiidiiTradeReact", {}, key="_market/flows/fiidii_latest.json", ttl_hours=TTL_LIVE)
    out = {}
    hist = CACHE_ROOT / "_market" / "flows" / "fiidii_history.jsonl"
    hist.parent.mkdir(parents=True, exist_ok=True)
    seen = set(hist.read_text().splitlines()) if hist.exists() else set()
    with hist.open("a") as h:
        for r in data or []:
            line = json.dumps(r, sort_keys=True)
            if line not in seen:
                h.write(line + "\n")
            d = parse_date(r["date"]).isoformat()
            cat = "fii_fpi" if "FII" in r["category"] else "dii"
            out[f"{cat}_net"] = num(float(r["netValue"]), INR_CR, as_of=d, source="NSE FII/DII provisional cash-market data", source_url=f.url,
                                    retrieved_at=f.retrieved_at, notes="provisional, single day; NSDL publishes final FPI data")
    out["accumulated_history_file"] = str(hist)
    return out


def cpi() -> dict:
    try:
        f = fetch(f"{MOSPI_CPI}?Format=JSON&limit=24", key="_market/mospi/cpi_latest.json", ttl_hours=24.0, timeout=30)
        data = f.json()
        return {"cpi_raw_response": {"note": "MOSPI responded; schema not yet mapped", "keys": list(data)[:10] if isinstance(data, dict) else None,
                                     "source_url": f.url}}
    except (SourceError, ValueError) as e:
        return {"cpi_yoy": missing(f"MOSPI API unavailable ({e}); cite a dated MOSPI CPI press release via WebSearch", PCT, source_url=MOSPI_CPI)}


def cmd_macro(args) -> dict:
    out: dict = {"as_of_request": today_ist().isoformat(), "warnings": []}
    for name, fn in (("rbi", rbi_rates), ("flows", fii_dii), ("inflation", cpi)):
        try:
            out[name] = fn()
        except SourceError as e:
            out[name] = {"status": e.status, "error": str(e)}
            out["warnings"].append(f"{name}: {e}")
    out["not_covered"] = ["crude oil (no keyless primary source verified; cite dated source via WebSearch)",
                          "historical series for rates/CPI (snapshot only; cite RBI/MOSPI releases with dates)"]
    return out


def register(sub, leaf) -> None:
    p = leaf(sub, "macro", "RBI rates, INR/USD, G-sec yields, FII/DII flows, CPI (with as-of dates)")
    p.set_defaults(func=cmd_macro)
