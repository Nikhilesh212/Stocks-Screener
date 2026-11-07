"""Compute group: pure computations on cached facts. Each module exposes register(sub, leaf)."""


def register(sub, leaf) -> None:
    from . import base_rates, calc, costs_tax, portfolio, ratios, reverse_dcf, technicals, valuation
    for mod in (calc, ratios, valuation, reverse_dcf, technicals, base_rates, portfolio, costs_tax):
        mod.register(sub, leaf)
