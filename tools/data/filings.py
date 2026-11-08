"""Exchange filings: announcements, annual reports, concall transcripts, presentations,
results, credit ratings; plus download + page-numbered text, search and page reads.

Classification of announcements into transcripts/presentations is by keywords in
the exchange's own subject text; it can miss oddly titled filings, so the full
announcement list is always available with --kind announcements.
"""
from __future__ import annotations

import datetime as dt
import re

from ..common import pdftext
from ..common.entity import get_entity, same_issuer_equity
from ..common.periods import nse_date, parse_date
from ..common.provenance import today_ist
from ..common.sources import TTL_LIST, nse_api

KINDS = ("announcements", "annual_reports", "transcripts", "presentations", "results", "ratings", "all")
_TRANSCRIPT = re.compile(r"transcript", re.I)
_PRESENTATION = re.compile(r"presentation|investor deck|earnings deck", re.I)
_RESULTS = re.compile(r"financial result", re.I)
_RATING = re.compile(r"credit rating", re.I)


def announcements(e, start: dt.date, end: dt.date) -> tuple[list[dict], list[str]]:
    out, urls = [], []
    s = start
    while s <= end:
        t = min(end, s + dt.timedelta(days=89))
        data, f = nse_api("corporate-announcements", {"index": "equities", "symbol": e.nse_symbol, "from_date": nse_date(s), "to_date": nse_date(t)},
                          key=f"{e.isin}/nse_ann/{s}_{t}.json", ttl_hours=None if t < today_ist() - dt.timedelta(days=3) else TTL_LIST)
        urls.append(f.url)
        for a in data or []:
            if a.get("sm_isin") and not same_issuer_equity(a["sm_isin"], e.isin):
                continue
            out.append({
                "date": a.get("an_dt"), "category": a.get("desc"), "text": (a.get("attchmntText") or "")[:400],
                "url": a.get("attchmntFile"), "size": a.get("attFileSize") or a.get("fileSize"), "industry": a.get("smIndustry"),
            })
        s = t + dt.timedelta(days=1)
    out.sort(key=lambda x: parse_date(x["date"]) or dt.date.min, reverse=True)
    return out, urls


def classify(a: dict) -> str | None:
    blob = f"{a['category']} {a['text']}"
    if _TRANSCRIPT.search(blob):
        return "transcripts"
    if _PRESENTATION.search(blob):
        return "presentations"
    if _RATING.search(blob):
        return "ratings"
    if _RESULTS.search(a["category"] or ""):
        return "results"
    return None


def annual_reports(e) -> tuple[list[dict], str]:
    data, f = nse_api("annual-reports", {"index": "equities", "symbol": e.nse_symbol}, key=f"{e.isin}/nse_ar/list.json", ttl_hours=TTL_LIST)
    rows = [{"date": r.get("disseminationDateTime") or r.get("broadcast_dttm"), "fiscal_year": f"FY{str(r.get('toYr'))[-2:]}",
             "from_year": r.get("fromYr"), "to_year": r.get("toYr"), "url": r.get("fileName"), "size": r.get("attFileSize")}
            for r in (data or {}).get("data", [])]
    return rows, f.url


def credit_ratings(e) -> tuple[list[dict], str]:
    data, f = nse_api("corporate-credit-rating", {"index": "equities", "symbol": e.nse_symbol}, key=f"{e.isin}/nse_ratings/list.json", ttl_hours=TTL_LIST)
    rows = []
    for r in data or []:
        if r.get("Symbol") != e.nse_symbol:
            continue  # endpoint returns market-wide recent ratings; keep only this issuer
        rows.append({"date": r.get("DateofCR"), "agency": r.get("NameOfCRAgency"), "rating": r.get("CreditRating"), "outlook": r.get("Outlook"),
                     "action": r.get("RatingAction"), "instrument_isin": r.get("ISIN"), "earlier_rating": r.get("CreditRatingEarlier"),
                     "earlier_date": r.get("DateOfCREarlier")})
    return rows, f.url


