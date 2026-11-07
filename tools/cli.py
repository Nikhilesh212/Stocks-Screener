"""CLI entry: python -m tools <group> <command> [args] --json

Output is always JSON on stdout (the --json flag is accepted for clarity);
logs and progress go to stderr. Exit code 0 = ok, 2 = source/entity error.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from .common.cache import REPO_ROOT, settings
from .common.entity import ResolutionError
from .common.errors import InputError
from .common.http import SourceError
from .common.provenance import now_iso


def _leaf_factory(common: argparse.ArgumentParser):
    def leaf(sub, name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, description=help_text, parents=[common])
    return leaf


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="emit JSON (always on; accepted for clarity)")
    common.add_argument("--refresh", action="store_true", help="bypass the disk cache for this call")
    common.add_argument("--out", help="also write the JSON result to this file")
    leaf = _leaf_factory(common)

    parser = argparse.ArgumentParser(prog="python -m tools", description=(
        "Indian equity research tools. Code fetches facts and computes numbers; it never ranks or recommends. "
        "Every number carries provenance {value, unit, period, as_of, source, ...}."))
    groups = parser.add_subparsers(dest="group", required=True, metavar="{data,compute,ledger,smoke}")

    from .data import register as register_data
    g = groups.add_parser("data", help="fetch facts: resolve, prices, index, filings, financials, shareholding, macro, events")
    register_data(g.add_subparsers(dest="command", required=True), leaf)

    try:
        from .compute import register as register_compute
        g = groups.add_parser("compute", help="pure computations: calc, ratios, valuation, reverse_dcf, technicals, base_rates, portfolio, costs_tax")
        register_compute(g.add_subparsers(dest="command", required=True), leaf)
    except ImportError:
        pass
    try:
        from .ledger import register as register_ledger
        g = groups.add_parser("ledger", help="freeze, mark, review, postmortem")
        register_ledger(g.add_subparsers(dest="command", required=True), leaf)
    except ImportError:
        pass

    from .smoke import register as register_smoke
    register_smoke(groups, leaf)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    settings.refresh = bool(getattr(args, "refresh", False))
    command = " ".join(x for x in (args.group, getattr(args, "command", None)) if x)
    out: dict = {"command": command, "generated_at": now_iso()}
    code = 0
    try:
        result = args.func(args)
        out["status"] = "ok"
        out.update(result if isinstance(result, dict) else {"result": result})
    except ResolutionError as e:
        out.update({"status": "entity_error", "error": str(e), "resolution": e.result})
        code = 2
    except SourceError as e:
        out.update({"status": e.status, "error": str(e)})
        code = 2
    except FileNotFoundError as e:
        out.update({"status": "missing_input", "error": str(e)})
        code = 2
    except InputError as e:
        out.update({"status": "input_error", "error": str(e)})
        code = 2
    text = json.dumps(out, indent=1, ensure_ascii=False, default=str)
    if getattr(args, "out", None):
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    print(text)
    return code
