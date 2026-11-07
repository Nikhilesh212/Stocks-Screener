"""Market access for the ledger: identity, total-return series, benchmark TRI, announcements.

`LiveMarket` reads the data-layer cache and, unless told not to, refreshes a
series that is missing or stale. Tests pass a stub with the same methods.
"""
from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from ..common.provenance import today_ist

log = logging.getLogger(__name__)
BENCHMARK = "NIFTY 500"
STALE_DAYS = 4


class LiveMarket:
    def __init__(self, fetch: bool = True):
        self.fetch = fetch
        self.notes: list[str] = []

    def resolve(self, query: str) -> dict:
        from ..common.entity import get_entity
        e = get_entity(query)
        return {"isin": e.isin, "symbol": e.nse_symbol, "legal_name": e.legal_name}

    def prices(self, isin: str, since: dt.date) -> pd.DataFrame:
        """Daily series with date, close, adj_close, tr_index (dividends reinvested)."""
        from ..common.entity import get_entity
        from ..data.prices import history, load_adjusted
        try:
            df = load_adjusted(isin)
        except FileNotFoundError:
            df = None
        stale = df is None or df["date"].min() > since or df["date"].max() < today_ist() - dt.timedelta(days=STALE_DAYS)
        if stale and self.fetch:
            start = min(since, df["date"].min()) if df is not None else since
            res = history(get_entity(isin), start - dt.timedelta(days=10), today_ist())
            self.notes.extend(f"{isin}: {w}" for w in res.get("warnings", []))
            df = load_adjusted(isin)
        elif stale:
            self.notes.append(f"{isin}: cached prices end {None if df is None else df['date'].max()} (not refreshed: --no-fetch)")
        return df if df is not None else pd.DataFrame(columns=["date", "close", "adj_close", "tr_index"])

    def index_tri(self, name: str = BENCHMARK) -> pd.DataFrame:
        from ..data.index import combined, load_index
        try:
            df = load_index(name)
        except FileNotFoundError:
            df = None
        last = None if df is None or "tri" not in df else df.dropna(subset=["tri"])["date"].max()
        if (last is None or last < today_ist() - dt.timedelta(days=STALE_DAYS)) and self.fetch:
            start = (last or today_ist() - dt.timedelta(days=800)) - dt.timedelta(days=5)
            _, _, warns = combined(name, start, today_ist(), {"tri"})
            self.notes.extend(warns)
            df = load_index(name)
        return df[["date", "tri"]].dropna() if df is not None and "tri" in df else pd.DataFrame(columns=["date", "tri"])

    def announcements(self, symbol: str, start: dt.date, end: dt.date) -> list[dict]:
        from ..common.entity import get_entity
        from ..data.filings import announcements
        anns, _ = announcements(get_entity(symbol), start, end)
        return anns
