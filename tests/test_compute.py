"""Compute group against hand-checked synthetic inputs (no network, no cache).

Each expected value is worked out by hand in the comment next to it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from tools.common.errors import InputError
from tools.common.provenance import find_bare_numbers
from tools.compute import _util, base_rates, calc, costs_tax, portfolio, ratios, reverse_dcf, technicals, valuation
from tools.data.corpactions import CorpAction

D = dt.date


def tbl(columns: list[str], rows: list[list]) -> dict:
    return {"kind": "table", "columns": columns, "rows": rows, "units": {}}


# ---------------------------------------------------------------- _util

def test_util_helpers():
    assert _util.cagr(100, 121, 2) == (pytest.approx(0.1), None)
    assert _util.cagr(-1, 5, 2)[0] is None and "negative" in _util.cagr(-1, 5, 2)[1]
    assert _util.safe_div(1, 0) is None and _util.fnum(float("nan")) is None
    assert _util.percentile_rank(3, [1, 2, 3, 4]) == 62.5  # (2 below + 0.5 tie) / 4
    assert _util.normal_quantile(0.975) == pytest.approx(1.959964, abs=1e-6)
    assert _util.t_quantile(0.975, 10) == pytest.approx(2.228, abs=0.01)
    lo, hi = _util.wilson_ci(0.5, 100)
    assert (lo, hi) == (pytest.approx(0.4038, abs=1e-3), pytest.approx(0.5962, abs=1e-3))
    lo, hi = _util.mean_ci(np.array([1.0, 2, 3, 4, 5]), 5)  # mean 3, sd 1.5811, t(4) 2.776 -> +-1.963
    assert (lo, hi) == (pytest.approx(1.037, abs=0.03), pytest.approx(4.963, abs=0.03))


def test_unadjusted_gap_guard():
    px = pd.DataFrame({"date": [D(2025, 1, 1), D(2025, 1, 2), D(2025, 1, 3)], "close": [200.0, 100.0, 101.0],
                       "open": [199.0, 100.0, 100.0], "adj_factor": [1.0, 1.0, 1.0]})
    assert len(_util.unadjusted_gaps(px)) == 1
    px["adj_factor"] = [2.0, 1.0, 1.0]  # adjusted for a 1:1 bonus: gap explained
    assert _util.unadjusted_gaps(px) == []


# ---------------------------------------------------------------- calc

def test_calc_evaluate_and_guards():
    assert calc.evaluate("(a-b)/b*100", {"a": 110, "b": 100}) == pytest.approx(10)
    assert calc.evaluate("cagr(100, 121, 2)") == pytest.approx(0.1)
    assert calc.evaluate("avg(1, 2, 3) + max(4, 5)") == pytest.approx(7)
    for bad in ("__import__('os')", "a.b", "x[0]", "2**10000", "unknown + 1"):
        with pytest.raises(calc.CalcError):
            calc.evaluate(bad, {"a": 1, "x": 1})
    out = calc.cmd_calc(argparse.Namespace(expr="a/b", var=["a=1,000", "b=4"], unit="x", label="test"))
    assert out["result"]["value"] == 250 and find_bare_numbers(out) == []


# ---------------------------------------------------------------- ratios

PL_COLS = ["period", "period_end", "revenue", "other_income", "finance_costs", "depreciation", "pbt_before_exceptional", "pbt", "tax",
           "pat", "pat_owners", "cfo", "capex_ppe", "capex_intangibles", "cost_of_materials", "purchases_stock_in_trade",
           "change_in_inventories", "paid_up_capital", "face_value", "eps_basic"]
BS_COLS = ["period", "period_end", "total_equity", "equity_owners", "borrowings_noncurrent", "borrowings_current", "cash",
           "other_bank_balances", "current_investments", "trade_receivables_current", "inventories", "trade_payables_current"]


def corp_fin() -> dict:
    annual = tbl(PL_COLS, [
        ["FY25", "2025-03-31", 1000, 50, 20, 30, 200, 200, 50, 150, 150, 180, 60, 10, 400, 0, 0, 1e9, 10, 15],
        ["FY24", "2024-03-31", 800, 40, 20, 30, 150, 150, 40, 110, 110, 120, 50, 0, 320, 0, 0, 5e8, 10, 22],
    ])
    bs = tbl(BS_COLS, [
        ["as of 2025-03-31", "2025-03-31", 1100, 1100, 200, 100, 50, 10, 40, 100, 80, 60],
        ["as of 2024-03-31", "2024-03-31", 900, 900, 200, 100, 40, 0, 0, 80, 70, 50],
    ])
    q = tbl(["period", "period_end", "revenue", "other_income", "finance_costs", "depreciation", "pbt_before_exceptional", "pat",
             "pat_owners", "eps_basic"],
            [["Q4FY25", "2025-03-31", 280, 10, 5, 8, 60, 45, 45, 4.5], ["Q3FY25", "2024-12-31", 250, 10, 5, 7, 50, 38, 38, 3.8],
             ["Q2FY25", "2024-09-30", 240, 15, 5, 8, 45, 34, 34, 3.4], ["Q1FY25", "2024-06-30", 230, 15, 5, 7, 45, 33, 33, 6.6]])
    return {"basis": "consolidated", "is_bank_format": False, "annual": annual, "balance_sheet": bs, "quarterly": q}


BONUS_JUL24 = [CorpAction(D(2024, 7, 15), "bonus", "Bonus 1:1", 2.0, None)]


def test_corporate_ratios_hand_checked():
    out = ratios.compute(corp_fin(), actions=BONUS_JUL24)
    t = out["annual_ratios"]
    r = dict(zip(t["columns"], t["rows"][0]))  # FY25 (newest first)
    assert r["ebitda"] == 200  # 200 + 20 + 30 - 50
    assert r["ebit"] == 220
    assert r["ebitda_margin_pct"] == pytest.approx(20) and r["pat_margin_pct"] == pytest.approx(15)
    assert r["other_income_pct_pbt"] == pytest.approx(25) and r["effective_tax_rate_pct"] == pytest.approx(25)
    assert r["roe_pct"] == pytest.approx(15)  # 150 / avg(900, 1100)
    assert r["roce_pct"] == pytest.approx(220 / 1300 * 100)  # capital employed avg(1200, 1400)
    assert r["debt_equity"] == pytest.approx(300 / 1100)
    assert r["net_debt"] == 200  # 300 - 50 - 10 - 40
    assert r["interest_coverage"] == pytest.approx(11)
    assert r["fcf"] == 110 and r["ocf_ebitda"] == pytest.approx(0.9) and r["ocf_pat"] == pytest.approx(1.2)
    assert r["receivable_days"] == pytest.approx(36.5)  # 100 / 1000 * 365
    assert r["inventory_days"] == pytest.approx(73) and r["payable_days"] == pytest.approx(54.75)
    assert r["cash_conversion_cycle_days"] == pytest.approx(54.75)
    # bonus 1:1 between FY24 and FY25: FY24's 5 crore shares are 10 on today's basis, so no dilution
    assert r["shares_crore"] == 10 and r["share_count_change_pct"] == pytest.approx(0)
    prev = dict(zip(t["columns"], t["rows"][1]))
    assert prev["share_basis_factor"] == 2 and prev["eps_restated"] == 11
    assert out["contingent_liabilities_pct_networth"]["value"] is None
    assert out["ttm"]["revenue"]["value"] == 1000 and out["ttm"]["eps_restated"]["value"] == pytest.approx(4.5 + 3.8 + 3.4 + 3.3)
    assert find_bare_numbers(out) == []


def test_eps_growth_refuses_unrestated_bonus():
    recs = [{"period": "FY24", "period_end": "2024-03-31", "eps_basic": 22.0, "eps_restated": 11.0, "shares_crore": 5.0},
            {"period": "FY25", "period_end": "2025-03-31", "eps_basic": 15.0, "eps_restated": 15.0, "shares_crore": 10.0}]
    g = ratios.growth(recs, ["eps_restated", "eps_basic"], spans=(1,))
    assert g["eps_restated"]["1y"]["value"] == pytest.approx(36.36, abs=0.01)  # 15 / 11 - 1
    assert g["eps_basic"]["1y"]["value"] is None and "bonus/split" in g["eps_basic"]["1y"]["notes"]


def test_without_actions_nothing_is_restated():
    out = ratios.compute(corp_fin(), actions=None)
    assert any("not restated" in n for n in out["share_basis_notes"])
    t = out["annual_ratios"]
    assert all(row[t["columns"].index("eps_restated")] is None for row in t["rows"])


def test_bank_ratios_zero_is_missing_and_pcr():
    cols = ["period", "period_end", "interest_earned", "interest_expended", "other_income", "operating_expenses", "provisions", "pat",
            "gross_npa", "net_npa", "gnpa_pct", "nnpa_pct", "car", "cet1_ratio", "paid_up_capital", "face_value", "eps_basic"]
    fin = {"is_bank_format": True, "basis": "standalone",
           "annual": tbl(cols, [["FY25", "2025-03-31", 1000, 600, 100, 250, 40, 150, 100, 30, 0, 0, 0, 0, 1e9, 1, 1.5]]),
           "balance_sheet": tbl(["period", "period_end", "total_assets", "advances", "deposits", "capital", "reserves"],
                                [["as of 2025-03-31", "2025-03-31", 10000, 6000, 8000, 100, 900]]),
           "quarterly": tbl(["period", "period_end"], [])}
    out = ratios.compute(fin, actions=[])
    r = dict(zip(out["annual_ratios"]["columns"], out["annual_ratios"]["rows"][0]))
    assert r["nii"] == 400 and r["nii_to_avg_assets_pct"] == pytest.approx(4)
    assert r["cost_to_income_pct"] == pytest.approx(50)  # 250 / (400 + 100)
    assert r["pcr_pct"] == pytest.approx(70)  # (100 - 30) / 100
    assert r["gnpa_pct_filed"] is None and r["car_filed"] is None  # filed 0 = not reported
    assert r["credit_deposit_pct"] == pytest.approx(75) and r["roe_pct"] == pytest.approx(15)
    assert find_bare_numbers(out) == []


def test_ttm_needs_consecutive_quarters():
    q = [{"period": p, "period_end": e, "revenue": 1.0} for p, e in
         (("Q4FY25", "2025-03-31"), ("Q3FY25", "2024-12-31"), ("Q1FY25", "2024-06-30"), ("Q4FY24", "2024-03-31"))]
    assert ratios.ttm(q, ["revenue"])["revenue"]["value"] is None


# ---------------------------------------------------------------- valuation

def test_public_lag_and_multiples():
    assert valuation.public_from("2024-06-30") == D(2024, 8, 14)  # +45 days
    assert valuation.public_from("2025-03-31") == D(2025, 5, 30)  # Q4: +60 days
    fin = corp_fin()
    f = valuation.fundamentals_at(fin, BONUS_JUL24, D(2025, 6, 1), False)
    assert f["ttm_pat_owners"] == 150  # 45 + 38 + 34 + 33
    assert f["shares_today_basis_crore"] == 10  # Q4FY25 row has no share columns; FY25 annual: 1e9 / 10 / 1e7
    early = valuation.fundamentals_at(fin, BONUS_JUL24, D(2025, 5, 29), False)
    assert early["ttm_pat_owners"] is None  # Q4FY25 not public until 30-May
    m = valuation.multiples(100.0, f, False)  # mcap = 100 x 10 crore = 1000 crore
    assert m["market_cap"] == 1000 and m["pe"] == pytest.approx(1000 / 150)
    assert m["pb"] == pytest.approx(1000 / 1100)
    assert m["ev"] == 1200  # + net debt 200
    ebitda = (60 + 5 + 8 - 10) + (50 + 5 + 7 - 10) + (45 + 5 + 8 - 15) + (45 + 5 + 7 - 15)
    assert m["ev_ebitda"] == pytest.approx(1200 / ebitda)
    assert m["fcf_yield_pct"] == pytest.approx(11)  # 110 / 1000


def test_valuation_percentile_against_own_history():
    days = pd.bdate_range("2025-06-01", "2026-10-30")
    px = pd.DataFrame({"date": [d.date() for d in days], "close": np.linspace(50, 150, len(days))})
    px["adj_close"] = px["close"]
    px["open"] = px["close"]
    px["adj_factor"] = 1.0
    out = valuation.valuation(corp_fin(), px, BONUS_JUL24)
    pe = out["vs_own_history"]["pe"]["5y"]
    n = pe["n_obs"]["value"]
    # fundamentals frozen after FY25, prices rising: today's P/E is the unique maximum of its own history
    assert pe["percentile"]["value"] == pytest.approx((n - 0.5) / n * 100)
    assert "shorter than 5y" in pe["percentile"]["notes"]
    assert out["current"]["pe"]["value"] == pytest.approx(150 * 10 / 150)
    peers = valuation.peer_compare({"pe": 10.0, "pb": None, "ev_ebitda": None, "fcf_yield_pct": None},
                                   {"A": {"pe": 8.0}, "B": {"pe": 12.0}, "C": {"error": "no cache"}}, {k: "x" for k in valuation.MULTIPLES})
    assert peers["pe"]["percentile_vs_peers"]["value"] == 50 and peers["pe"]["peer_median"]["value"] == 10
    assert find_bare_numbers(out) == [] and find_bare_numbers(peers) == []


# ---------------------------------------------------------------- reverse DCF

def test_reverse_dcf_hand_checks():
    # N = F = 0 is Gordon: 10 x 1.05 / (0.12 - 0.05) = 150
    assert reverse_dcf.value(10, 0.3, 0.12, 0, 0, 0.05)["value"] == pytest.approx(150)
    assert reverse_dcf.implied_terminal_growth(150, 10, 0.12) == pytest.approx(0.05)
    # one year at 10%: CF1 = 11, PV 10; TV = 11 x 1.05 / 0.05 = 231, PV 210; total 220
    assert reverse_dcf.value(10, 0.10, 0.10, 1, 0, 0.05)["value"] == pytest.approx(220)
    g, why = reverse_dcf.solve_growth(220, 10, 0.10, 1, 0, 0.05)
    assert why is None and g == pytest.approx(0.10, abs=1e-7)
    # fade: year 1 at 20% -> 12; fade year growth 0.2 - 0.2 x 1/2 = 10% -> 13.2
    assert reverse_dcf.cash_flows(10, 0.2, 1, 1, 0.0) == pytest.approx([12, 13.2])
    g, why = reverse_dcf.solve_growth(1e9, 10, 0.12, 10, 5, 0.05)
    assert g is None and "above the search range" in why
    with pytest.raises(InputError):
        reverse_dcf.value(10, 0.1, 0.05, 5, 0, 0.05)
    with pytest.raises(InputError):
        reverse_dcf.solve_growth(100, -1, 0.12, 5, 0, 0.05)


def test_reverse_dcf_output_and_grids():
    out = reverse_dcf.reverse_dcf(300, 10, ke=0.12, n=10, f=5, gt=0.05, base_label="test")
    g = out["implied_growth"]["value"] / 100
    assert reverse_dcf.value(10, g, 0.12, 10, 5, 0.05)["value"] == pytest.approx(300, rel=1e-6)
    grid = out["sensitivity_ke_x_n"]
    assert grid["columns"][0] == "cost_of_equity_pct" and len(grid["rows"]) == 5
    row12 = next(r for r in grid["rows"] if r[0] == pytest.approx(12))
    assert row12[grid["columns"].index("high_growth_years=10")] == pytest.approx(g * 100, rel=1e-6)
    assert out["sensitivity_ke_x_gt"]["rows"][0][1] is not None
    assert find_bare_numbers(out) == []
    gordon = reverse_dcf.reverse_dcf(150, 10, ke=0.12, n=0, f=0, gt=0.05, base_label="t")
    assert gordon["implied_terminal_growth"]["value"] == pytest.approx(5)


# ---------------------------------------------------------------- technicals

def synthetic_px(n: int = 300, start: str = "2025-01-01", growth: float = 0.001, value_inr: float = 1e8) -> pd.DataFrame:
    days = pd.bdate_range(start, periods=n)
    close = 100 * (1 + growth) ** np.arange(n)
    df = pd.DataFrame({"date": [d.date() for d in days], "close": close, "open": close, "adj_close": close, "adj_high": close,
                       "adj_low": close, "adj_factor": 1.0, "value_inr": value_inr, "delivery_pct": 50.0})
    df["tr_index"] = df["adj_close"] / df["adj_close"].iloc[0] * 100
    return df


def test_drawdown_and_vol():
    dd, pk, tr = technicals.max_drawdown(np.array([100, 120, 90, 130, 117.0]), list("abcde"))
    assert dd == pytest.approx(-0.25) and (pk, tr) == ("b", "c")  # 120 -> 90
    assert technicals.realised_vol(100 * 1.01 ** np.arange(30)) == pytest.approx(0, abs=1e-12)


def test_technicals_output():
    px = synthetic_px()
    idx = pd.DataFrame({"date": px["date"], "tri": px["adj_close"] ** 0.5})  # index return = half the log return
    out = technicals.technicals(px, idx)
    close = px["adj_close"].to_numpy()
    assert out["trend"]["dma_50"]["value"] == pytest.approx(close[-50:].mean())
    assert out["range_52w"]["pct_below_high"]["value"] == pytest.approx(0)
    assert out["liquidity"]["adv_20d"]["value"] == pytest.approx(10)  # 1e8 INR = 10 crore
    rs = out["relative_strength"]["3m"]
    s, i = rs["stock_total_return"]["value"] / 100, rs["index_total_return"]["value"] / 100
    assert (1 + i) == pytest.approx(math.sqrt(1 + s))
    assert "warnings" not in out and find_bare_numbers(out) == []


# ---------------------------------------------------------------- base rates

def synthetic_index(jump_on_break: float = 1.0) -> pd.DataFrame:
    days = pd.date_range("2012-01-01", "2024-12-31", freq="D")
    t = (days - days[0]).days / 365.25
    tri = 100 * np.exp(0.10 * t)
    pe = 20 + 5 * np.sin(np.arange(len(days)) / 200)
    pe = np.where(days.date >= base_rates.PE_BREAK_DATE, pe / jump_on_break, pe)
    return pd.DataFrame({"date": days.date, "tri": tri, "pe": pe, "pb": 3.0, "div_yield": 1.2})


def test_base_rates_constant_growth():
    out = base_rates.base_rates(synthetic_index(), horizon_months=12, buckets=4, pe_method="raw")
    u = out["unconditional"]
    # TRI grows 10% a year continuously: every 12-month forward return is e^0.1 - 1 = 10.52%
    assert u["mean"]["value"] == pytest.approx((math.exp(0.1) - 1) * 100, abs=0.05)
    assert u["share_positive_pct"]["value"] == 100
    n = u["n_obs"]["value"]
    assert u["n_independent"]["value"] == pytest.approx(round(n / 12, 1))
    b = out["by_pe_bucket"]
    assert sum(r[b["columns"].index("n_obs")] for r in b["rows"]) == n
    assert any("Overlapping windows" in w for w in out["warnings"])
    assert find_bare_numbers(out) == []


def test_base_rates_splices_pe_break():
    df = synthetic_index(jump_on_break=1.2)
    assert base_rates.implied_earnings_jump(df, base_rates.PE_BREAK_DATE) == pytest.approx(1.2, rel=1e-3)
    adj, jump = base_rates.adjust_pe(df, "spliced")
    before = adj[adj["date"] < base_rates.PE_BREAK_DATE]["pe"].iloc[-1]
    raw_before = df[df["date"] < base_rates.PE_BREAK_DATE]["pe"].iloc[-1]
    assert before == pytest.approx(raw_before / jump)


# ---------------------------------------------------------------- portfolio

def test_portfolio_beta_hhi_liquidity_and_mandate():
    n = 300
    rng = np.random.default_rng(0)
    m = rng.normal(0, 0.01, n)
    days = [d.date() for d in pd.bdate_range("2025-01-01", periods=n)]
    idx = pd.DataFrame({"date": days, "tri": 100 * np.cumprod(1 + m)})

    def stock(mult: float) -> pd.DataFrame:
        tr = 100 * np.cumprod(1 + mult * m)
        return pd.DataFrame({"date": days, "tr_index": tr, "adj_close": tr, "close": tr, "open": tr, "adj_factor": 1.0, "value_inr": 1e7})
    prices = {"AAA": stock(2.0), "BBB": stock(1.0)}
    meta = {"AAA": {"industry": "IT", "index_memberships": ["NIFTY 100"]}, "BBB": {"industry": "IT", "index_memberships": []}}
    mandate = {"max_positions": 10, "max_weight": 0.05, "max_sector_weight": 0.35, "allow_cash": True,
               "liquidity": {"min_adv_inr_crore": 5, "max_days_to_exit": 3, "participation_rate": 0.15}}
    out = portfolio.analyse({"AAA": 0.1, "BBB": 0.1}, prices, meta, idx, capital_inr=1e7, mandate=mandate)
    pos = {r[0]: dict(zip(out["positions"]["columns"], r)) for r in out["positions"]["rows"]}
    assert pos["AAA"]["beta_1y"] == pytest.approx(2.0) and pos["BBB"]["beta_1y"] == pytest.approx(1.0)
    assert pos["AAA"]["days_to_exit_at_10pct_adv"] == pytest.approx(1.0)  # 1e6 INR / (0.1 x 1e7)
    assert pos["AAA"]["size"].startswith("large") and pos["BBB"]["size"].startswith("other")
    assert out["correlation"]["rows"][0][2] == pytest.approx(1.0)
    assert out["cash"]["value"] == pytest.approx(80)
    assert out["concentration"]["hhi"]["value"] == pytest.approx(0.5) and out["concentration"]["effective_n"]["value"] == pytest.approx(2)
    assert out["stress"]["beta_implied_portfolio_move"]["value"] == pytest.approx(-6)  # (0.1x2 + 0.1x1) x -20%
    checks = {c["check"]: c for c in out["mandate_checks"]}
    assert checks["max_weight"]["breach"] is True and checks["max_positions"]["breach"] is False
    assert checks["min_adv_inr_crore"]["breach"] is True  # ADV 1 crore < 5
    assert checks["max_weight"]["limit"]["source"] == "config/mandate.yaml"
    assert find_bare_numbers(out) == []
    run_m = portfolio.analyse({"AAA": 0.1}, prices, meta, idx, capital_inr=1e5, mandate=mandate, mandate_source="runs/r/mandate.yaml")
    assert {c["check"]: c for c in run_m["mandate_checks"]}["max_weight"]["limit"]["source"] == "runs/r/mandate.yaml"


def test_parse_holdings():
    assert portfolio.parse_holdings("reliance:0.1, CAMS:0.05", None) == {"RELIANCE": 0.1, "CAMS": 0.05}
    with pytest.raises(InputError):
        portfolio.parse_holdings("RELIANCE=0.1", None)


# ---------------------------------------------------------------- costs and tax

def E(value, since="2000-01-01", **kw):
    return [{"value": value, "effective_from": since, "source_url": "https://example.test", "verified": "2026-11-08", **kw}]


COSTS = {
    "charges": {
        "brokerage_delivery": E(0.0, cap_inr=20.0, floor_inr=None),
        "stt_delivery_buy": E(0.001), "stt_delivery_sell": E(0.001),
        "exchange_txn_nse": E(0.0000297), "exchange_txn_bse": E(0.0000375), "sebi_fee": E(0.000001),
        "stamp_duty_delivery_buy": E(0.00015), "dp_charge_per_sell": E(15.34),
        "gst": E(0.18, base=["brokerage", "exchange_txn", "sebi_fee"]),
    },
    "tax": {
        "stcg_equity_rate": E(0.15) + E(0.20, "2024-07-23"), "ltcg_equity_rate": E(0.10) + E(0.125, "2024-07-23"),
        "ltcg_exemption_inr_per_fy": E(100000.0) + E(125000.0, "2024-04-01"), "ltcg_min_holding_months": E(12),
        "cess": E(0.04), "surcharge_cap_cg": E(0.15),
    },
}


def test_round_trip_costs_hand_checked():
    out = costs_tax.round_trip(100000, 120000, D(2024, 1, 1), D(2025, 6, 1), cfg=COSTS)
    out.pop("_stt_inr")
    # buy: STT 100, exchange 2.97, SEBI 0.10, stamp 15, GST 0.18 x 3.07 = 0.5526 -> 118.6226
    assert out["buy"]["total"]["value"] == pytest.approx(118.6226)
    # sell: STT 120, exchange 3.564, SEBI 0.12, DP 15.34, GST 0.18 x 3.684 = 0.66312 -> 139.68712
    assert out["sell"]["total"]["value"] == pytest.approx(139.68712)
    assert out["total"]["value"] == pytest.approx(258.30972)
    assert find_bare_numbers(out) == []


def test_capital_gains_tax_hand_checked():
    t = costs_tax.trade(100000, 120000, D(2024, 1, 1), D(2025, 6, 1), cfg=COSTS)
    tax = t["tax"]
    assert tax["kind"] == "LTCG"
    gain = 20000 - (258.30972 - 220)  # STT (100 + 120) is not deductible
    assert tax["gain"]["value"] == pytest.approx(gain)
    assert tax["tax_without_exemption"]["value"] == pytest.approx(gain * 0.125 * 1.04)
    assert tax["tax_with_exemption"]["value"] == 0  # gain below the 1.25 lakh exemption
    st = costs_tax.trade(100000, 120000, D(2025, 1, 1), D(2025, 6, 1), cfg=COSTS)["tax"]
    assert st["kind"] == "STCG" and st["tax_with_exemption"]["value"] == pytest.approx(st["gain"]["value"] * 0.20 * 1.04)
    old = costs_tax.capital_gains_tax(100, 200, D(2024, 1, 1), D(2024, 7, 22), cfg=COSTS)
    assert old["tax_without_exemption"]["value"] == pytest.approx(100 * 0.15 * 1.04)  # before 23-Jul-2024
    capped = costs_tax.capital_gains_tax(100, 200, D(2025, 1, 1), D(2025, 6, 1), surcharge=0.25, cfg=COSTS)
    assert capped["tax_without_exemption"]["value"] == pytest.approx(100 * 0.20 * 1.15 * 1.04)
    loss = costs_tax.capital_gains_tax(200, 100, D(2025, 1, 1), D(2025, 6, 1), cfg=COSTS)
    assert loss["tax_with_exemption"]["value"] == 0 and "set off" in loss["notes"]
    assert find_bare_numbers(t) == []


def test_long_term_needs_more_than_twelve_months():
    assert not costs_tax.is_long_term(D(2024, 1, 15), D(2025, 1, 15))
    assert costs_tax.is_long_term(D(2024, 1, 15), D(2025, 1, 16))


def test_costs_yaml_is_sourced():
    cfg = costs_tax.load_costs()
    for section in ("charges", "tax"):
        for name in COSTS[section]:
            entries = cfg[section][name]
            assert entries, name
            for e in entries:
                assert e.get("source_url", "").startswith("http"), name
                assert e.get("verified") and e.get("effective_from"), name
    text = costs_tax.COSTS_PATH.read_text()
    assert "brokerage_delivery:  # DEFAULT - confirm" in text
    costs_tax.entry(cfg, "tax", "stcg_equity_rate", D(2026, 11, 8))


def test_every_cli_help_renders():
    from tools.cli import build_parser
    parser = build_parser()
    groups = next(a for a in parser._actions if a.dest == "group").choices
    assert {"data", "compute", "ledger"} <= set(groups)

    def walk(p):
        p.format_help()  # a stray % in a help string (here or in a child's help) raises
        for a in p._actions:
            if isinstance(a.choices, dict):
                for child in a.choices.values():
                    walk(child)
    walk(parser)
