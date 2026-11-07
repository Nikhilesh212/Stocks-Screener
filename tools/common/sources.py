"""URL builders and fetch helpers for the sources verified in config/sources.yaml."""
from __future__ import annotations

import datetime as dt
import io
import json
from urllib.parse import urlencode

import pandas as pd

from .cache import Fetched, fetch
from .http import SourceNotFound, SourceError
from .provenance import today_ist

NSE_API = "https://www.nseindia.com/api"
NSE_ARCH = "https://nsearchives.nseindia.com"
NIFTY_BACK = "https://www.niftyindices.com/BackPage"
BSE_BHAV = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV"

TTL_LIST = 12.0     # announcement / filing lists
TTL_MASTER = 24.0   # equity master, index constituents
TTL_LIVE = 2.0      # surveillance lists, flows


def nse_api(path: str, params: dict, *, key: str, ttl_hours: float | None) -> tuple[object, Fetched]:
    url = f"{NSE_API}/{path}?{urlencode(params, safe=',[]')}" if params else f"{NSE_API}/{path}"
    f = fetch(url, key=key, ttl_hours=ttl_hours)
    try:
        return f.json(), f
    except json.JSONDecodeError as e:
        raise SourceError(f"NSE API {path} returned non-JSON ({len(f.content)} bytes)") from e


def niftyindices_post(endpoint: str, cinfo: dict, *, key: str, ttl_hours: float | None) -> tuple[list, Fetched]:
    """niftyindices.com BackPage endpoints take {"cinfo": "<single-quoted dict string>"}."""
    inner = "{" + ",".join(f"'{k}':'{v}'" for k, v in cinfo.items()) + "}"
    body = json.dumps({"cinfo": inner})
    f = fetch(f"{NIFTY_BACK}/{endpoint}", key=key, ttl_hours=ttl_hours, method="POST",
              json_body=body, content_type="application/json; charset=utf-8")
    data = f.json()
    if isinstance(data, dict) and "d" in data:
        data = json.loads(data["d"]) if isinstance(data["d"], str) else data["d"]
    return data, f


def read_csv_bytes(content: bytes, **kw) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(content), skipinitialspace=True, **kw)
    df.columns = [str(c).strip() for c in df.columns]
    for c in df.columns:
        if df[c].dtype == object or str(df[c].dtype).startswith("str"):
            df[c] = df[c].astype("string").str.strip()
    return df


def recent_dates(n: int = 10, end: dt.date | None = None) -> list[dt.date]:
    end = end or today_ist()
    return [end - dt.timedelta(days=i) for i in range(n)]


def latest_daily_file(url_for_date, key_for_date, *, lookback: int = 10, end: dt.date | None = None) -> tuple[dt.date, Fetched]:
    """Walk back from `end` until a dated archive file exists (skips weekends/holidays)."""
    last_err: Exception | None = None
    for d in recent_dates(lookback, end):
        if d.weekday() >= 5:
            continue
        try:
            # today's file may still appear later; past-dated files are immutable
            ttl = 6.0 if d == today_ist() else None
            return d, fetch(url_for_date(d), key=key_for_date(d), ttl_hours=ttl)
        except SourceNotFound as e:
            last_err = e
            continue
    raise SourceNotFound(f"no file found in last {lookback} days: {last_err}")


def bhavcopy_url(d: dt.date) -> str:
    return f"{NSE_ARCH}/products/content/sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"


def bhavcopy_key(d: dt.date) -> str:
    return f"_market/nse_bhavcopy/{d.isoformat()}.csv"


def ind_close_url(d: dt.date) -> str:
    return f"{NSE_ARCH}/content/indices/ind_close_all_{d.strftime('%d%m%Y')}.csv"


def ind_close_key(d: dt.date) -> str:
    return f"_market/nse_ind_close/{d.isoformat()}.csv"
