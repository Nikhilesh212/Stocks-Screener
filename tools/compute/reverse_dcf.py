"""`compute reverse_dcf`: the growth rate today's price implies.

Model (per share, cash flows at year ends):
  years 1..N         CF_t = CF_{t-1} x (1 + g)
  years N+1..N+F     growth fades linearly from g towards gt: g_k = g - (g - gt) x k / (F + 1)
  terminal           TV = CF_{N+F} x (1 + gt) / (ke - gt), discounted from year N+F
  value              sum CF_t / (1 + ke)^t + TV / (1 + ke)^(N+F)
With N = F = 0 this is the Gordon model CF0 x (1 + gt) / (ke - gt); g is then not
identifiable, so the tool solves for the implied terminal growth instead.

It answers "what has to go right to justify today's price?", not "what is it worth".
"""
from __future__ import annotations

from ..common.errors import InputError
from ..common.provenance import derived, missing, num
from ..common.units import INR, PCT, RATIO
from ._util import records_table

G_LO, G_HI = -0.9, 2.0


def cash_flows(cf0: float, g: float, n: int, f: int, gt: float) -> list[float]:
    flows, cf = [], cf0
    for _ in range(n):
        cf *= 1 + g
        flows.append(cf)
    for k in range(1, f + 1):
        cf *= 1 + (g - (g - gt) * k / (f + 1))
        flows.append(cf)
    return flows


def value(cf0: float, g: float, ke: float, n: int, f: int, gt: float) -> dict:
    """Present value per share and its parts."""
    if ke <= gt:
        raise InputError(f"cost of equity ({ke}) must exceed terminal growth ({gt})")
    flows = cash_flows(cf0, g, n, f, gt)
    pv_explicit = sum(cf / (1 + ke) ** t for t, cf in enumerate(flows, start=1))
    last = flows[-1] if flows else cf0
    tv = last * (1 + gt) / (ke - gt)
    pv_tv = tv / (1 + ke) ** (n + f)
    return {"value": pv_explicit + pv_tv, "pv_explicit": pv_explicit, "pv_terminal": pv_tv, "final_cf": last}


def solve_growth(price: float, cf0: float, ke: float, n: int, f: int, gt: float, tol: float = 1e-9) -> tuple[float | None, str | None]:
    """Bisection for the g that makes value == price. Value rises with g when CF0 > 0."""
    if cf0 <= 0:
        raise InputError("base cash flow must be positive (a reverse DCF on negative earnings/FCF is undefined)")
    if price <= 0:
        raise InputError("price must be positive")
    if n + f == 0:
        raise InputError("N = F = 0 leaves no growth period; use implied_terminal_growth")
    lo, hi = G_LO, G_HI
    v_lo, v_hi = value(cf0, lo, ke, n, f, gt)["value"], value(cf0, hi, ke, n, f, gt)["value"]
    if price < v_lo:
        return None, f"price below the value at g = {G_LO:.0%}: implied growth is below the search range"
    if price > v_hi:
        return None, f"price above the value at g = {G_HI:.0%}: implied growth is above the search range"
    for _ in range(200):
        mid = (lo + hi) / 2
        if value(cf0, mid, ke, n, f, gt)["value"] < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2, None


def implied_terminal_growth(price: float, cf0: float, ke: float) -> float:
    """Gordon: price = CF0 (1 + gt) / (ke - gt)  =>  gt = (price x ke - CF0) / (price + CF0)."""
    return (price * ke - cf0) / (price + cf0)


def reverse_dcf(price: float, cf0: float, *, ke: float, n: int, f: int, gt: float, base_label: str,
                ke_grid: list[float] | None = None, n_grid: list[int] | None = None, gt_grid: list[float] | None = None) -> dict:
    params = {"price": num(price, INR, source="caller or cached close"), "base_cash_flow_per_share": num(cf0, "INR/share", source="caller or cache", notes=base_label),
              "cost_of_equity": num(ke * 100, PCT, source="caller"), "high_growth_years": num(n, "years", source="caller"),
              "fade_years": num(f, "years", source="caller"), "terminal_growth": num(gt * 100, PCT, source="caller")}
    if cf0 <= 0:
        raise InputError("base cash flow must be positive (a reverse DCF on negative earnings/FCF is undefined)")
    if ke <= gt:
        raise InputError(f"cost of equity ({ke}) must exceed terminal growth ({gt})")
    out: dict = {"parameters": params, "model": __doc__.split("It answers")[0].strip()}
    if n + f == 0:
        gt_imp = implied_terminal_growth(price, cf0, ke)
        out["implied_terminal_growth"] = derived(gt_imp * 100, PCT, formula="(price x ke - CF0) / (price + CF0)", inputs=params)
        return out
    g, why = solve_growth(price, cf0, ke, n, f, gt)
    if g is None:
        out["implied_growth"] = missing(why, PCT, source="computed")
    else:
        parts = value(cf0, g, ke, n, f, gt)
        out["implied_growth"] = derived(g * 100, PCT, formula=f"g such that DCF value = price (bisection on [{G_LO}, {G_HI}])", inputs=params)
        out["what_has_to_go_right"] = {
            "cash_flow_multiple_by_end_of_high_growth": derived((1 + g) ** n, RATIO, formula=f"(1 + g)^{n}"),
            "cash_flow_multiple_by_end_of_fade": derived(parts["final_cf"] / cf0, RATIO, formula=f"CF_{n + f} / CF0"),
            "terminal_value_share_of_price": derived(parts["pv_terminal"] / parts["value"] * 100, PCT, formula="PV(terminal) / value"),
        }
    ke_grid = ke_grid or [round(ke + d, 4) for d in (-0.02, -0.01, 0.0, 0.01, 0.02)]
    n_grid = n_grid or sorted({max(1, n - 5), n, n + 5})
    gt_grid = gt_grid or [round(gt + d, 4) for d in (-0.01, 0.0, 0.01)]
    out["sensitivity_ke_x_n"] = _grid(price, cf0, ke_grid, "high_growth_years", n_grid, lambda k, x: (k, x, f, gt))
    out["sensitivity_ke_x_gt"] = _grid(price, cf0, ke_grid, "terminal_growth_pct", [x * 100 for x in gt_grid],
                                       lambda k, x: (k, n, f, x / 100))
    return out


