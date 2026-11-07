"""Corporate actions from NSE, parsed into price-adjustment factors.

factor = how many shares one pre-event share becomes. Prices before the ex-date
are divided by the cumulative factor; volumes are multiplied by it.

  Bonus a:b    -> a new shares for every b held -> factor (a+b)/b
  Split X -> Y -> face value X becomes Y        -> factor X/Y
  Consolidation (Y -> X, X > Y)                  -> factor Y/X  (< 1)
  Rights, demerger, capital reduction           -> factor not parseable from text;
                                                   use NSE's adjusted previous close
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass

from ..common.entity import Entity, same_issuer_equity
from ..common.periods import nse_date, parse_date
from ..common.sources import TTL_LIST, nse_api


@dataclass
class CorpAction:
    ex_date: dt.date
    kind: str
    subject: str
    factor: float | None  # share multiplier for price adjustment
    cash_per_share: float | None  # dividends, INR per share on the pre-event share count
    record_date: dt.date | None = None
    series: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ex_date"] = self.ex_date.isoformat()
        d["record_date"] = self.record_date.isoformat() if self.record_date else None
        return d


_BONUS = re.compile(r"bonus\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", re.I)
_FV = re.compile(r"from\s*(?:rs|re|inr)?\.?\s*/?\s*([\d.]+)\s*/?-?.*?to\s*(?:rs|re|inr)?\.?\s*/?\s*([\d.]+)", re.I)
_DIV = re.compile(r"(?:dividend|div)[^0-9]*?(?:rs|re|inr)\.?\s*([\d.]+)", re.I)


def parse_subject(subject: str) -> tuple[str, float | None, float | None]:
    s = " ".join(subject.split())
    low = s.lower()
    if "bonus" in low:
        m = _BONUS.search(s)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            return "bonus", (a + b) / b, None
        return "bonus", None, None
    if "split" in low or "sub-division" in low or "subdivision" in low:
        m = _FV.search(s)
        if m:
            old, new = float(m.group(1)), float(m.group(2))
            if new > 0:
                return "split", old / new, None
        return "split", None, None
    if "consolidation" in low:
        m = _FV.search(s)
        if m:
            old, new = float(m.group(1)), float(m.group(2))
            if new > 0:
                return "consolidation", old / new, None
        return "consolidation", None, None
    if "rights" in low:
        return "rights", None, None
    if "demerger" in low or "scheme of arrangement" in low:
        return "demerger", None, None
    if "capital reduction" in low or "reduction of capital" in low:
        return "capital_reduction", None, None
    if "buy back" in low or "buyback" in low:
        return "buyback", None, None
    if "dividend" in low or re.search(r"\bdiv\b", low):
        amounts = [float(x) for x in _DIV.findall(s)]
        # "Interim Dividend - Rs 5 / Special Dividend - Rs 10" -> 15
        return "dividend", None, (sum(amounts) if amounts else None)
    if "distribution" in low:
        return "distribution", None, None
    return "other", None, None


def corporate_actions(entity: Entity, start: dt.date, end: dt.date) -> tuple[list[CorpAction], str, str]:
    params = {"index": "equities", "symbol": entity.nse_symbol, "from_date": nse_date(start), "to_date": nse_date(end)}
    data, f = nse_api("corporates-corporateActions", params,
                      key=f"{entity.isin}/nse_ca/{start.isoformat()}_{end.isoformat()}.json", ttl_hours=TTL_LIST)
    out: list[CorpAction] = []
    for rec in data or []:
        if rec.get("isin") and not same_issuer_equity(rec["isin"], entity.isin):
            continue  # NSE echoes ISIN; refuse records for a different instrument
        ex = parse_date(rec.get("exDate"))
        if ex is None:
            continue
        kind, factor, cash = parse_subject(rec.get("subject", ""))
        try:
            rd = parse_date(rec.get("recDate"))
        except ValueError:
            rd = None
        out.append(CorpAction(ex, kind, rec.get("subject", "").strip(), factor, cash, rd, rec.get("series")))
    out.sort(key=lambda a: a.ex_date)
    return out, f.url, f.retrieved_at
