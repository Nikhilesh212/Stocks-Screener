"""Ledger against a stub market with hand-computed returns.

Freeze 2026-01-07, entry at the 2026-01-08 close. From 2026-06-01:
AAA total return +20% (no dividend), BBB price +5% and total return +8%
(dividends), CCC -20%, DDD has no prices, Nifty 500 TRI +10%.
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from tools.common.errors import InputError
from tools.common.provenance import find_bare_numbers
from tools.ledger import evaluate, freeze, review, store

D = dt.date
STEP = D(2026, 6, 1)


def series(before: float, after: float) -> list[float]:
    return [before if d < STEP else after for d in DAYS]


DAYS = [d.date() for d in pd.bdate_range("2025-12-01", "2026-12-31")]


class StubMarket:
    notes: list[str] = []
    PX = {"AAA": (100, 120, 100, 120), "BBB": (100, 105, 100, 108), "CCC": (100, 80, 100, 80)}  # close before/after, TR before/after

    def resolve(self, s):
        return {"isin": f"INE{s}01010", "symbol": s, "legal_name": f"{s} Ltd"}

    def prices(self, isin, since):
        sym = isin[3:6]
        if sym not in self.PX:
            return pd.DataFrame(columns=["date", "close", "adj_close", "tr_index"])
        c0, c1, t0, t1 = self.PX[sym]
        return pd.DataFrame({"date": DAYS, "close": series(c0, c1), "adj_close": series(c0, c1), "tr_index": series(t0, t1)})

    def index_tri(self, name="NIFTY 500"):
        return pd.DataFrame({"date": DAYS, "tri": series(1000, 1100)})

    def announcements(self, symbol, start, end):
        return [{"date": "15-Feb-2026", "category": "Outcome of Board Meeting", "text": f"{symbol} results", "url": "https://example.test/a.pdf"}]


ZERO_COSTS = {
    "charges": {k: [{"value": 0.0, "effective_from": "2000-01-01", "source_url": "https://x.test", "verified": "2026-11-08",
                     **({"base": ["brokerage"]} if k == "gst" else {})}]
                for k in ("brokerage_delivery", "stt_delivery_buy", "stt_delivery_sell", "exchange_txn_nse", "exchange_txn_bse", "sebi_fee",
                          "stamp_duty_delivery_buy", "dp_charge_per_sell", "gst")},
    "tax": {k: [{"value": v, "effective_from": "2000-01-01", "source_url": "https://x.test", "verified": "2026-11-08"}]
            for k, v in (("stcg_equity_rate", 0.20), ("ltcg_equity_rate", 0.125), ("ltcg_exemption_inr_per_fy", 125000.0),
                         ("ltcg_min_holding_months", 12), ("cess", 0.04), ("surcharge_cap_cg", 0.15))},
}

SCEN = [{"name": "bull", "probability": 0.5, "return_pct": 25, "return_range_pct": [15, None]},
        {"name": "base", "probability": 0.3, "return_pct": 8, "return_range_pct": [0, 15]},
        {"name": "bear", "probability": 0.2, "return_pct": -15, "return_range_pct": [None, 0]}]


def freeze_input(**kw) -> dict:
    inp = {"model_id": "claude-opus-5-5", "horizon_months": 6,
           "picks": [{"symbol": "AAA", "weight": 0.5, "thesis": "One. Two. Three.", "scenarios": SCEN, "p_beat_benchmark": 0.7,
                      "kill_criteria": ["margin below 10%"], "review_dates": ["2026-02-15"]},
                     {"symbol": "BBB", "weight": 0.3, "thesis": "One. Two. Three.",
                      "scenarios": [{"name": "base", "probability": 1.0, "return_pct": 10}], "p_beat_benchmark": 0.6,
                      "kill_criteria": ["promoter pledge above 20%"], "review_dates": []}],
           "cohorts": {"B": ["AAA", "BBB", "CCC"], "C": ["CCC"], "D": ["AAA", "BBB", "CCC", "DDD"]}}
    inp.update(kw)
    return inp


@pytest.fixture
def frozen(tmp_path):
    ldir = tmp_path / "ledger"
    path = tmp_path / "freeze_input.json"
    path.write_text(json.dumps(freeze_input()))
    out = freeze.freeze("run1", input_path=str(path), approval="user in chat (test)", ledger_dir=str(ldir), market=StubMarket(),
                        frozen_at="2026-01-07T15:00:00+05:30")
    return ldir, out


def test_freeze_records(frozen):
    ldir, out = frozen
    assert out["n_picks"] == 2 and find_bare_numbers(out) == []
    run = out["run"]
    assert run["horizon_end"] == "2026-07-07"
    assert run["cohorts"]["A"]["cash"]["value"] == pytest.approx(0.2)
    assert [m["symbol"] for m in run["cohorts"]["D"]["members"]] == ["AAA", "BBB", "CCC", "DDD"]
    assert out["picks"][0]["reference_price"]["value"] == 100 and out["picks"][0]["benchmark_at_freeze"]["value"] == 1000
    lines = (ldir / "picks.jsonl").read_text().splitlines()
    assert len(lines) == 3
    with pytest.raises(InputError, match="already frozen"):
        p = ldir.parent / "freeze_input.json"
        freeze.freeze("run1", input_path=str(p), approval="again", ledger_dir=str(ldir), market=StubMarket())


def test_freeze_reads_the_run_mandate(tmp_path):
    (tmp_path / "mandate.yaml").write_text("horizon_months: 9\ncapital_inr: 100000\n")
    inp = freeze_input()
    del inp["horizon_months"]
    recs, _ = freeze.build_records("run1", inp, StubMarket(), approval="test", run_dir=tmp_path, frozen_at="2026-01-07T15:00:00+05:30")
    run = recs[0]
    assert run["capital_inr"]["value"] == 100000 and run["capital_inr"]["source"] == "runs/run1/mandate.yaml"
    assert run["horizon_months"]["value"] == 9 and run["horizon_end"] == "2026-10-07"


def test_freeze_validation(tmp_path):
    with pytest.raises(InputError, match="approval"):
        freeze.freeze("r", input_path=None, approval=" ", ledger_dir=str(tmp_path), market=StubMarket())
    bad = freeze_input()
    bad["picks"][0]["scenarios"] = [{"name": "x", "probability": 0.5}]
    bad["picks"][1]["weight"] = 0.6
    errs = freeze.validate(bad)
    assert any("sum to 0.500" in e for e in errs) and any("> 1" in e for e in errs)
    assert freeze.validate(freeze_input(picks=[])) == []  # cash/index is a valid outcome


def test_mark_cohorts(frozen):
    ldir, _ = frozen
    out = evaluate.mark("run1", ledger_dir=str(ldir), market=StubMarket(), as_of=D(2026, 7, 1))
    c = {k: v["total_return"]["value"] for k, v in out["cohorts"].items()}
    assert out["entry_date"] == "2026-01-08"
    assert c["A"] == pytest.approx(12.4)  # 0.5 x 20 + 0.3 x 8, cash 0
    assert c["B"] == pytest.approx((20 + 8 - 20) / 3)
    assert c["C"] == pytest.approx(-20)
    assert c["D"] == pytest.approx((20 + 8 - 20) / 3)  # DDD has no prices: excluded and reported
    assert out["cohorts"]["D"]["n_with_returns"]["value"] == 3 and "DDD" in out["cohorts"]["D"]["note"]
    assert c["E"] == pytest.approx(10)
    assert out["comparisons"]["C_minus_A"]["value"] == pytest.approx(-32.4)
    assert out["comparisons"]["A_minus_E"]["value"] == pytest.approx(2.4)
    assert find_bare_numbers(out) == []


def test_postmortem_net_tax_and_calibration(frozen):
    ldir, _ = frozen
    with pytest.raises(InputError, match="--force"):
        evaluate.postmortem("run1", ledger_dir=str(ldir), market=StubMarket(), as_of=D(2026, 7, 1), cfg=ZERO_COSTS)
    out = evaluate.postmortem("run1", ledger_dir=str(ldir), market=StubMarket(), as_of=D(2026, 7, 10), cfg=ZERO_COSTS)
    assert not out["interim"] and out["capital"]["value"] == 1_000_000  # notional: capital_inr not set
    rows = {r[0]: dict(zip(out["picks"]["columns"], r)) for r in out["picks"]["rows"]}
    # AAA: 5 lakh -> 6 lakh, STCG 1 lakh x 20% x 1.04 = 20,800; net 79,200 = 15.84%
    assert rows["AAA"]["kind"] == "STCG" and rows["AAA"]["cg_tax_no_exemption_inr"] == pytest.approx(20800)
    assert rows["AAA"]["net_return_pct"] == pytest.approx(15.84)
    # BBB: 3 lakh, price +5% -> gain 15,000, tax 3,120; dividends 3 lakh x (8% - 5%) = 9,000; net 20,880 = 6.96%
    assert rows["BBB"]["dividends_inr"] == pytest.approx(9000) and rows["BBB"]["net_return_pct"] == pytest.approx(6.96)
    net = out["portfolio_A"]["net"]
    # all short-term: tax 1.15 lakh x 20% x 1.04 = 23,920 both ways; (1,24,000 - 23,920) / 10 lakh = 10.008%
    assert net["with_exemption"]["net_return"]["value"] == pytest.approx(10.008)
    assert net["without_exemption"]["cg_tax"]["value"] == pytest.approx(23920)
    cal = out["calibration"]
    assert cal["brier_p_beat_benchmark"]["value"] == pytest.approx(((0.7 - 1) ** 2 + (0.6 - 0) ** 2) / 2)  # AAA beat, BBB did not
    assert cal["brier_scenarios"]["value"] == pytest.approx(0.25 + 0.09 + 0.04)  # AAA realised "bull"
    assert find_bare_numbers(out) == []
    md = (ldir / "postmortems" / "run1.md").read_text()
    assert "Post-mortem: run1" in md and "### AAA" in md
    with pytest.raises(InputError, match="already recorded"):
        evaluate.postmortem("run1", ledger_dir=str(ldir), market=StubMarket(), as_of=D(2026, 7, 10), cfg=ZERO_COSTS)


def test_portfolio_tax_nets_losses_and_one_exemption():
    pt = evaluate.portfolio_tax([{"kind": "STCG", "gain": -50000}, {"kind": "LTCG", "gain": 300000}], ZERO_COSTS, D(2026, 7, 1))
    assert pt["net_ltcg"] == 250000  # short-term loss set off against long-term gain
    assert pt["tax_with_exemption"] == pytest.approx((250000 - 125000) * 0.125 * 1.04)
    assert pt["tax_without_exemption"] == pytest.approx(250000 * 0.125 * 1.04)


def test_review_window_and_corrections(frozen):
    ldir, _ = frozen
    out = review.review("run1", ledger_dir=str(ldir), market=StubMarket(), as_of=D(2026, 3, 1))
    assert out["window"] == {"from": "2026-01-07", "to": "2026-03-01"}
    assert out["picks"][0]["kill_criteria"] == ["margin below 10%"] and out["picks"][0]["review_dates_in_window"] == ["2026-02-15"]
    nxt = review.review("run1", ledger_dir=str(ldir), market=StubMarket(), as_of=D(2026, 4, 1))
    assert nxt["window"]["from"] == "2026-03-02"
    store.correction("run1:INEAAA01010", {"kill_criteria": ["margin below 8%"]}, "typo at freeze", str(ldir))
    _, picks, _ = store.run_records("run1", str(ldir))
    aaa = next(p for p in picks if p["symbol"] == "AAA")
    assert aaa["kill_criteria"] == ["margin below 8%"] and aaa["corrections"][0]["reason"] == "typo at freeze"
    raw = [json.loads(x) for x in (ldir / "picks.jsonl").read_text().splitlines()]
    assert next(r for r in raw if r["record_id"] == "run1:INEAAA01010")["kill_criteria"] == ["margin below 10%"]  # original untouched


def test_discover_cohorts_reads_run_files(tmp_path):
    """B from dossiers (conviction files never read), C from red-team "killed", D from candidates."""
    (tmp_path / "dossiers").mkdir()
    (tmp_path / "redteam").mkdir()
    for s in ("AAA", "BBB"):
        (tmp_path / "dossiers" / f"{s}.json").write_text(json.dumps({"identity": {"isin": f"INE{s}01010", "nse_symbol": s}}))
    (tmp_path / "dossiers" / "ZZZ.conviction.json").write_text(json.dumps({"symbol": "ZZZ", "p_beat_benchmark": 0.6}))
    (tmp_path / "redteam" / "AAA.json").write_text(json.dumps({"identity": {"nse_symbol": "AAA"}, "verdict": "killed"}))
    (tmp_path / "redteam" / "BBB.json").write_text(json.dumps({"identity": {"nse_symbol": "BBB"}, "verdict": "weakened"}))
    (tmp_path / "candidates.json").write_text(json.dumps({"candidates": [{"symbol": "AAA"}, {"symbol": "bbb"}, {"symbol": "CCC"}]}))
    cohorts, notes = freeze.discover_cohorts(tmp_path)
    assert cohorts == {"B": ["AAA", "BBB"], "C": ["AAA"], "D": ["AAA", "BBB", "CCC"]} and notes == []
