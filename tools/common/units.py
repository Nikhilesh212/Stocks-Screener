"""Unit handling. Money is stored in ₹ crore unless a field says otherwise.

1 crore = 100 lakh = 10 million = 1e7 rupees.
"""
from __future__ import annotations

import re

RUPEE = 1.0
LAKH = 1e5
MILLION = 1e6
CRORE = 1e7
BILLION = 1e9

INR_CR = "INR crore"
INR = "INR"
INR_PER_SHARE = "INR/share"
PCT = "%"
RATIO = "x"
COUNT = "count"
DAYS = "days"

_DIVISORS = {
    "rupees": RUPEE, "rupee": RUPEE, "inr": RUPEE, "actuals": RUPEE,
    "thousands": 1e3, "thousand": 1e3,
    "lakhs": LAKH, "lakh": LAKH, "lacs": LAKH, "lac": LAKH,
    "millions": MILLION, "million": MILLION, "mn": MILLION,
    "crores": CRORE, "crore": CRORE, "cr": CRORE,
    "billions": BILLION, "billion": BILLION, "bn": BILLION,
}


def divisor_for(label: str) -> float:
    key = label.strip().lower().replace("rs.", "").replace("₹", "").strip()
    if key not in _DIVISORS:
        raise ValueError(f"unknown money unit {label!r}")
    return _DIVISORS[key]


def to_crore(value: float | None, from_unit: str) -> float | None:
    if value is None:
        return None
    return value * divisor_for(from_unit) / CRORE


def inr_to_crore(value: float | None) -> float | None:
    return None if value is None else value / CRORE


def lakh_to_crore(value: float | None) -> float | None:
    return None if value is None else value * LAKH / CRORE


_NULLS = {"", "-", "--", "na", "n.a.", "nil", "null", "none", "nan"}


def parse_number(s: object) -> float | None:
    """Parse '1,23,456.78', '(12.5)', '-', '12.3%' etc. Returns None for blanks, never 0."""
    if s is None:
        return None
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return float(s)
    t = str(s).strip()
    if t.lower() in _NULLS:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "").replace("%", "").replace("₹", "").strip()
    t = re.sub(r"^(rs\.?|inr)\s*", "", t, flags=re.I)
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v
