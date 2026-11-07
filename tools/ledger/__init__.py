"""Ledger group: freeze approved picks, mark cohorts, review kill criteria, post-mortem. Append-only JSONL."""
from __future__ import annotations

import datetime as dt
import json


def _common(p) -> None:
    p.add_argument("run_id")
    p.add_argument("--ledger-dir", default="ledger", help="ledger folder (picks.jsonl); use ledger/test for dry runs")


def _market(args):
    from .market import LiveMarket
    return LiveMarket(fetch=not getattr(args, "no_fetch", False))


def _date(s: str | None) -> dt.date | None:
    from ..common.errors import InputError
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError as e:
        raise InputError(f"bad date {s!r}: use YYYY-MM-DD") from e


def cmd_freeze(args) -> dict:
    from .freeze import freeze
    return freeze(args.run_id, input_path=args.input, approval=args.approved, ledger_dir=args.ledger_dir, market=_market(args))


def cmd_mark(args) -> dict:
    from .evaluate import mark
    return mark(args.run_id, ledger_dir=args.ledger_dir, market=_market(args), as_of=_date(args.as_of))


def cmd_review(args) -> dict:
    from .review import review
    return review(args.run_id, ledger_dir=args.ledger_dir, market=_market(args), as_of=_date(args.as_of))


def cmd_postmortem(args) -> dict:
    from .evaluate import postmortem
    return postmortem(args.run_id, ledger_dir=args.ledger_dir, market=_market(args), force=args.force, surcharge=args.surcharge,
                      slab_rate=args.slab_rate, as_of=_date(args.as_of))


def cmd_correct(args) -> dict:
    from ..common.errors import InputError
    from .store import correction
    changes = {}
    for s in args.set or []:
        k, _, v = s.partition("=")
        if not k or not _:
            raise InputError(f"--set needs FIELD=JSON, got {s!r}")
        try:
            changes[k] = json.loads(v)
        except json.JSONDecodeError:
            changes[k] = v
    return {"correction": correction(args.record_id, changes, args.reason, args.ledger_dir)}


def register(sub, leaf) -> None:
    p = leaf(sub, "freeze", "append approved picks + cohorts A-E from runs/<run_id>/freeze_input.json (only after explicit user approval)")
    _common(p)
    p.add_argument("--approved", required=True, help="who approved and when, e.g. 'user in chat 2026-11-08 14:05'")
    p.add_argument("--input", help="freeze input JSON (default runs/<run_id>/freeze_input.json)")
    p.add_argument("--no-fetch", action="store_true", help="use cached prices only")
    p.set_defaults(func=cmd_freeze)

    p = leaf(sub, "mark", "current total return of every cohort (A-E) and pick vs Nifty 500 TRI since next-session entry (gross)")
    _common(p)
    p.add_argument("--as-of", help="YYYY-MM-DD (default today)")
    p.add_argument("--no-fetch", action="store_true", help="use cached prices only")
    p.set_defaults(func=cmd_mark)

    p = leaf(sub, "review", "announcements since the last review next to each pick's kill criteria (Claude judges)")
    _common(p)
    p.add_argument("--as-of", help="YYYY-MM-DD (default today)")
    p.set_defaults(func=cmd_review)

    p = leaf(sub, "postmortem", "net-of-cost-and-tax excess returns, Brier score, calibration, cohort comparison; writes ledger/postmortems/<run_id>.md")
    _common(p)
    p.add_argument("--force", action="store_true", help="allow before the horizon ends (labelled interim)")
    p.add_argument("--surcharge", type=float, default=0.0, help="surcharge fraction (capped at the capital-gains cap)")
    p.add_argument("--slab-rate", type=float, help="marginal slab rate for dividend tax, as a fraction")
    p.add_argument("--as-of", help="YYYY-MM-DD (default today)")
    p.add_argument("--no-fetch", action="store_true", help="use cached prices only")
    p.set_defaults(func=cmd_postmortem)

    p = leaf(sub, "correct", "append a correction to a ledger record (the original is never edited)")
    p.add_argument("record_id")
    p.add_argument("--set", action="append", help="FIELD=JSON (dotted paths allowed), repeatable")
    p.add_argument("--reason", required=True)
    p.add_argument("--ledger-dir", default="ledger")
    p.set_defaults(func=cmd_correct)
