"""Polite HTTP client.

Rules this module enforces (see CLAUDE.md):
* an honest User-Agent naming this tool (override with ER_USER_AGENT in .env);
* per-host minimum interval between requests;
* robots.txt respected;
* 401/403 are treated as "blocked": no retries with altered headers, no cookie
  games, no CAPTCHA handling. The caller marks the source unavailable.
"""
from __future__ import annotations

import os
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

DEFAULT_UA = "equity-research-tool/0.1 (personal non-commercial research)"

HOST_MIN_INTERVAL = {
    "www.nseindia.com": 1.5,
    "nsearchives.nseindia.com": 1.0,
    "www.niftyindices.com": 1.5,
    "www.rbi.org.in": 2.0,
    "rbi.org.in": 2.0,
}
DEFAULT_MIN_INTERVAL = 1.0


class SourceError(Exception):
    status = "error"


class SourceBlocked(SourceError):
    """Refused (401/403/robots). Do not work around it."""
    status = "blocked"


class SourceUnavailable(SourceError):
    """Timeouts, 5xx, 429 after backoff, network errors."""
    status = "unavailable"


class SourceNotFound(SourceError):
    status = "not_found"


@dataclass
class Response:
    status: int
    content: bytes
    content_type: str
    url: str


Transport = Callable[[str, str, dict | None, Any, float, dict], Response]


def _requests_transport(method: str, url: str, params: dict | None, json_body: Any, timeout: float, headers: dict) -> Response:
    r = requests.request(method, url, params=params, data=json_body, timeout=timeout, headers=headers, allow_redirects=True)
    return Response(r.status_code, r.content, r.headers.get("content-type", ""), r.url)


class PoliteHttp:
    def __init__(self, transport: Transport | None = None):
        self.transport = transport or _requests_transport
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    @property
    def user_agent(self) -> str:
        return os.environ.get("ER_USER_AGENT") or DEFAULT_UA

    def _wait(self, host: str) -> None:
        gap = HOST_MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL)
        last = self._last.get(host)
        if last is not None:
            delta = time.monotonic() - last
            if delta < gap:
                time.sleep(gap - delta)
        self._last[host] = time.monotonic()

    def _robots_ok(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self._robots:
            rp: urllib.robotparser.RobotFileParser | None = None
            try:
                self._wait(host)
                r = self.transport("GET", f"{parts.scheme}://{host}/robots.txt", None, None, 20, {"User-Agent": self.user_agent})
                if r.status == 200 and "text/plain" in r.content_type:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(r.content.decode("utf-8", "ignore").splitlines())
                elif r.status in (401, 403) and "text/plain" in r.content_type:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.disallow_all = True
                # 404 or an HTML error page: no robots rules published
            except requests.RequestException:
                rp = None
            self._robots[host] = rp
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: str | None = None,
        timeout: float = 45,
        content_type: str | None = None,
        retries: int = 2,
    ) -> Response:
        if not self._robots_ok(url):
            raise SourceBlocked(f"robots.txt disallows {url}")
        headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if content_type:
            headers["Content-Type"] = content_type
        host = urlsplit(url).netloc
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            self._wait(host)
            try:
                r = self.transport(method, url, params, json_body, timeout, headers)
            except requests.RequestException as e:  # timeouts, DNS, resets
                last_err = e
                time.sleep(2 * (attempt + 1))
                continue
            if r.status in (401, 403):
                raise SourceBlocked(f"HTTP {r.status} from {host}; treated as blocked (no workaround attempted)")
            if r.status == 404:
                raise SourceNotFound(f"HTTP 404 for {url}")
            if r.status == 429:
                last_err = SourceUnavailable(f"HTTP 429 rate limited by {host}")
                time.sleep(10 * (attempt + 1))
                continue
            if r.status >= 500:
                last_err = SourceUnavailable(f"HTTP {r.status} from {host}")
                time.sleep(3 * (attempt + 1))
                continue
            if r.status >= 300:
                raise SourceUnavailable(f"HTTP {r.status} from {url}")
            return r
        raise SourceUnavailable(f"{host}: {last_err}")


_client: PoliteHttp | None = None


def client() -> PoliteHttp:
    global _client
    if _client is None:
        _client = PoliteHttp()
    return _client


def set_transport(transport: Transport | None) -> None:
    """Tests swap in a recorded-fixture transport; None restores real HTTP."""
    global _client
    _client = PoliteHttp(transport)
