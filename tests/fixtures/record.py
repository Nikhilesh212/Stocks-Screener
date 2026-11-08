"""Record the unit-test fixtures: trimmed copies of real NSE responses and company filings.

    uv run python tests/fixtures/record.py --fetch   # live calls fill data/cache, then trim
    uv run python tests/fixtures/record.py           # trim from an already filled data/cache

The fixture files are not in git (NSE's terms restrict redistributing its data):
each machine records its own, and until then the tests that need them skip.
--fetch goes through the tools' own data functions and polite HTTP client (rate
limits, robots.txt, cache). Nothing here is fabricated: rows are only filtered,
never edited. If NSE no longer serves an exact historical window or filing,
recording stops, names the fixture and says why, and writes nothing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sys
from contextlib import contextmanager
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache"
OUT = Path(__file__).resolve().parent

RELIANCE, HDFCBANK, CAMS = "INE002A01018", "INE040A01034", "INE596I01020"
SYMBOL = {RELIANCE: "RELIANCE", HDFCBANK: "HDFCBANK", CAMS: "CAMS"}

# fixture -> what it is cut from (cache keys under data/cache/<ISIN>/)
# prices: one 90-day chunk as `data prices` asks NSE for it, then the rows dated lo..hi
PRICES = {"nse_price_RELIANCE_2024-10.json": (RELIANCE, "2024-08-24_2024-11-21", "2024-10-01", "2024-11-15"),
          "nse_price_CAMS_2025-11.json": (CAMS, "2025-11-03_2026-01-31", "2025-11-10", "2025-12-31")}
CA_WINDOW = "2023-11-04_2026-11-08"
CORP_ACTIONS = {"nse_ca_RELIANCE.json": RELIANCE, "nse_ca_CAMS.json": CAMS}
# whole XBRL filings; the legacy Q3FY25 one has a FourD context carrying the quarter's dates
XBRL = {"xbrl_CAMS_legacy_Q3FY25.xml": (CAMS, "INDAS_117968_1364281_29012025023635.xml"),
        "xbrl_CAMS_integrated_Q1FY26.xml": (CAMS, "INTEGRATED_FILING_INDAS_1498269_30072025062549_WEB.xml"),
        "xbrl_HDFCBANK_integrated_Q1FY26.xml": (HDFCBANK, "INTEGRATED_FILING_BANKING_1487995_19072025065149_WEB.xml")}
# three SHP formats: current (fractions), Jun-2025 (percent, new contexts), pre-2025 (percent, old contexts);
# HDFCBANK has no promoter group
SHP = {"shp_RELIANCE_2026-09.xml": (RELIANCE, "SHP_1742991_21102026042504_WEB.xml"),
       "shp_RELIANCE_2025-06.xml": (RELIANCE, "SHP_1489727_21072025081003_WEB.xml"),
       "shp_RELIANCE_2025-03.xml": (RELIANCE, "SHP_198754_1421266_21042025041033_WEB.xml"),
       "shp_HDFCBANK_2025-03.xml": (HDFCBANK, "SHP_196328_1408519_04042025045009_WEB.xml")}
# list responses, keeping the rows whose xbrl link carries one of these filing ids
LISTS = {"nse_results_CAMS_integrated.json": (CAMS, "nse_results/integrated_p*.json", ("1498269",)),
         "nse_results_CAMS_legacy_quarterly.json": (CAMS, "nse_results/legacy_Quarterly.json", ("1364281",)),
         "nse_shp_RELIANCE_list.json": (RELIANCE, "nse_shp/list.json", ("1742991", "1489727", "1421266"))}


class RecordError(Exception):
    """A fixture cannot be cut from what data/cache holds or what NSE serves now."""


@contextmanager
def making(*fixtures: str):
    """Name the fixtures a failing step was for."""
    try:
        yield
    except RecordError:
        raise
    except Exception as ex:
        raise RecordError(f"{', '.join(fixtures)}: {type(ex).__name__}: {ex}") from ex


def sources(fixture: str, rel: str) -> list[Path]:
    hits = sorted(p for p in glob.glob(str(CACHE / rel)) if not p.endswith(".meta.json"))
    if not hits:
        raise RecordError(f"{fixture}: data/cache/{rel} not found (run with --fetch)")
    return [Path(p) for p in hits]


def _date_key(s: str) -> str:
    return dt.datetime.strptime(s, "%d-%b-%Y").date().isoformat()


def price_window(fixture: str, isin: str, chunk: str, lo: str, hi: str) -> bytes:
    src = sources(fixture, f"{isin}/nse_price/{chunk}.json")[0]
    rows = [r for r in json.loads(src.read_text())["data"] if lo <= _date_key(r["mTIMESTAMP"]) <= hi]
    if not rows:
        raise RecordError(f"{fixture}: no rows dated {lo}..{hi} in {src.relative_to(ROOT)}")
    return json.dumps({"data": rows}, indent=0).encode()


def corp_actions(fixture: str, isin: str) -> bytes:
    d = json.loads(sources(fixture, f"{isin}/nse_ca/{CA_WINDOW}.json")[0].read_text())
    if not d:
        raise RecordError(f"{fixture}: NSE returned no corporate actions for {CA_WINDOW}")
    return json.dumps(d, indent=0).encode()


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


def shp_trim(fixture: str, isin: str, fname: str) -> bytes:
    """Keep only the category contexts and facts parse_shp reads (full files are ~0.5 MB)."""
    root = etree.fromstring(sources(fixture, f"{isin}/shp/{fname}")[0].read_bytes())
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
    return etree.tostring(root, xml_declaration=True, encoding="utf-8")


def trimmed_list(fixture: str, isin: str, rel: str, ids: tuple[str, ...]) -> bytes:
    """Rows from one list response, or from all its pages (a filing moves to later pages as new ones arrive)."""
    pages = [json.loads(p.read_text()) for p in sources(fixture, f"{isin}/{rel}")]

    def keep(r: dict) -> bool:
        return any(i in (r.get("xbrl") or "") for i in ids)

    d = pages[0]
    if isinstance(d, dict) and "data" in d:
        d = {**d, "data": [r for p in pages for r in p.get("data", []) if keep(r)]}
        d["totalCount"] = len(d["data"])
        rows = d["data"]
    else:
        d = rows = [r for p in pages for r in p if keep(r)]
    found = {i for i in ids if any(i in (r.get("xbrl") or "") for r in rows)}
    if found != set(ids):
        raise RecordError(f"{fixture}: filing ids {sorted(set(ids) - found)} not in data/cache/{isin}/{rel}")
    return json.dumps(d, indent=0).encode()


def whole_filing(fixture: str, isin: str, fname: str) -> bytes:
    return sources(fixture, f"{isin}/xbrl/{fname}")[0].read_bytes()


def build() -> dict[str, bytes]:
    jobs = [(price_window, PRICES), (corp_actions, {f: (isin,) for f, isin in CORP_ACTIONS.items()}),
            (whole_filing, XBRL), (shp_trim, SHP), (trimmed_list, LISTS)]
    out = {}
    for cut, table in jobs:
        for fixture, args in table.items():
            with making(fixture):
                out[fixture] = cut(fixture, *args)
    return out


def fetch_sources() -> None:
    """Fill data/cache with every file build() reads, through the tools' data functions and their cache keys."""
    sys.path.insert(0, str(ROOT))
    from tools.common.cache import fetch
    from tools.common.entity import get_entity
    from tools.common.sources import TTL_LIST, nse_api
    from tools.data.corpactions import corporate_actions
    from tools.data.financials import list_filings
    from tools.data.prices import raw_history

    def fixtures_of(isin: str) -> list[str]:
        return [f for table in (PRICES, CORP_ACTIONS, XBRL, SHP, LISTS) for f, v in table.items()
                if (v if isinstance(v, str) else v[0]) == isin]

    ent = {}
    for isin, sym in SYMBOL.items():
        with making(*fixtures_of(isin)):
            ent[isin] = get_entity(sym)
        if ent[isin].isin != isin:
            raise RecordError(f"{', '.join(fixtures_of(isin))}: {sym} now resolves to {ent[isin].isin}, not {isin}")

    for fixture, (isin, chunk, _, _) in PRICES.items():
        s, e = (dt.date.fromisoformat(x) for x in chunk.split("_"))
        with making(fixture):
            _, urls = raw_history(ent[isin], s, e)
        if len(urls) > 1:
            raise RecordError(f"{fixture}: NSE truncated the {chunk} chunk, so data/cache holds only its latest rows")

    ca_start, ca_end = (dt.date.fromisoformat(x) for x in CA_WINDOW.split("_"))
    for fixture, isin in CORP_ACTIONS.items():
        with making(fixture):
            corporate_actions(ent[isin], ca_start, ca_end)

    # filing links come from NSE's own lists, as `data financials` and `data shareholding` find them
    results: dict[str, list[str]] = {}
    for isin in {i for i, _ in XBRL.values()}:
        with making(*fixtures_of(isin)):
            for basis in ("consolidated", "standalone"):
                rows, warns = list_filings(ent[isin], basis)
                if warns:
                    raise RecordError("; ".join(warns))
                results.setdefault(isin, []).extend(r["xbrl"] for r in rows)
    for fixture, (isin, fname) in XBRL.items():
        _fetch_filing(fetch, fixture, results[isin], f"{isin}/xbrl/{fname}")

    shp: dict[str, list[str]] = {}
    for isin in {i for i, _ in SHP.values()}:
        with making(*fixtures_of(isin)):
            data, _ = nse_api("corporate-share-holdings-master", {"index": "equities", "symbol": ent[isin].nse_symbol},
                              key=f"{isin}/nse_shp/list.json", ttl_hours=TTL_LIST)
        shp[isin] = [r["xbrl"] for r in data or [] if r.get("xbrl")]
    for fixture, (isin, fname) in SHP.items():
        _fetch_filing(fetch, fixture, shp[isin], f"{isin}/shp/{fname}")


def _fetch_filing(fetch, fixture: str, links: list[str], key: str) -> None:
    fname = key.rsplit("/", 1)[-1]
    url = next((u for u in links if u.rsplit("/", 1)[-1] == fname), None)
    if url is None:
        raise RecordError(f"{fixture}: NSE's filing list no longer links {fname}")
    with making(fixture):
        fetch(url, key=key, ttl_hours=None)


def main() -> None:
    ap = argparse.ArgumentParser(description="Record the unit-test fixtures from data/cache.")
    ap.add_argument("--fetch", action="store_true", help="first make the live calls that fill data/cache")
    args = ap.parse_args()
    try:
        if args.fetch:
            fetch_sources()
        fixtures = build()
    except RecordError as ex:
        sys.exit(f"record.py: cannot record {ex}")
    for name, content in fixtures.items():
        (OUT / name).write_bytes(content)
        print(f"{name}  {len(content)} bytes")
    print(f"{len(fixtures)} fixtures written to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
