"""Disk cache keyed by ISIN (or _market), source and period.

Layout: data/cache/<ISIN or _market>/<source>/<name>
Each file has a sidecar <name>.meta.json with url and retrieved_at.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .http import client
from .provenance import now_iso

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = REPO_ROOT / "data" / "cache"


class Settings:
    refresh: bool = False  # set by --refresh: bypass cache reads, still write


settings = Settings()


@dataclass
class Fetched:
    content: bytes
    url: str
    retrieved_at: str
    from_cache: bool
    path: Path

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8-sig"))

    def text(self) -> str:
        return self.content.decode("utf-8-sig", "replace")


def cache_path(key: str) -> Path:
    p = (CACHE_ROOT / key).resolve()
    if CACHE_ROOT.resolve() not in p.parents:
        raise ValueError(f"cache key escapes cache root: {key}")
    return p


def _meta_path(p: Path) -> Path:
    return p.with_name(p.name + ".meta.json")


# An empty answer for a past-dated key may be a transient upstream glitch, not a
# fact; keep it only this long so a later call asks again.
EMPTY_TTL_HOURS = 6.0
_EMPTY_BODIES = {b"", b"[]", b"{}", b"null", b'""'}


def is_empty_payload(content: bytes) -> bool:
    """True for bodies that carry no records: blank, [], {}, or {"data": []} style wrappers."""
    body = content.strip()
    if body in _EMPTY_BODIES:
        return True
    if len(body) > 512 or not body.startswith(b"{"):
        return False
    try:
        obj = json.loads(body.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(obj, dict) and all(v in (None, [], {}, "", 0) for v in obj.values())


def read_cached(key: str, ttl_hours: float | None) -> Fetched | None:
    p = cache_path(key)
    m = _meta_path(p)
    if settings.refresh or not p.exists() or not m.exists():
        return None
    meta = json.loads(m.read_text())
    content = p.read_bytes()
    ttls = [t for t in (ttl_hours, meta.get("ttl_hours")) if t is not None]
    if is_empty_payload(content):  # also covers entries cached before this rule existed
        ttls.append(EMPTY_TTL_HOURS)
    if ttls and time.time() - meta.get("epoch", 0) > min(ttls) * 3600:
        return None
    return Fetched(content, meta["url"], meta["retrieved_at"], True, p)


def write_cached(key: str, content: bytes, url: str, *, ttl_hours: float | None = None) -> Fetched:
    """ttl_hours stored here caps the caller's TTL on later reads (used for empty bodies)."""
    p = cache_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    ts = now_iso()
    meta = {"url": url, "retrieved_at": ts, "epoch": time.time()}
    if ttl_hours is not None:
        meta["ttl_hours"] = ttl_hours
    _meta_path(p).write_text(json.dumps(meta))
    return Fetched(content, url, ts, False, p)


def fetch(
    url: str,
    *,
    key: str,
    ttl_hours: float | None,
    method: str = "GET",
    params: dict | None = None,
    json_body: str | None = None,
    content_type: str | None = None,
    timeout: float = 45,
) -> Fetched:
    """Return cached content if fresh, else download politely and cache.

    ttl_hours=None means the content is immutable (past-dated archives, filed
    documents) and is never refetched unless --refresh is given. Empty bodies
    are the exception: they expire after EMPTY_TTL_HOURS whatever the caller asked.
    """
    hit = read_cached(key, ttl_hours)
    if hit:
        return hit
    r = client().request(method, url, params=params, json_body=json_body, content_type=content_type, timeout=timeout)
    full_url = r.url
    if json_body:
        full_url = f"{url} POST {json_body}"
    return write_cached(key, r.content, full_url, ttl_hours=EMPTY_TTL_HOURS if is_empty_payload(r.content) else None)


def url_key(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]
