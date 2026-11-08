"""Shared test setup: no network, a throwaway cache, and a recorded-fixture transport.

Every test runs with a transport that fails on any request, so a test that
forgets to install fixtures cannot silently hit a live source. The download
cache points at a temp directory, so tests never read or write data/cache.

The fixture files are real NSE responses and filings, recorded on this machine
by tests/fixtures/record.py and kept out of git; tests that need a missing one
skip with the command that records it.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from tools.common import http
from tools.common.cache import settings

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RECORD_HINT = "real fixtures not recorded: run `uv run python tests/fixtures/record.py --fetch`"

# modules that bind CACHE_ROOT at import time
_CACHE_ROOT_MODULES = ("tools.common.cache", "tools.common.pdftext", "tools.data.prices", "tools.data.index",
                       "tools.data.macro", "tools.smoke")


def require_fixtures(*names: str) -> None:
    """Skip the calling test unless these recorded fixture files exist."""
    missing = sorted(n for n in names if not (FIXTURES / n).exists())
    if missing:
        pytest.skip(f"{RECORD_HINT} (missing {', '.join(missing)})")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """A test that reads FIXTURES / name directly skips, rather than errors, when that file is not recorded."""
    try:
        return (yield)
    except FileNotFoundError as ex:
        if ex.filename and Path(ex.filename).parent == FIXTURES:
            pytest.skip(f"{RECORD_HINT} (missing {Path(ex.filename).name})")
        raise


def _refuse(method, url, params, body, timeout, headers):
    raise AssertionError(f"unit test tried to reach the network: {method} {url}")


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    for name in _CACHE_ROOT_MODULES:
        monkeypatch.setattr(importlib.import_module(name), "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(http, "HOST_MIN_INTERVAL", {})
    monkeypatch.setattr(http, "DEFAULT_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(settings, "refresh", False)
    http.set_transport(_refuse)
    yield tmp_path / "cache"
    http.set_transport(None)


@pytest.fixture
def routes():
    """Install a transport that answers URLs containing a key with that fixture file.

    Usage: routes({"corporates-corporateActions": "nse_ca_CAMS.json", "bhavcopy": 404})
    robots.txt always answers 404 (no rules); unknown URLs fail the test; a fixture
    file that is not recorded skips it.
    """
    def install(table: dict[str, str | int | bytes]):
        require_fixtures(*(t for t in table.values() if isinstance(t, str)))

        def transport(method, url, params, body, timeout, headers):
            if url.endswith("/robots.txt"):
                return http.Response(404, b"", "text/html", url)
            for key, target in table.items():
                if key in url:
                    if isinstance(target, int):
                        return http.Response(target, b"", "text/html", url)
                    content = target if isinstance(target, bytes) else (FIXTURES / target).read_bytes()
                    ctype = "application/xml" if url.endswith(".xml") else "application/json"
                    return http.Response(200, content, ctype, url)
            raise AssertionError(f"no fixture route for {url}")
        http.set_transport(transport)
    return install
