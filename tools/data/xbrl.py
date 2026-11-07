"""Minimal XBRL instance parser for SEBI/NSE results and shareholding filings.

Handles two traps found in real filings:
* old-format (pre-2025) results label the year-to-date context "FourD" with the
  *quarter's* dates; the true period is in DateOfStart/EndOfReportingPeriod facts
  inside that context, so those facts override context dates;
* monetary facts are in absolute rupees regardless of the "LevelOfRounding" shown
  in the PDF; we convert to INR crore here and nowhere else.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from lxml import etree

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"


@dataclass
class Context:
    id: str
    start: dt.date | None
    end: dt.date | None  # for instants, end = instant
    instant: bool
    dims: tuple = ()


@dataclass
class Fact:
    name: str
    context: str
    unit: str | None
    decimals: str | None
    raw: str


@dataclass
class Instance:
    contexts: dict[str, Context]
    facts: list[Fact]
    text: dict[str, str] = field(default_factory=dict)  # first non-dimensional text value per name
    synthesized: list[str] = field(default_factory=list)  # context ids referenced but not defined by the filer

    def value(self, name: str, ctx: str) -> str | None:
        for f in self.facts:
            if f.name == name and f.context == ctx:
                return f.raw
        return None


def _d(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s.strip()[:10])
    except ValueError:
        return None


def parse(content: bytes) -> Instance:
    root = etree.fromstring(content)
    contexts: dict[str, Context] = {}
    for c in root.iter(f"{{{XBRLI}}}context"):
        p = c.find(f"{{{XBRLI}}}period")
        inst = p.find(f"{{{XBRLI}}}instant")
        dims = tuple(sorted((m.get("dimension"), (m.text or "").strip()) for m in c.iter(f"{{{XBRLDI}}}explicitMember")))
        dims += tuple(sorted((m.get("dimension"), (m[0].text if len(m) else "")) for m in c.iter(f"{{{XBRLDI}}}typedMember")))
        if inst is not None:
            d = _d(inst.text)
            contexts[c.get("id")] = Context(c.get("id"), None, d, True, dims)
        else:
            contexts[c.get("id")] = Context(c.get("id"), _d(p.findtext(f"{{{XBRLI}}}startDate")), _d(p.findtext(f"{{{XBRLI}}}endDate")), False, dims)
    facts: list[Fact] = []
    text: dict[str, str] = {}
    for el in root:
        if not isinstance(el.tag, str):
            continue
        ctx = el.get("contextRef")
        if ctx is None:
            continue
        name = etree.QName(el).localname
        raw = (el.text or "").strip()
        facts.append(Fact(name, ctx, el.get("unitRef"), el.get("decimals"), raw))
    # Some legacy filings (e.g. RELIANCE FY19-FY21) reference their main contexts (OneD, FourD, OneI) without
    # defining them. Recreate them as non-dimensional contexts; _fix_periods dates them from the filer's own
    # DateOfStart/EndOfReportingPeriod facts, and instants take the end date of the matching duration.
    synthesized = sorted({f.context for f in facts} - set(contexts))
    for cid in synthesized:
        contexts[cid] = Context(cid, None, None, cid.endswith("I"), ())
    for f in facts:
        if f.name not in text and f.context in contexts and not contexts[f.context].dims:
            text[f.name] = f.raw
    inst = Instance(contexts, facts, text, synthesized)
    _fix_periods(inst)
    for cid in synthesized:
        c = contexts[cid]
        if c.instant:
            dur = contexts.get(cid[:-1] + "D")
            c.end = dur.end if dur is not None and not dur.instant else None
        if c.end is None:
            del contexts[cid]  # cannot date it from the filing itself: drop rather than guess
    inst.synthesized = [cid for cid in synthesized if cid in contexts]
    return inst


def _fix_periods(inst: Instance) -> None:
    """Override duration-context dates with the filer's own reporting-period facts."""
    for cid, c in inst.contexts.items():
        if c.instant or c.dims:
            continue
        s = _d(inst.value("DateOfStartOfReportingPeriod", cid))
        e = _d(inst.value("DateOfEndOfReportingPeriod", cid))
        if s and e:
            c.start, c.end = s, e
        elif cid.startswith("Four") and c.end:
            fy_start = _d(inst.value("DateOfStartOfFinancialYear", cid)) or _d(inst.text.get("DateOfStartOfFinancialYear"))
            if fy_start and fy_start < (c.start or c.end):
                c.start = fy_start


def numeric(f: Fact) -> float | None:
    try:
        return float(f.raw.replace(",", ""))
    except ValueError:
        return None


def values_by_period(inst: Instance, name: str) -> list[tuple[Context, float, str | None]]:
    """All non-dimensional numeric values for a concept, with their (fixed) contexts."""
    out = []
    for f in inst.facts:
        if f.name != name:
            continue
        c = inst.contexts.get(f.context)
        if c is None or c.dims:
            continue
        v = numeric(f)
        if v is not None:
            out.append((c, v, f.unit))
    return out


def contexts_with_member(inst: Instance, member_substring: str) -> list[str]:
    return [cid for cid in inst.contexts if member_substring in cid]
