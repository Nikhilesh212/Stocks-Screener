"""`compute costs_tax`: round-trip costs and capital-gains tax for NSE/BSE cash-market delivery trades.

Every rate comes from `config/costs.yaml`, where each item is a list of entries
with `effective_from`, `source_url` and `verified`; the entry in force on the
trade date applies (buy-side items on the buy date, sell-side items and tax on
the sell date). Brokerage is a default (no broker chosen) and is labelled so.

Tax model (resident individual, STT-paid listed equity): held more than 12
months = long-term. Gain = sale value - purchase value - transfer costs, where
STT is not deductible (s.48 of the 1961 Act). LTCG is shown with and without
the annual exemption, because the exemption is shared across all of a person's
equity LTCG in the financial year. Surcharge is a parameter; cess applies on
tax plus surcharge. Losses: no tax; set-off rules are noted, not applied.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ..common.cache import REPO_ROOT
from ..common.errors import InputError
from ..common.provenance import derived, missing, num
from ..common.units import INR, PCT

COSTS_PATH = REPO_ROOT / "config" / "costs.yaml"


def load_costs(path: Path = COSTS_PATH) -> dict:
    if not path.exists():
        raise InputError(f"{path} missing; it holds every cost and tax rate with its source")
    return yaml.safe_load(path.read_text())


def entry(cfg: dict, section: str, name: str, on: dt.date) -> dict:
    """The rate entry in force on `on` (latest effective_from <= on)."""
    items = (cfg.get(section) or {}).get(name)
    if not items:
        raise InputError(f"costs.yaml has no {section}.{name}")
    live = [e for e in items if dt.date.fromisoformat(str(e["effective_from"])) <= on]
    if not live:
        raise InputError(f"costs.yaml {section}.{name}: no entry in force on {on}")
    return max(live, key=lambda e: str(e["effective_from"]))


def _rate_num(e: dict, value: float, unit: str, label: str) -> dict:
    return num(value, unit, source=label, source_url=e.get("source_url"), as_of=str(e.get("verified")),
               notes=" ".join(x for x in (f"effective from {e['effective_from']}", e.get("notes") or "") if x))


def brokerage(e: dict, value: float) -> float:
    fee = value * float(e["value"])
    if e.get("cap_inr") is not None:
        fee = min(fee, float(e["cap_inr"]))
    if e.get("floor_inr") is not None:
        fee = max(fee, float(e["floor_inr"]))
    return fee


def side_costs(cfg: dict, side: str, value: float, on: dt.date, exchange: str = "NSE") -> dict[str, tuple[float, dict]]:
    """INR cost lines for one side of a delivery trade: {item: (amount, rate entry)}."""
    if side not in ("buy", "sell"):
        raise InputError("side must be buy or sell")
    ex = exchange.upper()
    if ex not in ("NSE", "BSE"):
        raise InputError("exchange must be NSE or BSE")
    lines: dict[str, tuple[float, dict]] = {}
    e = entry(cfg, "charges", "brokerage_delivery", on)
    lines["brokerage"] = (brokerage(e, value), e)
    e = entry(cfg, "charges", f"stt_delivery_{side}", on)
    lines["stt"] = (value * float(e["value"]), e)
    e = entry(cfg, "charges", f"exchange_txn_{ex.lower()}", on)
    lines["exchange_txn"] = (value * float(e["value"]), e)
    e = entry(cfg, "charges", "sebi_fee", on)
    lines["sebi_fee"] = (value * float(e["value"]), e)
    if ex == "NSE" and (cfg.get("charges") or {}).get("ipft_nse"):
        e = entry(cfg, "charges", "ipft_nse", on)
        lines["ipft"] = (value * float(e["value"]), e)
    if side == "buy":
        e = entry(cfg, "charges", "stamp_duty_delivery_buy", on)
        lines["stamp_duty"] = (value * float(e["value"]), e)
    else:
        e = entry(cfg, "charges", "dp_charge_per_sell", on)
        lines["dp_charge"] = (float(e["value"]), e)
    e = entry(cfg, "charges", "gst", on)
    base = sum(lines[k][0] for k in e.get("base", []) if k in lines)
    lines["gst"] = (base * float(e["value"]), e)
    return lines


def round_trip(buy_value: float, sell_value: float, buy_date: dt.date, sell_date: dt.date, *, exchange: str = "NSE",
               cfg: dict | None = None) -> dict:
    """Both sides' cost lines in INR, totals, and total as % of the buy value."""
    cfg = cfg or load_costs()
    out: dict[str, Any] = {}
    total, stt = 0.0, 0.0
    for side, value, on in (("buy", buy_value, buy_date), ("sell", sell_value, sell_date)):
        lines = side_costs(cfg, side, value, on, exchange)
        block = {}
        for item, (amt, e) in lines.items():
            block[item] = derived(amt, INR, formula=_formula(item, e, value), as_of=on.isoformat(),
                                  inputs={"rate": _rate_num(e, float(e["value"]), e.get("unit", "fraction"), f"config/costs.yaml charges ({item})")},
                                  notes="user-confirmed default (no broker chosen)" if item == "brokerage" else None)
        side_total = sum(a for a, _ in lines.values())
        block["total"] = derived(side_total, INR, formula=f"sum of {side} lines")
        out[side] = block
        total += side_total
        stt += lines["stt"][0]
    out["total"] = derived(total, INR, formula="buy total + sell total")
    out["total_pct_of_buy_value"] = derived(total / buy_value * 100 if buy_value else None, PCT, formula="total / buy_value * 100")
    out["_stt_inr"] = stt  # internal: removed before output, used by the tax function
    return out


