"""Re-record the unit-test fixtures from the local download cache (data/cache).

Run `uv run python tests/fixtures/record.py` after a live `data ...` call has
filled the cache. Fixtures are trimmed copies of real exchange responses, so
tests exercise the real formats without touching the network. Nothing here is
fabricated: rows are only filtered, never edited.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache"
OUT = Path(__file__).resolve().parent

RELIANCE, HDFCBANK, CAMS = "INE002A01018", "INE040A01034", "INE596I01020"


def _date_key(s: str) -> str:
    import datetime as dt
    return dt.datetime.strptime(s, "%d-%b-%Y").date().isoformat()


def price_window(isin: str, chunk: str, lo: str, hi: str, name: str) -> None:
    d = json.loads((CACHE / isin / "nse_price" / f"{chunk}.json").read_text())
    rows = [r for r in d["data"] if lo <= _date_key(r["mTIMESTAMP"]) <= hi]
    (OUT / name).write_text(json.dumps({"data": rows}, indent=0))


def corp_actions(isin: str, name: str) -> None:
    d = json.loads((CACHE / isin / "nse_ca" / "2023-11-04_2026-11-08.json").read_text())
    (OUT / name).write_text(json.dumps(d, indent=0))


def copy(src: str, name: str) -> None:
    (OUT / name).write_bytes(Path(glob.glob(str(CACHE / src))[0]).read_bytes())


SHP_FACTS = {"ShareholdingAsAPercentageOfTotalNumberOfShares", "NumberOfShares", "ISIN", "Symbol", "DateOfReport",
             "PledgedOrEncumberedNumberOfShares",
             "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged",
             "WhetherAnySharesHeldByPromotersAreEncumberedUnderNonDisposalUndertaking",
             "WhetherAnySharesHeldByPromotersAreEncumberedOtherThanByWayOfPledgeOrNDU",
             "WhetherAnySharesHeldByPromotersArePledgeOrOtherwiseEncumbered"}
SHP_CONTEXTS = {"ShareholdingOfPromoterAndPromoterGroup_ContextI", "PublicShareholding_ContextI", "InstitutionsForeign_ContextI",
                "InstitutionsDomestic_ContextI", "MutualFundsOrUTI_ContextI", "InsuranceCompanies_ContextI",
                "NonInstitutions_ContextI", "Governments_ContextI",
                # pre-2025 taxonomy
                "ShareholdingOfPromoterAndPromoterGroupI", "PublicShareholdingI", "InstitutionsForeignI", "InstitutionsDomesticI",
                "MutualFundsOrUtiI", "InsuranceCompaniesI", "NonInstitutionsI", "CentralGovernmentOrPresidentOfIndiaI",
                "StateGovernmentsOrGovernorsI"}


def shp_trim(src: str, name: str) -> None:
    """Keep only the category contexts and facts parse_shp reads (full files are ~0.5 MB)."""
    root = etree.fromstring(Path(glob.glob(str(CACHE / src))[0]).read_bytes())
    keep_ctx = set(SHP_CONTEXTS)
    for el in root:
        if isinstance(el.tag, str) and etree.QName(el).localname in SHP_FACTS and el.get("contextRef") and etree.QName(el).localname not in ("NumberOfShares", "ShareholdingAsAPercentageOfTotalNumberOfShares"):
            keep_ctx.add(el.get("contextRef"))
    for el in list(root):
        if not isinstance(el.tag, str):
            root.remove(el)
            continue
        local = etree.QName(el).localname
        if local == "context":
            if el.get("id") not in keep_ctx:
                root.remove(el)
        elif el.get("contextRef") is not None:
            if local not in SHP_FACTS or el.get("contextRef") not in keep_ctx:
                root.remove(el)
    (OUT / name).write_bytes(etree.tostring(root, xml_declaration=True, encoding="utf-8"))


def trimmed_list(isin: str, rel: str, name: str, keep) -> None:
    d = json.loads((CACHE / isin / rel).read_text())
    if isinstance(d, dict) and "data" in d:
        d = {**d, "data": [r for r in d["data"] if keep(r)]}
        d["totalCount"] = len(d["data"])
    else:
        d = [r for r in d if keep(r)]
    (OUT / name).write_text(json.dumps(d, indent=0))


def main() -> None:
    price_window(RELIANCE, "2024-08-24_2024-11-21", "2024-10-01", "2024-11-15", "nse_price_RELIANCE_2024-10.json")
    corp_actions(RELIANCE, "nse_ca_RELIANCE.json")
    price_window(CAMS, "2025-11-03_2026-01-31", "2025-11-10", "2025-12-31", "nse_price_CAMS_2025-11.json")
    corp_actions(CAMS, "nse_ca_CAMS.json")
    # legacy (pre-integrated) Q3FY25 filing: FourD context carries the quarter's dates
    copy(f"{CAMS}/xbrl/INDAS_117968_1364281_29012025023635.xml", "xbrl_CAMS_legacy_Q3FY25.xml")
    copy(f"{CAMS}/xbrl/INTEGRATED_FILING_INDAS_1498269_30072025062549_WEB.xml", "xbrl_CAMS_integrated_Q1FY26.xml")
    copy(f"{HDFCBANK}/xbrl/INTEGRATED_FILING_BANKING_1487995_19072025065149_WEB.xml", "xbrl_HDFCBANK_integrated_Q1FY26.xml")
    trimmed_list(CAMS, "nse_results/integrated_p1.json", "nse_results_CAMS_integrated.json",
                 lambda r: "1498269" in (r.get("xbrl") or ""))
    trimmed_list(CAMS, "nse_results/legacy_Quarterly.json", "nse_results_CAMS_legacy_quarterly.json",
                 lambda r: "1364281" in (r.get("xbrl") or ""))
    # three SHP formats: current (fractions), Jun-2025 (percent, new contexts), pre-2025 (percent, old contexts)
    for date_tag, fname in (("2026-09", "SHP_1742991_21102026042504_WEB.xml"), ("2025-06", "SHP_1489727_21072025081003_WEB.xml"),
                            ("2025-03", "SHP_198754_1421266_21042025041033_WEB.xml")):
        shp_trim(f"{RELIANCE}/shp/{fname}", f"shp_RELIANCE_{date_tag}.xml")
    shp_trim(f"{HDFCBANK}/shp/*1408519_04042025045009_WEB.xml", "shp_HDFCBANK_2025-03.xml")
    trimmed_list(RELIANCE, "nse_shp/list.json", "nse_shp_RELIANCE_list.json",
                 lambda r: any(x in (r.get("xbrl") or "") for x in ("1742991", "1489727", "1421266")))

if __name__ == "__main__":
    main()
