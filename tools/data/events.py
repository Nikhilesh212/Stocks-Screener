"""Upcoming board meetings / results dates, upcoming corporate actions, and NSE surveillance status."""
from __future__ import annotations

import datetime as dt

from ..common.entity import get_entity
from ..common.periods import parse_date
from ..common.provenance import today_ist
from ..common.sources import TTL_LIST, TTL_LIVE, nse_api
from .corpactions import corporate_actions
from .prices import actions_output


def surveillance(isin: str, symbol: str) -> dict:
    asm, fa = nse_api("reportASM", {}, key="_market/surveillance/asm.json", ttl_hours=TTL_LIVE)
    gsm, fg = nse_api("reportGSM", {}, key="_market/surveillance/gsm.json", ttl_hours=TTL_LIVE)
    hits = []
    for term in ("longterm", "shortterm"):
        for r in (asm or {}).get(term, {}).get("data", []):
            if r.get("isin") == isin or r.get("symbol") == symbol:
                hits.append({"list": f"ASM {term}", "stage": r.get("asmSurvIndicator"), "description": r.get("survDesc"), "as_of": r.get("asmTime")})
    for r in gsm or []:
        if r.get("isin") == isin or r.get("symbol") == symbol:
            hits.append({"list": "GSM", "stage": r.get("gsmStage"), "description": r.get("survDesc"), "as_of": r.get("gsmTime")})
    return {"on_surveillance": bool(hits), "entries": hits, "sources": [fa.url, fg.url], "retrieved_at": fa.retrieved_at}


def cmd_events(args) -> dict:
    e = get_entity(args.query)
    today = today_ist()
    cal, fc = nse_api("event-calendar", {"index": "equities", "symbol": e.nse_symbol}, key=f"{e.isin}/nse_events/calendar.json", ttl_hours=TTL_LIST)
    upcoming, recent = [], []
    for r in cal or []:
        d = parse_date(r.get("date"))
        item = {"date": d.isoformat() if d else None, "purpose": r.get("purpose"), "detail": (r.get("bm_desc") or "")[:300]}
        if d and d >= today:
            upcoming.append(item)
        elif d and d >= today - dt.timedelta(days=120):
            recent.append(item)
    acts, ca_url, _ = corporate_actions(e, today - dt.timedelta(days=30), today + dt.timedelta(days=365))
    return {
        "identity": e.identity(), "today": today.isoformat(),
        "upcoming_board_meetings": sorted(upcoming, key=lambda x: x["date"]), "recent_board_meetings": sorted(recent, key=lambda x: x["date"], reverse=True),
        "calendar_source": fc.url,
        "corporate_actions_next_12m": actions_output([a.to_dict() for a in acts if a.ex_date >= today], ca_url),
        "corporate_actions_source": ca_url,
        "surveillance": surveillance(e.isin, e.nse_symbol),
        "notes": "NSE event calendar lists meetings once companies intimate them (usually 2-7 days ahead), so far-dated results dates are often absent.",
    }


def register(sub, leaf) -> None:
    p = leaf(sub, "events", "Upcoming results/board meetings, corporate actions, ASM/GSM surveillance status")
    p.add_argument("query")
    p.set_defaults(func=cmd_events)
