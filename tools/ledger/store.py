"""Append-only JSONL ledger.

Records are never rewritten. A correction is a new record
`{"record_type": "correction", "corrects": <record_id>, "changes": {...}}`;
readers apply corrections in file order on top of the original. Numbers inside
records are provenance numbers, so a record can be quoted as-is.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..common.cache import REPO_ROOT
from ..common.errors import InputError
from ..common.provenance import now_iso

DEFAULT_DIR = REPO_ROOT / "ledger"
PICKS_FILE = "picks.jsonl"


def ledger_path(ledger_dir: str | Path | None) -> Path:
    d = Path(ledger_dir) if ledger_dir else DEFAULT_DIR
    if not d.is_absolute():
        d = REPO_ROOT / d
    return d / PICKS_FILE


def read_all(ledger_dir: str | Path | None) -> list[dict]:
    p = ledger_path(ledger_dir)
    if not p.exists():
        return []
    out = []
    for i, line in enumerate(p.read_text().splitlines(), start=1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise InputError(f"{p}:{i} is not valid JSON ({e}); the ledger is append-only, fix by hand only with care") from e
    return out


def append(records: list[dict], ledger_dir: str | Path | None) -> Path:
    """Append records (one JSON object per line). Refuses duplicate record ids."""
    p = ledger_path(ledger_dir)
    existing = {r.get("record_id") for r in read_all(ledger_dir)}
    dup = [r["record_id"] for r in records if r["record_id"] in existing]
    if dup:
        raise InputError(f"record ids already in the ledger: {dup}; append a correction instead")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    return p


def _apply(rec: dict, changes: dict[str, Any]) -> dict:
    out = json.loads(json.dumps(rec))
    for path, value in changes.items():
        node = out
        keys = path.split(".")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
    return out


def current(records: list[dict]) -> list[dict]:
    """Records with corrections applied (corrections themselves dropped, listed under `corrections`)."""
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for r in records:
        if r.get("record_type") == "correction":
            target = r.get("corrects")
            if target not in by_id:
                raise InputError(f"correction {r.get('record_id')} refers to unknown record {target}")
            fixed = _apply(by_id[target], r.get("changes", {}))
            fixed.setdefault("corrections", []).append({"record_id": r["record_id"], "at": r.get("at"), "reason": r.get("reason")})
            by_id[target] = fixed
            continue
        by_id[r["record_id"]] = r
        order.append(r["record_id"])
    return [by_id[i] for i in order]


def run_records(run_id: str, ledger_dir: str | Path | None) -> tuple[dict, list[dict], list[dict]]:
    """(run record, pick records, other records such as reviews) for one run, corrections applied."""
    recs = [r for r in current(read_all(ledger_dir)) if r.get("run_id") == run_id]
    run = next((r for r in recs if r["record_type"] == "run"), None)
    if run is None:
        raise InputError(f"run {run_id} is not frozen in {ledger_path(ledger_dir)}")
    picks = [r for r in recs if r["record_type"] == "pick"]
    other = [r for r in recs if r["record_type"] not in ("run", "pick")]
    return run, picks, other


def correction(target: str, changes: dict[str, Any], reason: str, ledger_dir: str | Path | None) -> dict:
    recs = read_all(ledger_dir)
    if not any(r.get("record_id") == target for r in recs):
        raise InputError(f"no record {target} in the ledger")
    if not reason:
        raise InputError("a correction needs a reason")
    n = sum(1 for r in recs if r.get("corrects") == target) + 1
    rec = {"record_type": "correction", "record_id": f"{target}:correction{n}", "run_id": next(r.get("run_id") for r in recs if r.get("record_id") == target),
           "corrects": target, "changes": changes, "reason": reason, "at": now_iso()}
    append([rec], ledger_dir)
    return rec
