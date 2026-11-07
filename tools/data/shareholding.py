"""Quarterly shareholding pattern from exchange XBRL: promoter, FII/FPI, DII, MF, others, pledge.

Percentages are % of total shares. Filings store them as fractions or as
percent depending on the filing format; promoter + public = 100% decides which.
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

# Context ids per category: current taxonomy first, then the pre-2025 one
# (verified on RELIANCE/CAMS/HDFCBANK filings up to Mar-2025).
CATEGORIES = {
    "promoter": ["ShareholdingOfPromoterAndPromoterGroup_ContextI", "ShareholdingOfPromoterAndPromoterGroupI"],
    "public": ["PublicShareholding_ContextI", "PublicShareholdingI"],
    "fii_fpi": ["InstitutionsForeign_ContextI", "InstitutionsForeignI"],
    "dii": ["InstitutionsDomestic_ContextI", "InstitutionsDomesticI"],
    "mutual_funds": ["MutualFundsOrUTI_ContextI", "MutualFundsOrUtiI"],
    "insurance": ["InsuranceCompanies_ContextI", "InsuranceCompaniesI"],
    "non_institutions": ["NonInstitutions_ContextI", "NonInstitutionsI"],
    "government": ["Governments_ContextI", ("CentralGovernmentOrPresidentOfIndiaI", "StateGovernmentsOrGovernorsI")],
}
PLEDGE_FLAGS = ("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged",
                "WhetherAnySharesHeldByPromotersAreEncumberedUnderNonDisposalUndertaking",
                "WhetherAnySharesHeldByPromotersAreEncumberedOtherThanByWayOfPledgeOrNDU")
OLD_PLEDGE_FLAGS = ("WhetherAnySharesHeldByPromotersArePledgeOrOtherwiseEncumbered",)
PCT_FACT = "ShareholdingAsAPercentageOfTotalNumberOfShares"


def _raw_pct(inst: xbrl.Instance, ctxs: list) -> tuple[float | None, str | None]:
    for c in ctxs:
        if isinstance(c, tuple):  # sum of parts (old taxonomy has no parent context)
            parts = [inst.value(PCT_FACT, x) for x in c]
            if any(v is not None for v in parts):
                return sum(float(v) for v in parts if v is not None), c[0]
            continue
        v = inst.value(PCT_FACT, c)
        if v is not None:
            return float(v), c
    return None, None


def _scale(raw: dict) -> float | None:
    """Filings store holdings as fractions (0.5044) or as percent (50.44, both
    pre-2025 and Jun-2025 filings). Promoter + public must total 100%, which tells us which."""
    ref = (raw.get("promoter") or 0) + (raw.get("public") or 0)
    if 0.9 <= ref <= 1.1:
        return 100.0
    if 90 <= ref <= 110:
        return 1.0
    return None


def parse_shp(content: bytes) -> dict:
    inst = xbrl.parse(content)
    raw, ctx_used = {}, {}
    for cat, ctxs in CATEGORIES.items():
        raw[cat], ctx_used[cat] = _raw_pct(inst, ctxs)
    scale = _scale(raw)
    out: dict = {}
    for cat in CATEGORIES:
        out[cat] = None if raw[cat] is None or scale is None else round(raw[cat] * scale, 4)
    out["scale_evidence"] = ("promoter + public do not total 100% under either scale; values withheld" if scale is None else
                             f"stored as {'fractions' if scale == 100 else 'percent'} (promoter + public = {'1' if scale == 100 else '100'})")
    promoter_ctx = ctx_used["promoter"] or CATEGORIES["promoter"][0]
    promoter_shares = inst.value("NumberOfShares", promoter_ctx)
    flags = [inst.text.get(f) for f in PLEDGE_FLAGS + OLD_PLEDGE_FLAGS]
    if not raw["promoter"] and scale is not None:  # absent, or a filed 0 (old taxonomy files a zero row)
        out["pledged_pct_of_promoter"] = None
        out["pledge_evidence"] = "no promoter group in this filing"
    elif flags and all(f == "false" for f in flags if f is not None) and any(f is not None for f in flags):
        out["pledged_pct_of_promoter"] = 0.0
        out["pledge_evidence"] = "filing flags: no promoter shares pledged/encumbered"
    else:
        enc = None
        for f in inst.facts:
            if f.context == promoter_ctx and ("Pledged" in f.name or "Encumbered" in f.name) and f.name.startswith(("NumberOf", "PledgedOrEncumberedNumberOf")):
                enc = (enc or 0) + float(f.raw)
        if enc is not None and promoter_shares and float(promoter_shares) > 0:
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
    cols = ["quarter_end", *CATEGORIES.keys(), "pledged_pct_of_promoter", "pledge_evidence", "scale_evidence", "source_xbrl"]
    for r in recs:
        try:
            doc = fetch(r["xbrl"], key=f"{e.isin}/shp/{r['xbrl'].rsplit('/', 1)[-1]}", ttl_hours=None)
            p = parse_shp(doc.content)
        except (SourceError, Exception) as ex:
            warns.append(f"{r['date']}: XBRL unreadable ({ex}); master-list promoter {r.get('pr_and_prgrp')}% only")
            p = {k: None for k in cols}
            p["promoter"] = float(r["pr_and_prgrp"]) if r.get("pr_and_prgrp") else None
        rows.append([parse_date(r["date"]).isoformat(), *[p.get(k) for k in CATEGORIES], p.get("pledged_pct_of_promoter"), p.get("pledge_evidence"),
                     p.get("scale_evidence"), r["xbrl"]])
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
