"""Quarterly shareholding pattern from exchange XBRL: promoter, FII/FPI, DII, MF, others, pledge.

Percentages are % of total shares (XBRL stores fractions; converted to %).
Pledge: if the filing's own "promoter shares pledged/encumbered" flags are all
false, pledged % is reported as 0 with that flag as evidence; if any flag is
true we look for the encumbered-share counts and report null if not found.
"""
from __future__ import annotations

from ..common.cache import fetch
from ..common.entity import get_entity
from ..common.http import SourceError
from ..common.periods import parse_date
from ..common.provenance import table
from ..common.sources import TTL_LIST, nse_api
from ..common.units import PCT
from . import xbrl

CATEGORIES = {
    "promoter": "ShareholdingOfPromoterAndPromoterGroup_ContextI",
    "public": "PublicShareholding_ContextI",
    "fii_fpi": "InstitutionsForeign_ContextI",
    "dii": "InstitutionsDomestic_ContextI",
    "mutual_funds": "MutualFundsOrUTI_ContextI",
    "insurance": "InsuranceCompanies_ContextI",
    "non_institutions": "NonInstitutions_ContextI",
    "government": "Governments_ContextI",
}
PLEDGE_FLAGS = ("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged",
                "WhetherAnySharesHeldByPromotersAreEncumberedUnderNonDisposalUndertaking",
                "WhetherAnySharesHeldByPromotersAreEncumberedOtherThanByWayOfPledgeOrNDU")


def parse_shp(content: bytes) -> dict:
    inst = xbrl.parse(content)
    out: dict = {}
    for cat, ctx in CATEGORIES.items():
        v = inst.value("ShareholdingAsAPercentageOfTotalNumberOfShares", ctx)
        out[cat] = None if v is None else round(float(v) * 100, 4)
    promoter_shares = inst.value("NumberOfShares", CATEGORIES["promoter"])
    flags = [inst.text.get(f) for f in PLEDGE_FLAGS]
    if flags and all(f == "false" for f in flags if f is not None) and any(f is not None for f in flags):
        out["pledged_pct_of_promoter"] = 0.0
        out["pledge_evidence"] = "filing flags: no promoter shares pledged/encumbered"
    else:
        enc = None
        for f in inst.facts:
            if f.context == CATEGORIES["promoter"] and ("Pledged" in f.name or "Encumbered" in f.name) and f.name.startswith("NumberOf"):
                enc = (enc or 0) + float(f.raw)
        if enc is not None and promoter_shares:
            out["pledged_pct_of_promoter"] = round(enc / float(promoter_shares) * 100, 4)
            out["pledge_evidence"] = "encumbered share counts in promoter context"
        else:
            out["pledged_pct_of_promoter"] = None
            out["pledge_evidence"] = "pledge flag true or absent but counts not found in XBRL; read the PDF filing"
    return out


def cmd_shareholding(args) -> dict:
    e = get_entity(args.query)
    data, f = nse_api("corporate-share-holdings-master", {"index": "equities", "symbol": e.nse_symbol},
                      key=f"{e.isin}/nse_shp/list.json", ttl_hours=TTL_LIST)
    recs = sorted([r for r in data or [] if r.get("xbrl")], key=lambda r: parse_date(r["date"]), reverse=True)[: args.quarters]
    rows, warns = [], []
    cols = ["quarter_end", *CATEGORIES.keys(), "pledged_pct_of_promoter", "pledge_evidence", "source_xbrl"]
    for r in recs:
        try:
            doc = fetch(r["xbrl"], key=f"{e.isin}/shp/{r['xbrl'].rsplit('/', 1)[-1]}", ttl_hours=None)
            p = parse_shp(doc.content)
        except (SourceError, Exception) as ex:
            warns.append(f"{r['date']}: XBRL unreadable ({ex}); master-list promoter {r.get('pr_and_prgrp')}% only")
            p = {k: None for k in cols}
            p["promoter"] = float(r["pr_and_prgrp"]) if r.get("pr_and_prgrp") else None
        rows.append([parse_date(r["date"]).isoformat(), *[p.get(k) for k in CATEGORIES], p.get("pledged_pct_of_promoter"), p.get("pledge_evidence"), r["xbrl"]])
        mp = r.get("pr_and_prgrp")
        if mp and p.get("promoter") is not None and abs(float(mp) - p["promoter"]) > 0.05:
            warns.append(f"{r['date']}: promoter % master list {mp} vs XBRL {p['promoter']}")
    units = {k: PCT for k in [*CATEGORIES, "pledged_pct_of_promoter"]}
    return {"identity": e.identity(), "list_source": f.url, "warnings": warns,
            "shareholding": table(cols, rows, units=units, source="NSE shareholding pattern XBRL filings", as_of=rows[0][0] if rows else None,
                                  notes="% of total shares; fii_fpi and dii are institution totals; mutual_funds and insurance are subsets of dii")}


def register(sub, leaf) -> None:
    p = leaf(sub, "shareholding", "Promoter / FII / DII / MF / public holdings and promoter pledge over N quarters")
    p.add_argument("query")
    p.add_argument("--quarters", type=int, default=12)
    p.set_defaults(func=cmd_shareholding)