def _grid(price: float, cf0: float, ke_grid: list[float], col_name: str, col_vals: list, args) -> dict:
    """Implied g (%) for each cost of equity (rows) x parameter (columns); null where undefined or out of range."""
    rows, why = [], []
    for k in ke_grid:
        row = [k * 100]
        for x in col_vals:
            ke, n, f, gt = args(k, x)
            if ke <= gt or n + f == 0:
                row.append(None)
                why.append(f"ke {ke:.2%}, {col_name} {x}: undefined (ke <= gt or no growth years)")
                continue
            g, reason = solve_growth(price, cf0, ke, n, f, gt)
            row.append(g * 100 if g is not None else None)
            if reason:
                why.append(f"ke {ke:.2%}, {col_name} {x}: {reason}")
        rows.append(row)
    cols = ["cost_of_equity_pct", *[f"{col_name}={x:g}" for x in col_vals]]
    t = records_table([dict(zip(cols, r)) for r in rows], cols, {c: PCT for c in cols}, source="computed",
                      notes="cells = implied high-growth rate g in %; " + ("; ".join(why) if why else "all cells solved"))
    return t


def cmd_reverse_dcf(args) -> dict:
    price, cf0, label, ident = args.price, args.base_value, args.base_label or "caller-supplied base", None
    if args.query:
        from .valuation import _load, fundamentals_at
        ident, fin, px, actions, _ = _load(args.query, args.basis)
        f = fundamentals_at(fin, actions or [], None, bool(fin.get("is_bank_format")))
        if price is None:
            price = float(px.dropna(subset=["close"])["close"].iloc[-1])
        if cf0 is None:
            sh = f.get("shares_today_basis_crore")
            if args.base == "fcf":
                cf0 = f["fcf"] / sh if f.get("fcf") is not None and sh else None
                label = f"FCF per share, {f.get('fcf_period')} (cfo - capex) / shares on today's basis"
            else:
                cf0 = f["ttm_pat_owners"] / sh if f.get("ttm_pat_owners") is not None and sh else None
                label = f"TTM EPS (pat_owners / shares on today's basis), {', '.join(f.get('ttm_quarters', []))}"
    if price is None or cf0 is None:
        raise InputError("need --price and --base-value, or a symbol whose cache gives them")
    out = reverse_dcf(price, cf0, ke=args.ke, n=args.years, f=args.fade, gt=args.terminal_growth, base_label=label)
    return {"identity": ident, **out} if ident else out


def register(sub, leaf) -> None:
    p = leaf(sub, "reverse_dcf", "growth rate implied by today's price (high growth N years, linear fade F years, Gordon terminal) + sensitivity grids")
    p.add_argument("query", nargs="?", help="NSE symbol or ISIN: price and base cash flow from the cache (or pass --price/--base-value)")
    p.add_argument("--price", type=float, help="price per share, INR")
    p.add_argument("--base-value", type=float, help="base cash flow per share CF0, INR")
    p.add_argument("--base-label", help="what --base-value is (e.g. 'FY26 FCF/share')")
    p.add_argument("--base", choices=("fcf", "eps"), default="fcf", help="with a symbol: FCF/share (latest FY) or TTM EPS")
    p.add_argument("--basis", choices=("consolidated", "standalone"), default="consolidated")
    p.add_argument("--ke", type=float, required=True, help="cost of equity as a fraction, e.g. 0.12")
    p.add_argument("--years", type=int, default=10, help="high-growth years N")
    p.add_argument("--fade", type=int, default=5, help="fade years F")
    p.add_argument("--terminal-growth", type=float, default=0.05, help="terminal growth as a fraction (nominal INR)")
    p.set_defaults(func=cmd_reverse_dcf)