def cmd_list(args) -> dict:
    e = get_entity(args.query)
    end = parse_date(args.to) if args.to else today_ist()
    start = parse_date(args.start) if args.start else end - dt.timedelta(days=int(30.44 * args.months))
    out: dict = {"identity": e.identity(), "window": {"from": start.isoformat(), "to": end.isoformat()}, "warnings": []}
    kind = args.kind
    if kind in ("announcements", "transcripts", "presentations", "results", "ratings", "all"):
        anns, urls = announcements(e, start, end)
        out["announcements_source"] = urls[-1] if urls else None
        if kind in ("announcements", "all"):
            out["announcements"] = anns[: args.limit]
            out["n_items"] = len(anns)
            if len(anns) > args.limit:
                out["warnings"].append(f"showing the latest {args.limit} of {len(anns)} announcements in the window; "
                                       f"rerun with --limit {len(anns)} or a narrower --from/--to window to see the rest")
        for k in ("transcripts", "presentations", "results", "ratings"):
            if kind in (k, "all"):
                out[k] = [a for a in anns if classify(a) == k][: args.limit]
        if anns:
            out["basic_industry"] = anns[0].get("industry")
    if kind in ("annual_reports", "all"):
        out["annual_reports"], out["annual_reports_source"] = annual_reports(e)
    if kind in ("ratings", "all"):
        out["rating_actions"], out["rating_actions_source"] = credit_ratings(e)
        if not out["rating_actions"]:
            out["warnings"].append("NSE rating feed returned no rows for this symbol (feed is market-wide and recent); check 'ratings' announcements and agency sites")
    if kind in ("transcripts", "all") and not out.get("transcripts"):
        out["warnings"].append("no transcript found by keyword in this window; check company IR site via WebFetch and say so in the dossier")
    return out


def cmd_get(args) -> dict:
    e = get_entity(args.query)
    info = pdftext.download_and_extract(args.url, e.isin)
    return {"identity": e.identity(), **info}


def cmd_search(args) -> dict:
    e = get_entity(args.query)
    return {"identity": e.identity(), **pdftext.search(e.isin, args.doc_id, args.pattern, context=args.context, max_hits=args.max_hits)}


def cmd_pages(args) -> dict:
    e = get_entity(args.query)
    a, _, b = args.range.partition("-")
    return {"identity": e.identity(), **pdftext.pages(e.isin, args.doc_id, int(a), int(b or a), max_chars=args.max_chars)}


def register(sub, leaf) -> None:
    p = leaf(sub, "filings", "List exchange filings; download a document to page-numbered text; search or read pages")
    s = p.add_subparsers(dest="filings_cmd", required=True)
    ls = leaf(s, "list", "List filings for a company")
    ls.add_argument("query", help="NSE symbol or ISIN")
    ls.add_argument("--kind", choices=KINDS, default="all")
    ls.add_argument("--from", dest="start")
    ls.add_argument("--to")
    ls.add_argument("--months", type=float, default=12)
    ls.add_argument("--limit", type=int, default=60)
    ls.set_defaults(func=cmd_list)
    g = leaf(s, "get", "Download a filing (PDF/HTML) and extract page-numbered text; returns doc_id")
    g.add_argument("query")
    g.add_argument("url")
    g.set_defaults(func=cmd_get)
    se = leaf(s, "search", "Regex search a downloaded document; returns page numbers and snippets")
    se.add_argument("query")
    se.add_argument("doc_id")
    se.add_argument("pattern")
    se.add_argument("--context", type=int, default=250)
    se.add_argument("--max-hits", type=int, default=40)
    se.set_defaults(func=cmd_search)
    pg = leaf(s, "pages", "Read page text from a downloaded document, e.g. 45-52")
    pg.add_argument("query")
    pg.add_argument("doc_id")
    pg.add_argument("range")
    pg.add_argument("--max-chars", type=int, default=60000)
    pg.set_defaults(func=cmd_pages)
