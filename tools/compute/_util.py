"""Shared helpers for the compute group: table <-> DataFrame, statistics, inputs.

Compute functions are pure: numbers in, provenance numbers out. CLI wrappers
read the cached parquet/JSON written by the data group.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ..common.cache import REPO_ROOT
from ..common.provenance import derived, missing

MANDATE_PATH = REPO_ROOT / "config" / "mandate.yaml"


def frame(t: dict | None) -> pd.DataFrame:
    """A provenance table as a DataFrame (empty if absent)."""
    if not t or not t.get("rows"):
        return pd.DataFrame(columns=(t or {}).get("columns", []))
    return pd.DataFrame(t["rows"], columns=t["columns"])


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def load_mandate(path: Path = MANDATE_PATH) -> dict:
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def fnum(x: Any) -> float | None:
    """float or None; NaN/None/non-numeric -> None (never 0)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def safe_div(a: Any, b: Any) -> float | None:
    a, b = fnum(a), fnum(b)
    if a is None or b is None or b == 0:
        return None
    return a / b


def cagr(start: float | None, end: float | None, years: float) -> tuple[float | None, str | None]:
    """Compound annual growth; undefined (None + reason) for non-positive endpoints."""
    start, end = fnum(start), fnum(end)
    if start is None or end is None:
        return None, "endpoint missing"
    if years <= 0:
        return None, "non-positive span"
    if start <= 0 or end <= 0:
        return None, "CAGR undefined when either endpoint is zero or negative"
    return (end / start) ** (1 / years) - 1, None


def pct_or_missing(value: float | None, why: str | None, *, formula: str, inputs: Any = None, period: str | None = None,
                   as_of: str | None = None, unit: str = "%", scale: float = 100.0, notes: str | None = None) -> dict:
    if value is None:
        return missing(why or "inputs unavailable", unit, source="computed", formula=formula, period=period)
    return derived(value * scale, unit, formula=formula, inputs=inputs, period=period, as_of=as_of, notes=notes)


def percentile_rank(value: float, sample: list[float] | np.ndarray) -> float | None:
    """Share of sample values <= value, in % (ties count half)."""
    s = np.asarray([x for x in sample if fnum(x) is not None], dtype=float)
    if len(s) == 0 or fnum(value) is None:
        return None
    below = np.sum(s < value)
    equal = np.sum(s == value)
    return float((below + 0.5 * equal) / len(s) * 100)


def t_quantile(p: float, dof: float) -> float:
    """Student-t quantile via the Cornish-Fisher expansion of the normal (error < 0.01 for dof >= 3)."""
    z = normal_quantile(p)
    if dof <= 0:
        return float("nan")
    g1 = (z ** 3 + z) / 4
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96
    g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384
    return z + g1 / dof + g2 / dof ** 2 + g3 / dof ** 3


def normal_quantile(p: float) -> float:
    """Acklam's rational approximation (abs error < 1.2e-9)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    lo, hi = 0.02425, 1 - 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > hi:
        return -normal_quantile(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def mean_ci(values: np.ndarray, n_eff: float, level: float = 0.95) -> tuple[float, float]:
    """CI for the mean using an effective sample size (overlap-corrected)."""
    m = float(np.mean(values))
    if n_eff < 2 or len(values) < 2:
        return float("nan"), float("nan")
    sd = float(np.std(values, ddof=1))
    t = t_quantile(0.5 + level / 2, n_eff - 1)
    half = t * sd / math.sqrt(n_eff)
    return m - half, m + half


def wilson_ci(p_hat: float, n: float, level: float = 0.95) -> tuple[float, float]:
    if n <= 0:
        return float("nan"), float("nan")
    z = normal_quantile(0.5 + level / 2)
    denom = 1 + z * z / n
    centre = (p_hat + z * z / (2 * n)) / denom
    half = z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


def records_table(records: list[dict], columns: list[str], units: dict[str, str], *, source: str, notes: str | None = None,
                  as_of: str | None = None) -> dict:
    from ..common.provenance import table
    rows = [[None if (isinstance(r.get(c), float) and (math.isnan(r[c]) or math.isinf(r[c]))) else r.get(c) for c in columns] for r in records]
    return table(columns, rows, units=units, source=source, notes=notes, as_of=as_of)
