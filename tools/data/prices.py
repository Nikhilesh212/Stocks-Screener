"""Daily prices with corporate-action adjustment, delivery %, and a total-return series.

Primary source: NSE security-wise historical data (price, volume, deliverable).
Every adjustment factor parsed from a corporate-action text is checked against the
observed overnight gap (previous close / ex-date open). NSE's published previous
close is NOT adjusted on ex-dates (verified on RELIANCE bonus, 28-Oct-2024), so the
gap is the only exchange-side check; a gap outside +/-15% of the factor is flagged.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from ..common.cache import CACHE_ROOT
from ..common.entity import Entity, get_entity
from ..common.http import SourceError
from ..common.periods import nse_date, parse_date
from ..common.provenance import num, table, today_ist
from ..common.sources import bhavcopy_key, bhavcopy_url, nse_api, read_csv_bytes
from ..common.cache import fetch
from ..common.units import INR, INR_CR, PCT
from .corpactions import CorpAction, corporate_actions

SOURCE = "NSE security-wise historical data (priceVolumeDeliverable)"
API_PATH = "historicalOR/generateSecurityWiseHistoricalData"
PREFERRED_SERIES = ("EQ", "BE", "BZ", "SM", "ST")
GAP_TOL = 0.15          # overnight move allowed around a parsed factor
UNEXPLAINED_GAP = 0.25  # overnight gap that suggests an unlisted corporate action
ROW_CAP = 70            # NSE security-wise history returns at most this many rows per call (the latest ones)


def _chunks(start: dt.date, end: dt.date, days: int = 90):
    # the NSE endpoint silently returns only the latest ~70 rows of a longer range
    s = start
    while s <= end:
        e = min(end, s + dt.timedelta(days=days - 1))
        yield s, e
        s = e + dt.timedelta(days=1)


def _chunk_rows(entity: Entity, s: dt.date, e: dt.date, today: dt.date, urls: list[str]) -> list[dict]:
    """Rows for s..e; a chunk that hits the row cap (e.g. two series traded, EQ and IL) is split in halves and refetched."""
    immutable = e < today - dt.timedelta(days=5)
    params = {"from": nse_date(s), "to": nse_date(e), "symbol": entity.nse_symbol, "type": "priceVolumeDeliverable", "series": "ALL"}
    data, f = nse_api(API_PATH, params, key=f"{entity.isin}/nse_price/{s.isoformat()}_{e.isoformat()}.json",
                      ttl_hours=None if immutable else 6.0)
    urls.append(f.url)
    got = (data or {}).get("data", [])
    if got:
        first = min(parse_date(r["mTIMESTAMP"]) for r in got)
        if len(got) >= ROW_CAP or first > s + dt.timedelta(days=10):
            if (e - s).days < 14:
                raise SourceError(f"NSE returned a truncated chunk {s}..{e} ({len(got)} rows, first {first}) even after splitting")
            mid = s + (e - s) // 2
            return _chunk_rows(entity, s, mid, today, urls) + _chunk_rows(entity, mid + dt.timedelta(days=1), e, today, urls)
    return got


def raw_history(entity: Entity, start: dt.date, end: dt.date) -> tuple[pd.DataFrame, list[str]]:
    rows, urls = [], []
    today = today_ist()
    for s, e in _chunks(start, end):
        rows.extend(_chunk_rows(entity, s, e, today, urls))
    if not rows:
        return pd.DataFrame(), urls
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "date": df["mTIMESTAMP"].map(parse_date),
        "series": df["CH_SERIES"].astype(str),
        "prev_close": pd.to_numeric(df["CH_PREVIOUS_CLS_PRICE"], errors="coerce"),
        "open": pd.to_numeric(df["CH_OPENING_PRICE"], errors="coerce"),
        "high": pd.to_numeric(df["CH_TRADE_HIGH_PRICE"], errors="coerce"),
        "low": pd.to_numeric(df["CH_TRADE_LOW_PRICE"], errors="coerce"),
        "close": pd.to_numeric(df["CH_CLOSING_PRICE"], errors="coerce"),
        "vwap": pd.to_numeric(df.get("VWAP"), errors="coerce"),
        "volume": pd.to_numeric(df["CH_TOT_TRADED_QTY"], errors="coerce"),
        "value_inr": pd.to_numeric(df["CH_TOT_TRADED_VAL"], errors="coerce"),
        "delivery_qty": pd.to_numeric(df.get("COP_DELIV_QTY"), errors="coerce"),
        "delivery_pct": pd.to_numeric(df.get("COP_DELIV_PERC"), errors="coerce"),
    })
    out = out[out["series"].isin(PREFERRED_SERIES)]
    out["rank"] = out["series"].map({s: i for i, s in enumerate(PREFERRED_SERIES)})
    out = out.sort_values(["date", "rank"]).drop_duplicates("date", keep="first").drop(columns="rank")
    return out.sort_values("date").reset_index(drop=True), urls


def _rights_factor(a: CorpAction, face_value: float | None, cum_price: float) -> float | None:
    """Theoretical factor from 'Rights a:b @ Premium Rs P': TERP = (b*Pcum + a*Pissue)/(a+b)."""
    m = re.search(r"rights\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*@\s*premium\s*(?:rs|re)\.?\s*([\d.]+)", a.subject, re.I)
    if not m or face_value is None:
        return None
    ra, rb, prem = float(m.group(1)), float(m.group(2)), float(m.group(3))
    issue = face_value + prem
    if issue >= cum_price:
        return 1.0  # out-of-the-money rights carry no value
    terp = (rb * cum_price + ra * issue) / (ra + rb)
    return cum_price / terp


def adjust(raw: pd.DataFrame, actions: list[CorpAction], face_value: float | None = None) -> tuple[pd.DataFrame, list[dict], list[str]]:
    """Back-adjust prices for share-count events; build a dividend-reinvested TR series."""
    df = raw.copy().reset_index(drop=True)
    warnings: list[str] = []
    log: list[dict] = []
    dates = df["date"].tolist()
    events: list[tuple[dt.date, float]] = []
    action_dates = set()
    for a in actions:
        if not dates or a.ex_date > dates[-1] or a.ex_date <= dates[0]:
            log.append({**a.to_dict(), "applied_factor": None, "factor_source": None, "observed_gap": None,
                        "check": "outside price range"})
            continue
        i = next(k for k, d in enumerate(dates) if d >= a.ex_date)
        action_dates.add(dates[i])
        gap = float(df.at[i - 1, "close"] / df.at[i, "open"]) if df.at[i, "open"] else None
        applied, src, check = None, None, "n/a"
        if a.factor is not None:
            applied, src = a.factor, "parsed from corporate-action text"
            if gap is not None:
                diff = abs(gap / a.factor - 1)
                check = "ok" if diff <= GAP_TOL else f"CHECK: overnight gap {gap:.3f} vs factor {a.factor:.3f}"
                if diff > GAP_TOL:
                    warnings.append(f"{a.ex_date} {a.kind}: parsed factor {a.factor:.4f} but overnight gap {gap:.4f}; verify")
        elif a.kind == "rights":
            f = _rights_factor(a, face_value, float(df.at[i - 1, "close"]))
            if f is not None:
                applied, src, check = f, "theoretical ex-rights factor (TERP) from text and cum-rights close", "theoretical"
            else:
                check = "UNADJUSTED: rights terms not parseable"
                warnings.append(f"{a.ex_date}: rights issue not adjusted ('{a.subject}')")
        elif a.kind in ("demerger", "capital_reduction", "split", "bonus", "consolidation"):
            if gap is not None and abs(gap - 1) > 0.02:
                applied, src, check = gap, "APPROXIMATE: overnight gap on ex-date (includes market move)", "approximate"
                warnings.append(f"{a.ex_date} {a.kind}: factor approximated from overnight gap {gap:.4f}; treat returns across this date with care")
            else:
                check = "no adjustment (no material gap)"
        if applied is not None:
            events.append((dates[i], applied))
        log.append({**a.to_dict(), "applied_factor": applied, "factor_source": src, "observed_gap": gap, "check": check})

    gaps = df["close"].shift(1) / df["open"]
    for i in np.where((gaps - 1).abs() > UNEXPLAINED_GAP)[0]:
        if i > 0 and dates[i] not in action_dates:
            warnings.append(f"{dates[i]}: overnight gap {gaps.iat[i]:.3f} with no listed corporate action; possible missing action, series NOT adjusted")

    cum = np.ones(len(df))
    for d, f in events:
        cum[df["date"] < d] *= f
    df["adj_factor"] = cum
    for c in ("open", "high", "low", "close", "vwap"):
        df[f"adj_{c}"] = df[c] / cum
    df["adj_volume"] = df["volume"] * cum

    div = pd.Series(0.0, index=df.index)
    for a in actions:
        if a.kind == "dividend" and a.cash_per_share and dates and dates[0] < a.ex_date <= dates[-1]:
            i = next(k for k, d in enumerate(dates) if d >= a.ex_date)
            div.iat[i] += a.cash_per_share / cum[i]  # same share basis as that day's adjusted price
        elif a.kind == "dividend" and a.cash_per_share is None and dates and dates[0] < a.ex_date <= dates[-1]:
            warnings.append(f"{a.ex_date}: dividend amount not parseable from '{a.subject}'; excluded from TR series")
    prev = df["adj_close"].shift(1)
    gross = (df["adj_close"] + div) / prev
    gross.iat[0] = 1.0
    df["tr_index"] = 100 * gross.cumprod()
    df["dividend_adj"] = div
    return df, log, warnings


def history(entity: Entity, start: dt.date, end: dt.date) -> dict:
    raw, urls = raw_history(entity, start, end)
    if raw.empty:
        return {"df": raw, "urls": urls, "actions": [], "warnings": ["no price rows returned"], "ca_url": None}
    acts, ca_url, _ = corporate_actions(entity, start - dt.timedelta(days=5), end)
    adj, log, warns = adjust(raw, acts, entity.face_value_inr)
    path = CACHE_ROOT / entity.isin / "derived" / "prices_adjusted.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    adj.assign(date=pd.to_datetime(adj["date"])).to_parquet(path, index=False)
    return {"df": adj, "urls": urls, "actions": log, "warnings": warns, "ca_url": ca_url, "path": path}


def load_adjusted(isin: str) -> pd.DataFrame:
    p = CACHE_ROOT / isin / "derived" / "prices_adjusted.parquet"
    if not p.exists():
        raise FileNotFoundError(f"no cached price series for {isin}; run `data prices` first")
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def bhavcopy(d: dt.date) -> tuple[pd.DataFrame, str, str]:
    f = fetch(bhavcopy_url(d), key=bhavcopy_key(d), ttl_hours=None if d < today_ist() else 6.0)
    df = read_csv_bytes(f.content)
    for c in ("PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "LAST_PRICE", "CLOSE_PRICE", "AVG_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS", "NO_OF_TRADES", "DELIV_QTY", "DELIV_PER"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df, f.url, f.retrieved_at


# ---------------------------------------------------------------- CLI

CA_NUMBER_FIELDS = {"factor": "shares per pre-event share", "applied_factor": "shares per pre-event share",
                    "observed_gap": "ratio (prev close / ex-date open)", "cash_per_share": "INR/share"}


def actions_output(log: list[dict], ca_url: str | None) -> list[dict]:
    """Corporate-action log with every number wrapped in provenance."""
    out = []
    for a in log:
        rec = dict(a)
        for k, unit in CA_NUMBER_FIELDS.items():
            if k not in rec:
                continue
            if k == "observed_gap":
                rec[k] = num(rec[k], unit, as_of=a["ex_date"], source=f"computed from {SOURCE}", notes="previous close / ex-date open, unadjusted")
            elif k == "applied_factor":
                rec[k] = num(rec[k], unit, as_of=a["ex_date"], source=a.get("factor_source") or "not applied")
            else:
                rec[k] = num(rec[k], unit, as_of=a["ex_date"], source="parsed from NSE corporate-action subject", source_url=ca_url)
        out.append(rec)
    return out


def cmd_prices(args) -> dict:
    e = get_entity(args.query)
    end = parse_date(args.to) if args.to else today_ist()
    start = parse_date(args.start) if args.start else end - dt.timedelta(days=int(365.25 * args.years))
    h = history(e, start, end)
    df = h["df"]
    out = {"identity": e.identity(), "source": SOURCE, "trust": "high (exchange primary)", "source_urls": h["urls"][-3:],
           "corporate_actions_source": h["ca_url"], "corporate_actions": actions_output(h["actions"], h["ca_url"]), "warnings": h["warnings"]}
    if df.empty:
        out["last"] = None
        return out
    last = df.iloc[-1]
    asof = last["date"].isoformat()
    out.update({
        "range": {"from": df["date"].iloc[0].isoformat(), "to": asof}, "n_rows": int(len(df)),
        "cached_series_path": str(h["path"]),
        "last": {
            "close": num(float(last["close"]), INR, as_of=asof, source=SOURCE, source_url=h["urls"][-1]),
            "adj_close": num(float(last["adj_close"]), INR, as_of=asof, source="computed: close / cumulative adj_factor (factor 1 on latest date)"),
            "traded_value": num(float(last["value_inr"]) / 1e7, INR_CR, as_of=asof, source=SOURCE, source_url=h["urls"][-1]),
            "delivery_pct": num(None if pd.isna(last["delivery_pct"]) else float(last["delivery_pct"]), PCT, as_of=asof, source=SOURCE),
        },
    })
    # cross-check last close against the NSE bhavcopy archive (a separately published file)
    try:
        b, burl, _ = bhavcopy(last["date"])
        row = b[(b["SYMBOL"] == e.nse_symbol) & (b["SERIES"] == last["series"])]
        if len(row):
            bc = float(row.iloc[0]["CLOSE_PRICE"])
            diff = abs(bc / float(last["close"]) - 1)
            out["crosscheck_last_close"] = {"bhavcopy_close": num(bc, INR, as_of=asof, source="NSE bhavcopy archive", source_url=burl),
                                             "flag": diff > 0.02, "diff_pct": num(diff * 100, PCT, source="computed")}
    except SourceError as ex:
        out["crosscheck_last_close"] = {"flag": None, "error": str(ex)}
    if args.rows:
        cols = ["date", "series", "close", "adj_close", "adj_volume", "delivery_pct", "tr_index"]
        tail = df[cols].tail(args.rows)
        rows = [[r[0].isoformat(), r[1], *[None if pd.isna(x) else round(float(x), 4) for x in r[2:]]] for r in tail.itertuples(index=False)]
        out["rows"] = table(cols, rows, units={"close": INR, "adj_close": INR, "adj_volume": "shares", "delivery_pct": PCT, "tr_index": "index (100 = first row)"},
                            source=SOURCE, as_of=asof, notes="adj_* back-adjusted for bonus/split/rights; tr_index reinvests dividends")
    return out


def cmd_bhavcopy(args) -> dict:
    d = parse_date(args.date)
    df, url, ts = bhavcopy(d)
    syms = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    if syms:
        df = df[df["SYMBOL"].isin(syms)]
    df = df[df["SERIES"].isin(PREFERRED_SERIES)]
    cols = ["SYMBOL", "SERIES", "CLOSE_PRICE", "PREV_CLOSE", "TTL_TRD_QNTY", "TURNOVER_LACS", "DELIV_PER"]
    rows = [[r[0], r[1], *[None if pd.isna(x) else float(x) for x in r[2:]]] for r in df[cols].itertuples(index=False)]
    rows = [r[:5] + [None if r[5] is None else r[5] / 100] + r[6:] for r in rows]  # lakh -> crore
    cols = cols[:5] + ["TURNOVER_CR"] + cols[6:]
    missing_syms = sorted(set(syms) - set(df["SYMBOL"])) if syms else []
    return {"date": d.isoformat(), "missing_symbols": missing_syms,
            "data": table(cols, rows, units={"CLOSE_PRICE": INR, "PREV_CLOSE": INR, "TTL_TRD_QNTY": "shares", "TURNOVER_CR": INR_CR, "DELIV_PER": PCT},
                          source="NSE full bhavcopy (sec_bhavdata_full)", source_url=url, as_of=d.isoformat(), retrieved_at=ts,
                          notes="unadjusted; symbols only (resolve ISINs before comparing across dates)")}


def register(sub, leaf) -> None:
    p = leaf(sub, "prices", "Daily OHLCV adjusted for bonus/split/rights, delivery percent, dividend TR series")
    p.add_argument("query", help="NSE symbol or ISIN")
    p.add_argument("--from", dest="start", help="YYYY-MM-DD (default: --years back)")
    p.add_argument("--to", help="YYYY-MM-DD (default today)")
    p.add_argument("--years", type=float, default=3.0)
    p.add_argument("--rows", type=int, default=0, help="include the last N rows in output (full series is cached to parquet)")
    p.set_defaults(func=cmd_prices)
    b = leaf(sub, "bhavcopy", "Cross-section of all NSE closes/turnover/delivery for one date (unadjusted)")
    b.add_argument("--date", required=True)
    b.add_argument("--symbols", help="comma-separated NSE symbols")
    b.set_defaults(func=cmd_bhavcopy)