def _formula(item: str, e: dict, value: float) -> str:
    if item == "brokerage":
        return f"min(value x {e['value']}, cap {e.get('cap_inr')}) floored at {e.get('floor_inr')} per order"
    if item == "dp_charge":
        return "flat INR per scrip per sell day"
    if item == "gst":
        return f"{e['value']} x ({' + '.join(e.get('base', []))})"
    return f"value {value:.2f} x {e['value']}"


def is_long_term(buy_date: dt.date, sell_date: dt.date, months: int = 12) -> bool:
    """Listed equity is long-term if held for more than `months` months."""
    return sell_date > (pd.Timestamp(buy_date) + pd.DateOffset(months=months)).date()


def capital_gains_tax(buy_value: float, sell_value: float, buy_date: dt.date, sell_date: dt.date, *, deductible_costs: float = 0.0,
                      surcharge: float = 0.0, exemption_remaining: float | None = None, cfg: dict | None = None) -> dict:
    """Tax on one lot. `deductible_costs`: transfer costs excluding STT. `exemption_remaining`: LTCG exemption still unused this FY
    (None = the full annual amount)."""
    cfg = cfg or load_costs()
    if sell_date < buy_date:
        raise InputError("sell date before buy date")
    months = int(entry(cfg, "tax", "ltcg_min_holding_months", sell_date)["value"])
    lt = is_long_term(buy_date, sell_date, months)
    gain = sell_value - buy_value - deductible_costs
    kind = "LTCG" if lt else "STCG"
    rate_e = entry(cfg, "tax", "ltcg_equity_rate" if lt else "stcg_equity_rate", sell_date)
    cess_e = entry(cfg, "tax", "cess", sell_date)
    cap_e = entry(cfg, "tax", "surcharge_cap_cg", sell_date)
    sur = min(surcharge, float(cap_e["value"]))
    rate = float(rate_e["value"])
    cess = float(cess_e["value"])
    out: dict[str, Any] = {
        "kind": kind,
        "holding_days": num((sell_date - buy_date).days, "days", source="computed"),
        "gain": derived(gain, INR, formula="sell_value - buy_value - transfer costs excl. STT"),
        "rate": _rate_num(rate_e, rate * 100, PCT, f"config/costs.yaml tax ({kind})"),
        "cess": _rate_num(cess_e, cess * 100, PCT, "config/costs.yaml tax (cess)"),
        "surcharge_applied": num(sur * 100, PCT, source="caller (capped by config/costs.yaml surcharge_cap_cg)",
                                 notes=f"requested {surcharge * 100:g}%, cap {float(cap_e['value']) * 100:g}% on these gains"),
    }
    mult = rate * (1 + sur) * (1 + cess)
    if gain <= 0:
        zero = derived(0.0, INR, formula="no tax on a loss")
        out["tax_without_exemption"] = out["tax_with_exemption"] = zero
        out["notes"] = ("loss: short-term losses set off against STCG or LTCG, long-term losses only against LTCG; "
                        "carry forward 8 years if the return is filed on time. Not applied here.")
        return out
    out["tax_without_exemption"] = derived(gain * mult, INR, formula="gain x rate x (1 + surcharge) x (1 + cess)")
    if lt:
        ex_e = entry(cfg, "tax", "ltcg_exemption_inr_per_fy", sell_date)
        ex = float(ex_e["value"]) if exemption_remaining is None else max(0.0, min(exemption_remaining, float(ex_e["value"])))
        taxable = max(0.0, gain - ex)
        out["exemption_used"] = derived(min(gain, ex), INR, formula="min(gain, exemption available)",
                                        inputs={"annual_exemption": _rate_num(ex_e, float(ex_e["value"]), INR, "config/costs.yaml tax (LTCG exemption)")})
        out["tax_with_exemption"] = derived(taxable * mult, INR, formula="max(0, gain - exemption) x rate x (1 + surcharge) x (1 + cess)",
                                            notes="the exemption is per person per FY across all equity LTCG; with other LTCG it may already be used")
    else:
        out["tax_with_exemption"] = derived(gain * mult, INR, formula="STCG has no annual exemption",
                                            notes="residents below the basic exemption limit can absorb STCG against it; not modelled")
    return out


