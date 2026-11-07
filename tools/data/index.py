"""Index levels (price), Total Return Index, and index P/E, P/B, dividend yield.

Sources (verified 2026-11-08):
* price OHLC: NSE historicalOR/indicesHistory (chunked; endpoint caps rows per call)
* TRI:        niftyindices.com BackPage/getTotalReturnIndexString (<=1 year per call)
* P/E,P/B,DY: niftyindices.com BackPage/getpepbHistoricaldataDBtoString (<=1 year per call)
Past chunks are cached forever; the current chunk refreshes after 6 hours.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from ..common.cache import CACHE_ROOT
from ..common.entity import INDEX_FILES, index_constituents
from ..common.http import SourceError
from ..common.periods import nse_date, parse_date
from ..common.provenance import num, table, today_ist
from ..common.sources import (ind_close_key, ind_close_url, latest_daily_file, niftyindices_post, nse_api,
                              read_csv_bytes)
from ..common.units import PCT, RATIO

SRC_PRICE = "NSE indices history API"
SRC_TRI = "niftyindices.com Total Returns Index"
SRC_PEPB = "niftyindices.com P/E, P/B, dividend yield history"


def _chunks(start: dt.date, end: dt.date, days: int):
    s = start
    while s <= end:
        e = min(end, s + dt.timedelta(days=days - 1))
        yield s, e
        s = e + dt.timedelta(days=1)


def _ttl(e: dt.date) -> float | None:
    return None if e < today_ist() - dt.timedelta(days=5) else 6.0


def _slug(name: str) -> str:
    return name.upper().replace(" ", "_").replace("&", "AND")


def price_history(name: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    rows = []
    for s, e in _chunks(start, end, 90):
        data, _ = nse_api("historicalOR/indicesHistory", {"indexType": name.upper(), "from": nse_date(s), "to": nse_date(e)},
                          key=f"_market/index_price/{_slug(name)}/{s}_{e}.json", ttl_hours=_ttl(e))
        recs = (data or {}).get("data", [])
        if isinstance(recs, dict):  # older response shape
            recs = recs.get("indexCloseOnlineRecords", [])
        rows += recs
    if not rows:
        return pd.DataFrame(columns=["date", "close"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "date": df["EOD_TIMESTAMP"].map(parse_date),
        "open": pd.to_numeric(df["EOD_OPEN_INDEX_VAL"], errors="coerce"),
        "high": pd.to_numeric(df["EOD_HIGH_INDEX_VAL"], errors="coerce"),
        "low": pd.to_numeric(df["EOD_LOW_INDEX_VAL"], errors="coerce"),
        "close": pd.to_numeric(df["EOD_CLOSE_INDEX_VAL"], errors="coerce"),
    }).drop_duplicates("date").sort_values("date")


def _nifty_series(endpoint: str, name: str, start: dt.date, end: dt.date, kind: str) -> list[dict]:
    rows = []
    for s, e in _chunks(start, end, 365):
        cinfo = {"name": name.upper(), "startDate": s.strftime("%d-%b-%Y"), "endDate": e.strftime("%d-%b-%Y"), "indexName": name.upper()}
        data, _ = niftyindices_post(endpoint, cinfo, key=f"_market/index_{kind}/{_slug(name)}/{s}_{e}.json", ttl_hours=_ttl(e))
        rows += data or []
    return rows


def tri_history(name: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    rows = _nifty_series("getTotalReturnIndexString", name, start, end, "tri")
    if not rows:
        return pd.DataFrame(columns=["date", "tri"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({"date": df["Date"].map(parse_date), "tri": pd.to_numeric(df["TotalReturnsIndex"], errors="coerce"),
                         "net_tri": pd.to_numeric(df.get("NTR_Value"), errors="coerce")}).drop_duplicates("date").sort_values("date")


def pepb_history(name: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    rows = _nifty_series("getpepbHistoricaldataDBtoString", name, start, end, "pepb")
    if not rows:
        return pd.DataFrame(columns=["date", "pe", "pb", "div_yield"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({"date": df["DATE"].map(parse_date), "pe": pd.to_numeric(df["pe"], errors="coerce"),
                         "pb": pd.to_numeric(df["pb"], errors="coerce"),
                         "div_yield": pd.to_numeric(df["divYield"], errors="coerce")}).drop_duplicates("date").sort_values("date")


def combined(name: str, start: dt.date, end: dt.date, parts: set[str]) -> tuple[pd.DataFrame, dict, list[str]]:
    frames, status, warns = [], {}, []
    for part, fn in (("price", price_history), ("tri", tri_history), ("pepb", pepb_history)):
        if part not in parts:
            continue
        try:
            f = fn(name, start, end)
            status[part] = "ok" if len(f) else "empty"
            frames.append(f.set_index("date"))
        except SourceError as e:
            status[part] = f"{e.status}: {e}"
            warns.append(f"{part} unavailable: {e}")
    df = pd.concat(frames, axis=1).sort_index() if frames else pd.DataFrame()
    df.index.name = "date"
    df = df.reset_index()
    path = CACHE_ROOT / "_market" / "derived" / f"index_{_slug(name)}.parquet"
    if len(df):
        path.parent.mkdir(parents=True, exist_ok=True)
        prev = pd.read_parquet(path) if path.exists() else None
        out = df.assign(date=pd.to_datetime(df["date"]))
        if prev is not None:
            out = pd.concat([prev, out]).drop_duplicates("date", keep="last").sort_values("date")
        out.to_parquet(path, index=False)
    return df, status, warns


def load_index(name: str) -> pd.DataFrame:
    p = CACHE_ROOT / "_market" / "derived" / f"index_{_slug(name)}.parquet"
    if not p.exists():
        raise FileNotFoundError(f"no cached series for {name}; run `data index history \"{name}\"` first")
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


# ---------------------------------------------------------------- CLI

def cmd_history(args) -> dict:
    end = parse_date(args.to) if args.to else today_ist()
    start = parse_date(args.start) if args.start else end - dt.timedelta(days=int(365.25 * args.years))
    parts = set(args.parts.split(","))
    df, status, warns = combined(args.name, start, end, parts)
    out = {"index": args.name.upper(), "requested": {"from": start.isoformat(), "to": end.isoformat()}, "part_status": status,
           "warnings": warns, "cached_series_path": str(CACHE_ROOT / "_market" / "derived" / f"index_{_slug(args.name)}.parquet")}
    if df.empty:
        return out
    out["n_rows"] = int(len(df))
    latest = {}
    for col, unit, src in (("close", "index points", SRC_PRICE), ("tri", "index points", SRC_TRI), ("pe", RATIO, SRC_PEPB),
                           ("pb", RATIO, SRC_PEPB), ("div_yield", PCT, SRC_PEPB)):
        if col in df.columns and df[col].notna().any():
            r = df[df[col].notna()].iloc[-1]
            first = df[df[col].notna()].iloc[0]
            latest[col] = num(float(r[col]), unit, as_of=r["date"].isoformat(), source=src,
                              notes=f"series available from {first['date'].isoformat()} in this request")
    out["latest"] = latest
    if args.rows:
        cols = [c for c in ("close", "tri", "pe", "pb", "div_yield") if c in df.columns]
        tail = df[["date", *cols]].tail(args.rows)
        out["rows"] = table(["date", *cols], [[r[0].isoformat(), *[None if pd.isna(x) else float(x) for x in r[1:]]] for r in tail.itertuples(index=False)],
                            units={"close": "points", "tri": "points", "pe": RATIO, "pb": RATIO, "div_yield": PCT},
                            source=f"{SRC_PRICE}; {SRC_TRI}; {SRC_PEPB}", as_of=tail["date"].iloc[-1].isoformat())
    return out


def cmd_constituents(args) -> dict:
    df = index_constituents(args.name)
    rows = df[["Symbol", "Company Name", "Industry", "ISIN Code"]].values.tolist()
    return {"index": args.name.upper(), "n_items": len(rows), "constituents": [dict(zip(["symbol", "name", "industry", "isin"], r)) for r in rows],
            "source_url": f"https://nsearchives.nseindia.com/content/indices/{INDEX_FILES[args.name.upper()]}"}


def cmd_snapshot(args) -> dict:
    """All NSE indices for the latest trading day: close, P/E, P/B, dividend yield."""
    d, f = latest_daily_file(ind_close_url, ind_close_key)
    df = read_csv_bytes(f.content)
    names = [n.strip().upper() for n in args.names.split(",")] if args.names else None
    if names:
        df = df[df["Index Name"].str.upper().isin(names)]
    cols = ["Index Name", "Closing Index Value", "Change(%)", "P/E", "P/B", "Div Yield"]
    rows = [[r[0], *[pd.to_numeric(x, errors="coerce") for x in r[1:]]] for r in df[cols].itertuples(index=False)]
    rows = [[r[0], *[None if pd.isna(x) else float(x) for x in r[1:]]] for r in rows]
    return {"date": d.isoformat(), "data": table(["index", "close", "change_pct", "pe", "pb", "div_yield"], rows,
            units={"close": "points", "change_pct": PCT, "pe": RATIO, "pb": RATIO, "div_yield": PCT},
            source="NSE ind_close_all daily archive", source_url=f.url, as_of=d.isoformat(), retrieved_at=f.retrieved_at)}


def register(sub, leaf) -> None:
    p = leaf(sub, "index", "Index history (price, TRI, P/E-P/B-DY), constituents, or a snapshot of all NSE indices")
    s = p.add_subparsers(dest="index_cmd", required=True)
    h = leaf(s, "history", "Price/TRI/valuation history for one index (e.g. 'NIFTY 500')")
    h.add_argument("name")
    h.add_argument("--from", dest="start")
    h.add_argument("--to")
    h.add_argument("--years", type=float, default=3.0)
    h.add_argument("--parts", default="price,tri,pepb")
    h.add_argument("--rows", type=int, default=0)
    h.set_defaults(func=cmd_history)
    c = leaf(s, "constituents", "Current constituents of a Nifty index")
    c.add_argument("name", choices=sorted(INDEX_FILES), type=str.upper)
    c.set_defaults(func=cmd_constituents)
    n = leaf(s, "snapshot", "Latest close, P/E, P/B, DY for all (or named) NSE indices incl. sector indices")
    n.add_argument("--names", help="comma-separated index names, e.g. 'Nifty 500,Nifty Bank'")
    n.set_defaults(func=cmd_snapshot)
