"""Store filed PDFs and their page-numbered text so dossiers can cite pages.

Text lives at data/cache/<ISIN>/docs/<doc_id>.pages.json as a list of
{"page": n, "text": "..."} with 1-based page numbers matching the PDF viewer.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .cache import CACHE_ROOT, fetch, url_key


def doc_id_for(url: str) -> str:
    return url_key(url)


def _pages_path(isin: str, doc_id: str) -> Path:
    return CACHE_ROOT / isin / "docs" / f"{doc_id}.pages.json"


def download_and_extract(url: str, isin: str) -> dict:
    """Download (cached forever: filed documents don't change) and extract page text."""
    doc_id = doc_id_for(url)
    ext = Path(url.split("?")[0]).suffix.lower() or ".bin"
    f = fetch(url, key=f"{isin}/docs/{doc_id}{ext}", ttl_hours=None, timeout=120)
    pages_path = _pages_path(isin, doc_id)
    if not pages_path.exists():
        pages = extract_pages(f.content, ext)
        pages_path.write_text(json.dumps({"url": url, "retrieved_at": f.retrieved_at, "pages": pages}))
    data = json.loads(pages_path.read_text())
    n_chars = sum(len(p["text"]) for p in data["pages"])
    empty = sum(1 for p in data["pages"] if len(p["text"].strip()) < 20)
    return {
        "doc_id": doc_id, "url": url, "local_path": str(f.path), "text_path": str(pages_path),
        "n_pages": len(data["pages"]), "n_chars": n_chars, "near_empty_pages": empty,
        "retrieved_at": data["retrieved_at"],
        "warning": "many pages have no text layer (scanned?); OCR not attempted" if data["pages"] and empty > 0.5 * len(data["pages"]) else None,
    }


def extract_pages(content: bytes, ext: str) -> list[dict]:
    if ext == ".pdf" or content[:4] == b"%PDF":
        import pymupdf
        with pymupdf.open(stream=content, filetype="pdf") as doc:
            return [{"page": i + 1, "text": p.get_text("text")} for i, p in enumerate(doc)]
    if ext in (".html", ".htm", ".xml"):
        text = re.sub(r"<[^>]+>", " ", content.decode("utf-8", "ignore"))
        return [{"page": 1, "text": re.sub(r"\s+", " ", text)}]
    return [{"page": 1, "text": content.decode("utf-8", "ignore")}]


def load_pages(isin: str, doc_id: str) -> dict:
    p = _pages_path(isin, doc_id)
    if not p.exists():
        raise FileNotFoundError(f"doc {doc_id} not downloaded for {isin}; run `data filings get` first")
    return json.loads(p.read_text())


def search(isin: str, doc_id: str, pattern: str, *, context: int = 250, max_hits: int = 40) -> dict:
    data = load_pages(isin, doc_id)
    rx = re.compile(pattern, re.I)
    hits = []
    for p in data["pages"]:
        for m in rx.finditer(p["text"]):
            s, e = max(0, m.start() - context), min(len(p["text"]), m.end() + context)
            hits.append({"page": p["page"], "match": m.group(0), "snippet": re.sub(r"\s+", " ", p["text"][s:e])})
            if len(hits) >= max_hits:
                break
        if len(hits) >= max_hits:
            break
    pages_hit = sorted({h["page"] for h in hits})
    return {"doc_id": doc_id, "url": data["url"], "pattern": pattern, "pages_hit": pages_hit, "hits": hits, "truncated": len(hits) >= max_hits}


def pages(isin: str, doc_id: str, first: int, last: int, *, max_chars: int = 60000) -> dict:
    data = load_pages(isin, doc_id)
    out, total = [], 0
    for p in data["pages"]:
        if first <= p["page"] <= last:
            t = p["text"]
            if total + len(t) > max_chars:
                out.append({"page": p["page"], "text": t[: max(0, max_chars - total)], "truncated": True})
                break
            out.append({"page": p["page"], "text": t})
            total += len(t)
    return {"doc_id": doc_id, "url": data["url"], "pages": out}
