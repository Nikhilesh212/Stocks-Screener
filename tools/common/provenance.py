"""Provenance-carrying values.

Every number a tool emits is wrapped so a reader can always answer: what is it,
in what unit, for which period, as of when, and where did it come from.

Two shapes are allowed in tool output:

* a *provenance number* built by ``num()`` / ``missing()`` / ``derived()``;
* a *provenance table* built by ``table()`` for time series, where one block of
  provenance covers every row.

``find_bare_numbers()`` walks any output and reports numbers that are in
neither shape; tests run it over every command's output.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Iterable

IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")

PROVENANCE_KEYS = (
    "value", "unit", "period", "as_of", "source", "source_url",
    "source_doc", "page", "retrieved_at", "notes",
)


def now_iso() -> str:
    return dt.datetime.now(IST).isoformat(timespec="seconds")


def today_ist() -> dt.date:
    return dt.datetime.now(IST).date()


def _clean(value: Any) -> tuple[Any, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        raise TypeError("booleans are not numbers; emit them as plain fields")
    if not isinstance(value, (int, float)):
        raise TypeError(f"num() needs int/float/None, got {type(value).__name__}")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None, "value was NaN/inf in source or computation"
    return value, None


def num(
    value: int | float | None,
    unit: str | None,
    *,
    source: str,
    period: str | None = None,
    as_of: str | None = None,
    source_url: str | None = None,
    source_doc: str | None = None,
    page: int | None = None,
    notes: str | None = None,
    retrieved_at: str | None = None,
    **extra: Any,
) -> dict:
    value, why = _clean(value)
    if why:
        notes = f"{notes}; {why}" if notes else why
    out = {
        "value": value,
        "unit": unit,
        "period": period,
        "as_of": as_of,
        "source": source,
        "source_url": source_url,
        "source_doc": source_doc,
        "page": page,
        "retrieved_at": retrieved_at or now_iso(),
        "notes": notes,
    }
    out.update(extra)
    return out


def missing(reason: str, unit: str | None = None, *, source: str = "none", **kw: Any) -> dict:
    """A value we could not obtain. Never substitute zero for this."""
    return num(None, unit, source=source, notes=reason, **kw)


def derived(
    value: int | float | None,
    unit: str | None,
    *,
    formula: str,
    inputs: Iterable[dict] | dict | None = None,
    period: str | None = None,
    as_of: str | None = None,
    notes: str | None = None,
) -> dict:
    """A number computed in code from other provenance numbers."""
    if isinstance(inputs, dict):
        refs = {k: _ref(v) for k, v in inputs.items()}
    else:
        refs = [_ref(v) for v in (inputs or [])]
    return num(
        value, unit, source="computed", period=period, as_of=as_of,
        notes=notes, formula=formula, inputs=refs,
    )


def _ref(p: Any) -> Any:
    """Compact reference to an input so derived values stay traceable without bloat."""
    if isinstance(p, dict) and "value" in p:
        return {k: p.get(k) for k in ("value", "unit", "period", "as_of", "source", "source_url", "page") if p.get(k) is not None}
    return p


def table(
    columns: list[str],
    rows: list[list[Any]],
    *,
    units: dict[str, str],
    source: str,
    source_url: str | None = None,
    period: str | None = None,
    as_of: str | None = None,
    retrieved_at: str | None = None,
    notes: str | None = None,
) -> dict:
    """A time series or cross-section sharing one provenance block."""
    for r in rows:
        if len(r) != len(columns):
            raise ValueError("row length does not match columns")
    clean_rows = []
    for r in rows:
        clean_rows.append([
            None if isinstance(x, float) and (math.isnan(x) or math.isinf(x)) else x for x in r
        ])
    return {
        "kind": "table",
        "columns": columns,
        "units": units,
        "rows": clean_rows,
        "source": source,
        "source_url": source_url,
        "period": period,
        "as_of": as_of,
        "retrieved_at": retrieved_at or now_iso(),
        "notes": notes,
    }


def is_provenance_number(obj: Any) -> bool:
    return isinstance(obj, dict) and "value" in obj and "unit" in obj and "source" in obj and "retrieved_at" in obj


# Integer bookkeeping fields (page numbers, counts of rows/pages) are metadata,
# not financial figures, and may appear bare.
META_INT_KEYS = {"page", "pages_hit", "n_pages", "n_chars", "near_empty_pages", "n_rows", "n_items", "total_count",
                 "requested_quarters", "returned_quarters", "n_picks", "n_records"}


def find_bare_numbers(obj: Any, path: str = "$") -> list[str]:
    """Paths of numbers that are not inside a provenance number or table."""
    bad: list[str] = []
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return bad
    if isinstance(obj, (int, float)):
        return [path]
    if isinstance(obj, dict):
        if is_provenance_number(obj):
            # inputs/derived refs inside are provenance by construction
            return bad
        if obj.get("kind") == "table" and "rows" in obj and "units" in obj:
            return bad
        for k, v in obj.items():
            if k in META_INT_KEYS and (isinstance(v, int) and not isinstance(v, bool) or isinstance(v, list) and all(isinstance(x, int) for x in v)):
                continue
            bad.extend(find_bare_numbers(v, f"{path}.{k}"))
        return bad
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            bad.extend(find_bare_numbers(v, f"{path}[{i}]"))
    return bad
