"""Indian fiscal periods (April–March). FY27 = 1 Apr 2026 – 31 Mar 2027; Q1 = Apr–Jun."""
from __future__ import annotations

import datetime as dt
import re

_FORMATS = (
    "%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d/%m/%Y",
    "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%d%m%Y", "%Y%m%d",
)


def parse_date(s: str | dt.date | None) -> dt.date | None:
    if s is None:
        return None
    if isinstance(s, dt.datetime):
        return s.date()
    if isinstance(s, dt.date):
        return s
    t = str(s).strip()
    if not t or t in {"-", "--"}:
        return None
    if "T" in t and re.match(r"\d{4}-\d{2}-\d{2}T", t):
        return dt.date.fromisoformat(t[:10])
    for fmt in _FORMATS:
        try:
            return dt.datetime.strptime(t.title() if "%b" in fmt or "%B" in fmt else t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {s!r}")


def fy_end_year(d: dt.date) -> int:
    return d.year + 1 if d.month >= 4 else d.year


def fy_label(d: dt.date) -> str:
    return f"FY{fy_end_year(d) % 100:02d}"


def fy_bounds(fy: int) -> tuple[dt.date, dt.date]:
    """fy is the ending calendar year, e.g. 2027 for FY27."""
    return dt.date(fy - 1, 4, 1), dt.date(fy, 3, 31)


def quarter_of(d: dt.date) -> int:
    return {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[d.month]


def quarter_label(end: dt.date) -> str:
    return f"Q{quarter_of(end)}{fy_label(end)}"


def months_between(start: dt.date, end: dt.date) -> int:
    return round(((end - start).days + 1) / 30.44)


def period_label(start: dt.date | None, end: dt.date) -> str:
    """Q2FY27 for a quarter, H1FY27 for a half, 9MFY27, FY27 for a full year, else 'as of <date>'."""
    if start is None:
        return f"as of {end.isoformat()}"
    m = months_between(start, end)
    fy = fy_label(end)
    if m == 3:
        return quarter_label(end)
    if m == 6 and start.month == 4:
        return f"H1{fy}"
    if m == 9 and start.month == 4:
        return f"9M{fy}"
    if m == 12 and start.month == 4:
        return fy
    return f"{start.isoformat()}..{end.isoformat()}"


def quarter_end_dates(last: dt.date, n: int) -> list[dt.date]:
    """The n most recent quarter-end dates on or before `last`, newest first."""
    out = []
    y, m = last.year, last.month
    # move to the quarter end on/before `last`
    qm = ((m - 1) // 3) * 3 + 3
    d = _month_end(y, qm)
    if d > last:
        qm -= 3
        if qm <= 0:
            qm += 12
            y -= 1
        d = _month_end(y, qm)
    while len(out) < n:
        out.append(d)
        qm -= 3
        if qm <= 0:
            qm += 12
            y -= 1
        d = _month_end(y, qm)
    return out


def _month_end(y: int, m: int) -> dt.date:
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def nse_date(d: dt.date) -> str:
    """dd-mm-yyyy as NSE APIs expect."""
    return d.strftime("%d-%m-%Y")
