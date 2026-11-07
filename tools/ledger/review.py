"""`ledger review <run_id>`: announcements since the last review, listed next to each pick's kill criteria.

Code lists facts; Claude judges whether a criterion has fired. Each review
appends a `review` record so the next one starts where this one ended.
"""
from __future__ import annotations

import datetime as dt

from ..common.provenance import now_iso, today_ist
from . import store
from .market import LiveMarket


def review(run_id: str, *, ledger_dir: str | None, market: LiveMarket, as_of: dt.date | None = None, write: bool = True) -> dict:
    run, picks, other = store.run_records(run_id, ledger_dir)
    end = as_of or today_ist()
    reviews = sorted((r for r in other if r["record_type"] == "review"), key=lambda r: r["window_to"])
    start = (dt.date.fromisoformat(reviews[-1]["window_to"]) + dt.timedelta(days=1)) if reviews else dt.date.fromisoformat(run["frozen_at"][:10])
    items = []
    for p in picks:
        try:
            anns = market.announcements(p["symbol"], start, end)
            err = None
        except Exception as ex:  # one failing feed must not hide the other picks
            anns, err = [], f"{type(ex).__name__}: {ex}"
        due = [d for d in p.get("review_dates", []) if start.isoformat() <= d <= end.isoformat()]
        items.append({"symbol": p["symbol"], "isin": p["isin"], "thesis": p["thesis"], "kill_criteria": p["kill_criteria"],
                      "review_dates_in_window": due, "announcements": anns, "n_items": len(anns), "fetch_error": err})
    out = {"run_id": run_id, "window": {"from": start.isoformat(), "to": end.isoformat()}, "picks": items,
           "instructions": ("For each pick, read the announcements (and results, if any) against every kill criterion and state "
                            "whether it fired, with the document and page. Code does not judge this."),
           "previous_reviews": [r["window_to"] for r in reviews]}
    if write:
        rec = {"record_type": "review", "record_id": f"{run_id}:review:{end.isoformat()}", "run_id": run_id, "at": now_iso(),
               "window_from": start.isoformat(), "window_to": end.isoformat(),
               "n_items": sum(i["n_items"] for i in items), "errors": [f"{i['symbol']}: {i['fetch_error']}" for i in items if i["fetch_error"]]}
        if any(r["record_id"] == rec["record_id"] for r in other):
            out["note"] = f"already reviewed up to {end}; not recorded again"
        else:
            store.append([rec], ledger_dir)
    return out
