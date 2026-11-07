"""`data resolve`: identity, classification and index memberships for one company."""
from __future__ import annotations

from ..common.entity import resolve
from ..common.provenance import num
from ..common.units import INR_PER_SHARE


def resolve_output(r: dict) -> dict:
    """Wrap the entity's numeric fields in provenance for CLI output."""
    e = r.get("entity")
    if e:
        r["entity"] = {**e, "face_value_inr": num(e.get("face_value_inr"), INR_PER_SHARE, source="NSE equity master (EQUITY_L / SME_EQUITY_L)",
                                                    source_url=(e.get("sources") or [None])[0])}
    return r


def cmd_resolve(args) -> dict:
    r = resolve_output(resolve(args.query, with_bse=not args.no_bse))
    r["notes"] = ("industry is NSE's index-list industry (broad sector) when the company is in a Nifty index; "
                  "basic industry appears in `data filings` announcements (smIndustry). bse_code comes from the latest BSE bhavcopy.")
    return r


def register(sub, leaf) -> None:
    p = leaf(sub, "resolve", "Resolve symbol / ISIN / name to ISIN, NSE symbol, BSE code, legal name, industry, index memberships")
    p.add_argument("query")
    p.add_argument("--no-bse", action="store_true", help="skip BSE code lookup")
    p.set_defaults(func=cmd_resolve)
