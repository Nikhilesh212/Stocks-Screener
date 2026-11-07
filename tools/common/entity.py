"""Entity resolution: symbol / ISIN / name -> one listed company, or an explicit ambiguity.

Never guesses on a fuzzy name match: if the query does not identify exactly one
company, the caller gets status "ambiguous" with candidates, so an entity
mismatch cannot slip through silently.
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
from dataclasses import asdict, dataclass, field

import pandas as pd

from .cache import fetch
from .http import SourceError
from .periods import parse_date
from .sources import (BSE_BHAV, NSE_ARCH, TTL_MASTER, latest_daily_file, read_csv_bytes)

ISIN_RE = re.compile(r"^IN[EF0-9][A-Z0-9]{9}$")

INDEX_FILES = {
    "NIFTY 50": "ind_nifty50list.csv",
    "NIFTY NEXT 50": "ind_niftynext50list.csv",
    "NIFTY 100": "ind_nifty100list.csv",
    "NIFTY 200": "ind_nifty200list.csv",
    "NIFTY 500": "ind_nifty500list.csv",
    "NIFTY MIDCAP 150": "ind_niftymidcap150list.csv",
    "NIFTY SMALLCAP 250": "ind_niftysmallcap250list.csv",
    "NIFTY MICROCAP 250": "ind_niftymicrocap250_list.csv",
    "NIFTY TOTAL MARKET": "ind_niftytotalmarket_list.csv",
}


def same_issuer_equity(a: str | None, b: str | None) -> bool:
    """True if two ISINs are equity of the same issuer (INE + 4-char issuer + '01').

    Indian ISINs change on a face-value split (e.g. CAMS INE596I01012 -> INE596I01020),
    and exchange feeds keep the old ISIN on older records, so exact-match guards
    would silently drop real history.
    """
    return bool(a and b and a[:9] == b[:9])


class ResolutionError(Exception):
    def __init__(self, message: str, result: dict):
        super().__init__(message)
        self.result = result


@dataclass
class Entity:
    isin: str
    nse_symbol: str
    legal_name: str
    series: str | None
    board: str  # "main" | "sme"
    listing_date: str | None
    face_value_inr: float | None
    bse_code: str | None = None
    industry: str | None = None
    industry_source: str | None = None
    index_memberships: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def identity(self) -> dict:
        return {"isin": self.isin, "nse_symbol": self.nse_symbol, "bse_code": self.bse_code, "legal_name": self.legal_name}

    def to_dict(self) -> dict:
        return asdict(self)


def equity_master() -> pd.DataFrame:
    main = fetch(f"{NSE_ARCH}/content/equities/EQUITY_L.csv", key="_market/nse_master/EQUITY_L.csv", ttl_hours=TTL_MASTER)
    df = read_csv_bytes(main.content)
    df = df.rename(columns={"NAME OF COMPANY": "NAME", "ISIN NUMBER": "ISIN", "DATE OF LISTING": "LISTED", "FACE VALUE": "FV"})
    df["BOARD"] = "main"
    frames = [df[["SYMBOL", "NAME", "SERIES", "LISTED", "ISIN", "FV", "BOARD"]]]
    try:
        sme = fetch(f"{NSE_ARCH}/emerge/corporates/content/SME_EQUITY_L.csv", key="_market/nse_master/SME_EQUITY_L.csv", ttl_hours=TTL_MASTER)
        s = read_csv_bytes(sme.content)
        s = s.rename(columns={"NAME_OF_COMPANY": "NAME", "ISIN_NUMBER": "ISIN", "DATE_OF_LISTING": "LISTED", "FACE_VALUE": "FV"})
        s["BOARD"] = "sme"
        frames.append(s[["SYMBOL", "NAME", "SERIES", "LISTED", "ISIN", "FV", "BOARD"]])
    except SourceError:
        pass
    return pd.concat(frames, ignore_index=True)


def index_constituents(name: str) -> pd.DataFrame:
    fname = INDEX_FILES[name.upper()]
    f = fetch(f"{NSE_ARCH}/content/indices/{fname}", key=f"_market/nse_index_lists/{fname}", ttl_hours=TTL_MASTER)
    return read_csv_bytes(f.content)


def bse_code_map() -> tuple[dict[str, str], str | None]:
    """ISIN -> BSE scrip code from the latest BSE equity bhavcopy (plain public download)."""
    try:
        d, f = latest_daily_file(
            lambda d: BSE_BHAV.format(ymd=d.strftime("%Y%m%d")),
            lambda d: f"_market/bse_bhavcopy/{d.isoformat()}.csv",
        )
    except SourceError:
        return {}, None
    df = read_csv_bytes(f.content, dtype=str)
    return dict(zip(df["ISIN"], df["FinInstrmId"])), f.url


def _norm(name: str) -> list[str]:
    t = name.lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    stop = {"limited", "ltd", "the", "and", "of", "india", "co", "company", "corporation", "corp"}
    toks = [w for w in t.split() if w not in stop]
    return toks or t.split()


def _entity_from_row(row: pd.Series, memberships: list[str], industry: str | None, ind_src: str | None) -> Entity:
    listed = row.get("LISTED")
    try:
        listed_iso = parse_date(listed).isoformat() if isinstance(listed, str) else None
    except ValueError:
        listed_iso = None
    fv = pd.to_numeric(row.get("FV"), errors="coerce")
    return Entity(
        isin=str(row["ISIN"]), nse_symbol=str(row["SYMBOL"]), legal_name=str(row["NAME"]),
        series=str(row["SERIES"]) if pd.notna(row["SERIES"]) else None, board=str(row["BOARD"]),
        listing_date=listed_iso, face_value_inr=None if pd.isna(fv) else float(fv),
        industry=industry, industry_source=ind_src, index_memberships=memberships,
        sources=[f"{NSE_ARCH}/content/equities/EQUITY_L.csv"],
    )


def _memberships(isin: str) -> tuple[list[str], str | None, str | None]:
    out, industry, src = [], None, None
    for name, fname in INDEX_FILES.items():
        try:
            df = index_constituents(name)
        except SourceError:
            continue
        hit = df[df["ISIN Code"] == isin]
        if len(hit):
            out.append(name)
            if industry is None and "Industry" in df.columns:
                industry, src = str(hit.iloc[0]["Industry"]), f"{NSE_ARCH}/content/indices/{fname}"
    return out, industry, src


def resolve(query: str, *, with_bse: bool = True) -> dict:
    """Return {"status": "resolved"|"ambiguous"|"not_found", "entity": {...}?, "candidates": [...]}"""
    q = query.strip()
    m = equity_master()
    if ISIN_RE.match(q.upper()):
        hits = m[m["ISIN"] == q.upper()]
        how = "isin"
    else:
        hits = m[m["SYMBOL"].str.upper() == q.upper()]
        how = "symbol"
        if hits.empty:
            how = "name"
            qt = _norm(q)
            mask = m["NAME"].map(lambda n: all(t in _norm(n) for t in qt))
            hits = m[mask]
            if len(hits) > 1:
                exact = hits[hits["NAME"].map(lambda n: _norm(n) == qt)]
                if len(exact) == 1:
                    hits = exact
    # one company can appear twice (EQ on main board is unique; guard anyway)
    hits = hits.drop_duplicates(subset=["ISIN"])
    if len(hits) == 1:
        row = hits.iloc[0]
        mem, ind, src = _memberships(str(row["ISIN"]))
        e = _entity_from_row(row, mem, ind, src)
        if with_bse:
            codes, url = bse_code_map()
            e.bse_code = codes.get(e.isin)
            if url:
                e.sources.append(url)
        return {"status": "resolved", "matched_by": how, "entity": e.to_dict(), "candidates": []}
    if len(hits) > 1:
        cands = hits[["SYMBOL", "NAME", "ISIN", "BOARD"]].head(10).to_dict("records")
        return {"status": "ambiguous", "matched_by": how, "entity": None, "candidates": cands}
    names = m["NAME"].tolist()
    close = difflib.get_close_matches(q, names, n=5, cutoff=0.6)
    cands = m[m["NAME"].isin(close)][["SYMBOL", "NAME", "ISIN", "BOARD"]].to_dict("records")
    return {"status": "not_found" if not cands else "ambiguous", "matched_by": "fuzzy", "entity": None, "candidates": cands}


def get_entity(query: str, *, with_bse: bool = False) -> Entity:
    """Strict lookup for every other tool: must resolve to exactly one company."""
    r = resolve(query, with_bse=with_bse)
    if r["status"] != "resolved":
        raise ResolutionError(f"{query!r} did not resolve uniquely ({r['status']}); run `data resolve` and pass the ISIN", r)
    return Entity(**r["entity"])
