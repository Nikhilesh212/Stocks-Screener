"""Data layer against recorded exchange responses (tests/fixtures, trimmed real files).

Expected values are hand-checked from the raw fixture rows, e.g. RELIANCE
25-Oct-2024 close 2655.70 / bonus factor 2 = 1327.85.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time

import pytest

from tools.common import cache
from tools.common.entity import Entity
from tools.common.periods import fy_label, parse_date, period_label, quarter_end_dates, quarter_label
from tools.common.provenance import derived, find_bare_numbers, missing, num, table
from tools.common.units import divisor_for, parse_number, to_crore
from tools.data import financials, prices, shareholding, xbrl
from tools.data.corpactions import corporate_actions, parse_subject
from tools.data.resolve import resolve_output

from .conftest import FIXTURES

D = dt.date

RELIANCE = Entity("INE002A01018", "RELIANCE", "Reliance Industries Limited", "EQ", "main", "1995-11-29", 10.0)
# CAMS after the split: new ISIN, while NSE's corporate-action feed still carries the old one
CAMS = Entity("INE596I01020", "CAMS", "Computer Age Management Services Limited", "EQ", "main", "2020-10-01", 2.0)


# ---------------------------------------------------------------- corporate-action text

@pytest.mark.parametrize("subject, kind, factor, cash", [
    ("Bonus 1:1", "bonus", 2.0, None),
    ("Bonus 4:1", "bonus", 5.0, None),
    ("Bonus 3:2", "bonus", 2.5, None),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", "split", 5.0, None),
    ("Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share", "split", 2.0, None),
    ("Consolidation Of Shares From Re 1/- Per Share To Rs 10/- Per Share", "consolidation", 0.1, None),
    ("Rights 1:15 @ Premium Rs 1247/-", "rights", None, None),
    ("Dividend - Rs 10 Per Share", "dividend", None, 10.0),
    ("Interim Dividend - Rs 14.5 Per Share/Special Dividend - Rs 10.5 Per Share", "dividend", None, 25.0),
    ("Demerger", "demerger", None, None),
    ("Buy Back", "buyback", None, None),
])
def test_parse_subject(subject, kind, factor, cash):
    k, f, c = parse_subject(subject)
    assert k == kind
    assert f == pytest.approx(factor) if factor is not None else f is None
    assert c == pytest.approx(cash) if cash is not None else c is None


def test_rights_factor_is_terp():
    a = prices.CorpAction(D(2020, 5, 20), "rights", "Rights 1:15 @ Premium Rs 1247/-", None, None)
    # issue = FV 10 + 1247 = 1257; TERP = (15*1500 + 1*1257)/16 = 1484.8125; factor = 1500/1484.8125
    assert prices._rights_factor(a, 10.0, 1500.0) == pytest.approx(1500 / 1484.8125)
    assert prices._rights_factor(a, 10.0, 1200.0) == 1.0  # issue price above market: no value


def test_corporate_actions_keep_old_isin_records(routes):
    routes({"corporates-corporateActions": "nse_ca_CAMS.json"})
    acts, url, _ = corporate_actions(CAMS, D(2023, 11, 4), D(2026, 11, 8))
    split = [a for a in acts if a.kind == "split"]
    assert len(split) == 1 and split[0].ex_date == D(2025, 12, 5) and split[0].factor == 5.0
    assert sum(a.kind == "dividend" for a in acts) == 12
    assert [a.ex_date for a in acts] == sorted(a.ex_date for a in acts)


# ---------------------------------------------------------------- price adjustment

def _rows(df, day):
    return df[df["date"] == day].iloc[0]


def test_reliance_bonus_adjustment(routes):
    routes({"generateSecurityWiseHistoricalData": "nse_price_RELIANCE_2024-10.json",
            "corporates-corporateActions": "nse_ca_RELIANCE.json"})
    h = prices.history(RELIANCE, D(2024, 10, 1), D(2024, 11, 15))
    df = h["df"]
    assert len(df) == 32
    pre, ex = _rows(df, D(2024, 10, 25)), _rows(df, D(2024, 10, 28))
    assert pre["close"] == 2655.7 and pre["adj_factor"] == 2.0
    assert pre["adj_close"] == pytest.approx(1327.85)
    assert pre["adj_volume"] == 9298748 * 2
    assert ex["adj_factor"] == 1.0 and ex["adj_close"] == 1334.35
    bonus = next(a for a in h["actions"] if a["kind"] == "bonus")
    assert bonus["applied_factor"] == 2.0 and bonus["check"] == "ok"
    assert bonus["observed_gap"] == pytest.approx(2655.7 / 1337)
    # no dividend inside the window: TR index is the plain adjusted price ratio
    assert df["tr_index"].iloc[-1] == pytest.approx(100 * 1267.6 / (2929.65 / 2))
    assert h["warnings"] == []
    assert h["path"].exists()


def test_cams_split_adjustment(routes):
    routes({"generateSecurityWiseHistoricalData": "nse_price_CAMS_2025-11.json",
            "corporates-corporateActions": "nse_ca_CAMS.json"})
    h = prices.history(CAMS, D(2025, 11, 10), D(2025, 12, 31))
    df = h["df"]
    assert _rows(df, D(2025, 12, 4))["adj_close"] == pytest.approx(3956.7 / 5)
    assert _rows(df, D(2025, 11, 10))["adj_factor"] == 5.0
    assert _rows(df, D(2025, 12, 5))["adj_factor"] == 1.0
    split = next(a for a in h["actions"] if a["kind"] == "split")
    assert split["applied_factor"] == 5.0 and split["check"] == "ok"
    # dividends before the window are logged as outside the price range, not applied
    assert all(a["check"] == "outside price range" for a in h["actions"] if a["kind"] == "dividend" and a["ex_date"] < "2025-11-10")
    assert h["warnings"] == []


def test_adjust_flags_factor_that_disagrees_with_gap():
    import pandas as pd
    raw = pd.DataFrame({"date": [D(2024, 1, 1), D(2024, 1, 2)], "close": [100.0, 99.0], "open": [100.0, 99.0],
                        "high": [100.0, 99.0], "low": [100.0, 99.0], "vwap": [100.0, 99.0], "volume": [10.0, 10.0]})
    act = prices.CorpAction(D(2024, 1, 2), "bonus", "Bonus 1:1", 2.0, None)
    _, log, warns = prices.adjust(raw, [act])
    assert log[0]["check"].startswith("CHECK")
    assert any("verify" in w for w in warns)


def test_unexplained_gap_warns_without_adjusting():
    import pandas as pd
    raw = pd.DataFrame({"date": [D(2024, 1, 1), D(2024, 1, 2)], "close": [100.0, 50.0], "open": [100.0, 50.0],
                        "high": [100.0, 50.0], "low": [100.0, 50.0], "vwap": [100.0, 50.0], "volume": [10.0, 10.0]})
    df, _, warns = prices.adjust(raw, [])
    assert df["adj_factor"].tolist() == [1.0, 1.0]
    assert any("no listed corporate action" in w for w in warns)


def test_cmd_prices_has_no_bare_numbers(routes, monkeypatch):
    routes({"generateSecurityWiseHistoricalData": "nse_price_RELIANCE_2024-10.json",
            "corporates-corporateActions": "nse_ca_RELIANCE.json", "sec_bhavdata_full": 404})
    monkeypatch.setattr(prices, "get_entity", lambda q: RELIANCE)
    out = prices.cmd_prices(argparse.Namespace(query="RELIANCE", start="2024-10-01", to="2024-11-15", years=3.0, rows=5))
    assert find_bare_numbers(out) == []
    bonus = next(a for a in out["corporate_actions"] if a["kind"] == "bonus")
    assert bonus["applied_factor"]["value"] == 2.0 and bonus["factor"]["unit"] == "shares per pre-event share"
    assert out["last"]["close"]["value"] == 1267.6
    assert out["crosscheck_last_close"]["flag"] is None  # bhavcopy 404 reported, not hidden


# ---------------------------------------------------------------- XBRL results

def test_legacy_fourd_context_gets_year_to_date_start():
    inst = xbrl.parse((FIXTURES / "xbrl_CAMS_legacy_Q3FY25.xml").read_bytes())
    four = inst.contexts["FourD"]
    assert (four.start, four.end) == (D(2024, 4, 1), D(2024, 12, 31))  # filed with the quarter's dates
    rev = {period_label(c.start, c.end): v / 1e7 for c, v, _ in xbrl.values_by_period(inst, "RevenueFromOperations")}
    assert rev == {"Q3FY25": pytest.approx(369.7429), "9MFY25": pytest.approx(1066.3175)}


def test_bank_xbrl_extract():
    inst = xbrl.parse((FIXTURES / "xbrl_HDFCBANK_integrated_Q1FY26.xml").read_bytes())
    assert any(f.name == "InterestEarned" for f in inst.facts)
    got = {(item, period_label(s, e)): (v, u) for item, kind, s, e, v, u in financials._extract(inst, financials.BANK) if kind == "duration"}
    assert got[("interest_earned", "Q1FY26")][0] == pytest.approx(87371.87, abs=0.01)
    assert got[("pat", "Q1FY26")][0] == pytest.approx(17090.43, abs=0.01)
    assert got[("pat_owners", "Q1FY26")][0] == pytest.approx(16257.91, abs=0.01)
    assert got[("minority_interest", "Q1FY26")][0] == pytest.approx(832.52, abs=0.01)
    assert got[("pat", "Q1FY26")][1] == "INR crore"
    assert got[("eps_basic", "Q1FY26")][1] == "INR/share"


def test_financials_statements_end_to_end(routes, monkeypatch):
    routes({"integrated-filing-results": "nse_results_CAMS_integrated.json",
            "period=Quarterly": "nse_results_CAMS_legacy_quarterly.json",
            "period=Annual": b"[]",
            "INTEGRATED_FILING_INDAS_1498269": "xbrl_CAMS_integrated_Q1FY26.xml",
            "INDAS_117968_1364281": "xbrl_CAMS_legacy_Q3FY25.xml"})
    monkeypatch.setattr(financials, "get_entity", lambda q: CAMS)
    out = financials.cmd_financials(argparse.Namespace(query="CAMS", basis="consolidated", quarters=8, years=2))
    assert find_bare_numbers(out) == []
    q = out["quarterly"]
    rows = {r[0]: dict(zip(q["columns"], r)) for r in q["rows"]}
    assert rows["Q3FY25"]["revenue"] == pytest.approx(369.7429)
    assert "Q1FY26" in rows and q["units"]["revenue"] == "INR crore"
    assert "9MFY25" not in rows  # year-to-date columns never leak into the quarterly table
    cov = out["coverage"]
    assert cov["missing_quarters"] == ["Q4FY25", "Q2FY25", "Q1FY25", "Q4FY24", "Q3FY24", "Q2FY24"]
    assert cov["missing_not_in_filing_list"] == cov["missing_quarters"]  # the trimmed list only has two filings
    assert out["is_bank_format"] is False


def test_crosscheck_note_explains_minority_tagging():
    v = {}
    for q, rev, pat, owners, mi in (("Q1FY26", 10, 5, 4, 1), ("Q2FY26", 10, 4, 4, 0), ("Q3FY26", 10, 5, 4, 1), ("Q4FY26", 10, 4, 4, 0),
                                    ("FY26", 40, 16, 16, 0)):
        for item, val in (("interest_earned", rev), ("pat", pat), ("pat_owners", owners), ("minority_interest", mi)):
            v[(q, item)] = (val, "INR crore", "x.xml", D(2026, 3, 31))
    note = financials._crosscheck_note(v, "pat", "FY26", ["Q1FY26", "Q2FY26", "Q3FY26", "Q4FY26"], "minority_interest", "interest_earned")
    assert "reconciles" in note and "tagging inconsistency" in note


# ---------------------------------------------------------------- shareholding XBRL

@pytest.mark.parametrize("fname, promoter, public, fii, gov, scale", [
    ("shp_RELIANCE_2026-09.xml", 50.44, 49.56, 16.67, 0.1, "fractions"),   # current taxonomy, fractions
    ("shp_RELIANCE_2025-06.xml", 50.07, 49.93, 19.21, 0.1, "percent"),     # current contexts, whole percent
    ("shp_RELIANCE_2025-03.xml", 50.11, 49.89, 19.06, 0.09, "percent"),    # pre-2025 taxonomy (no _Context suffix)
    ("shp_HDFCBANK_2025-03.xml", 0.0, 100.0, 48.3, 0.0, "percent"),        # no promoter group
])
def test_parse_shp_formats(fname, promoter, public, fii, gov, scale):
    p = shareholding.parse_shp((FIXTURES / fname).read_bytes())
    assert p["promoter"] == pytest.approx(promoter)
    assert p["public"] == pytest.approx(public)
    assert p["fii_fpi"] == pytest.approx(fii)
    assert p["government"] == pytest.approx(gov)
    assert scale in p["scale_evidence"]
    if promoter:
        assert p["pledged_pct_of_promoter"] == 0.0
    else:
        assert p["pledged_pct_of_promoter"] is None and "no promoter" in p["pledge_evidence"]


def test_cmd_shareholding_end_to_end(routes, monkeypatch):
    routes({"corporate-share-holdings-master": "nse_shp_RELIANCE_list.json",
            "SHP_1742991": "shp_RELIANCE_2026-09.xml", "SHP_1489727": "shp_RELIANCE_2025-06.xml",
            "1421266": "shp_RELIANCE_2025-03.xml"})
    monkeypatch.setattr(shareholding, "get_entity", lambda q: RELIANCE)
    out = shareholding.cmd_shareholding(argparse.Namespace(query="RELIANCE", quarters=8))
    assert find_bare_numbers(out) == []
    t = out["shareholding"]
    assert [r[0] for r in t["rows"]] == ["2026-09-30", "2025-06-30", "2025-03-31"]
    assert [r[1] for r in t["rows"]] == [50.44, 50.07, 50.11]
    assert out["warnings"] == []  # master-list promoter % agrees with XBRL after scaling


# ---------------------------------------------------------------- periods and units

def test_fiscal_periods():
    assert fy_label(D(2026, 3, 31)) == "FY26" and fy_label(D(2026, 4, 1)) == "FY27"
    assert quarter_label(D(2026, 9, 30)) == "Q2FY27" and quarter_label(D(2026, 12, 31)) == "Q3FY27"
    assert quarter_label(D(2027, 3, 31)) == "Q4FY27"
    assert period_label(D(2025, 4, 1), D(2025, 9, 30)) == "H1FY26"
    assert period_label(D(2024, 4, 1), D(2024, 12, 31)) == "9MFY25"
    assert period_label(D(2024, 4, 1), D(2025, 3, 31)) == "FY25"
    assert period_label(None, D(2025, 3, 31)) == "as of 2025-03-31"
    assert quarter_end_dates(D(2026, 11, 8), 3) == [D(2026, 9, 30), D(2026, 6, 30), D(2026, 3, 31)]
    assert quarter_end_dates(D(2026, 3, 31), 2) == [D(2026, 3, 31), D(2025, 12, 31)]
    assert parse_date("28-Oct-2024") == D(2024, 10, 28) and parse_date("31-MAR-2025") == D(2025, 3, 31)
    assert parse_date("2025-12-05T00:00:00") == D(2025, 12, 5) and parse_date("-") is None


def test_units():
    assert parse_number("1,23,456.78") == 123456.78
    assert parse_number("(12.5)") == -12.5
    assert parse_number("12.3%") == 12.3
    assert parse_number("-") is None and parse_number("nil") is None and parse_number("") is None
    assert to_crore(5, "lakh") == pytest.approx(0.05)
    assert to_crore(250, "Rs. Million") == pytest.approx(25.0)
    assert to_crore(None, "crore") is None
    with pytest.raises(ValueError):
        divisor_for("furlongs")


# ---------------------------------------------------------------- provenance and cache

def test_find_bare_numbers():
    ok = {"a": num(1.0, "x", source="s"), "b": missing("n/a"), "c": derived(2.0, "x", formula="a*2", inputs=[num(1.0, "x", source="s")]),
          "t": table(["d", "v"], [["2024-01-01", 1.0]], units={"v": "x"}, source="s"), "page": 4, "label": "text", "flag": True}
    assert find_bare_numbers(ok) == []
    assert find_bare_numbers({"x": [1, {"y": 2.5}]}) == ["$.x[0]", "$.x[1].y"]
    assert num(float("nan"), "x", source="s")["value"] is None


def test_resolve_output_wraps_face_value():
    r = resolve_output({"status": "resolved", "entity": {**RELIANCE.to_dict(), "sources": ["https://example/EQUITY_L.csv"]}})
    assert find_bare_numbers(r) == []
    assert r["entity"]["face_value_inr"]["value"] == 10.0


def test_empty_response_not_cached_forever(offline):
    cache.write_cached("_market/x/empty.json", b'{"data": []}', "u", ttl_hours=cache.EMPTY_TTL_HOURS)
    cache.write_cached("_market/x/full.json", b'{"data": [1]}', "u")
    assert cache.read_cached("_market/x/empty.json", None) is not None
    for name in ("empty", "full"):  # age both entries by 7 hours
        m = cache._meta_path(cache.cache_path(f"_market/x/{name}.json"))
        meta = json.loads(m.read_text())
        meta["epoch"] = time.time() - 7 * 3600
        m.write_text(json.dumps(meta))
    assert cache.read_cached("_market/x/empty.json", None) is None
    assert cache.read_cached("_market/x/full.json", None) is not None
    assert cache.is_empty_payload(b"[]") and cache.is_empty_payload(b'{"data": [], "totalCount": 0}')
    assert not cache.is_empty_payload(b'{"data": [{"a": 1}]}')


def test_fetch_gives_empty_bodies_short_ttl(routes):
    routes({"nseindia.com/api/x": b"[]"})
    cache.fetch("https://www.nseindia.com/api/x", key="_market/x/past.json", ttl_hours=None)
    meta = json.loads(cache._meta_path(cache.cache_path("_market/x/past.json")).read_text())
    assert meta["ttl_hours"] == cache.EMPTY_TTL_HOURS