def trade(buy_value: float, sell_value: float, buy_date: dt.date, sell_date: dt.date, *, exchange: str = "NSE", surcharge: float = 0.0,
          exemption_remaining: float | None = None, cfg: dict | None = None) -> dict:
    """Round-trip costs, then tax on the gain net of deductible costs, then net proceeds both ways."""
    cfg = cfg or load_costs()
    costs = round_trip(buy_value, sell_value, buy_date, sell_date, exchange=exchange, cfg=cfg)
    stt = costs.pop("_stt_inr")
    deductible = costs["total"]["value"] - stt
    tax = capital_gains_tax(buy_value, sell_value, buy_date, sell_date, deductible_costs=deductible, surcharge=surcharge,
                            exemption_remaining=exemption_remaining, cfg=cfg)
    net = {}
    for k in ("with_exemption", "without_exemption"):
        t = tax[f"tax_{k}"]["value"]
        pnl = sell_value - buy_value - costs["total"]["value"] - t
        net[k] = {"net_pnl": derived(pnl, INR, formula="sell - buy - costs - tax"),
                  "net_return_pct": derived(pnl / buy_value * 100 if buy_value else None, PCT, formula="net_pnl / buy_value * 100")}
    return {"costs": costs, "tax": tax, "net": net,
            "rates_file": str(COSTS_PATH.relative_to(REPO_ROOT)), "rates_verified": cfg.get("meta", {}).get("verified")}


def _d(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(s)
    except ValueError as ex:
        raise InputError(f"bad date {s!r}: use YYYY-MM-DD") from ex


def cmd_costs_tax(args) -> dict:
    sell_value = args.sell_value if args.sell_value is not None else args.buy_value
    out = trade(args.buy_value, sell_value, _d(args.buy_date), _d(args.sell_date), exchange=args.exchange, surcharge=args.surcharge,
                exemption_remaining=args.exemption_remaining)
    out["inputs"] = {"buy_value": num(args.buy_value, INR, source="caller"), "sell_value": num(sell_value, INR, source="caller")}
    return out


def register(sub, leaf) -> None:
    p = leaf(sub, "costs_tax", "round-trip delivery costs (brokerage, STT, exchange, SEBI, stamp, GST, DP) and capital-gains tax by holding period")
    p.add_argument("--buy-value", type=float, required=True, help="purchase value, INR")
    p.add_argument("--sell-value", type=float, help="sale value, INR (default: same as buy, i.e. costs only)")
    p.add_argument("--buy-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--sell-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--exchange", default="NSE", choices=("NSE", "BSE"))
    p.add_argument("--surcharge", type=float, default=0.0, help="surcharge rate as a fraction (capped at the capital-gains cap)")
    p.add_argument("--exemption-remaining", type=float, help="LTCG exemption still unused this FY, INR (default: the full amount)")
    p.set_defaults(func=cmd_costs_tax)
