"""Data group: fetch facts with provenance. Each module exposes register(sub, leaf)."""


def register(sub, leaf) -> None:
    from . import events, filings, financials, index, macro, prices, resolve, shareholding
    for mod in (resolve, prices, index, filings, financials, shareholding, macro, events):
        mod.register(sub, leaf)
