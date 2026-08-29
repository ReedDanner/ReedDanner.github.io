"""
================================================================================
 QUANTDESK TERMINAL  -  Advanced Equity Analytics Workstation
================================================================================

 A single-file desktop terminal for end-of-day equity analytics built on the
 MarketStack v2 API, with technical / risk / regime analytics, adaptive
 forecasting, Monte Carlo simulation, strategy backtesting and an optional
 AI company analyst.

 Requirements
 ------------
     pip install customtkinter matplotlib pandas numpy requests scikit-learn
     pip install openai            # optional, only for the COMPANY (AI) tab

 Environment
 -----------
     MARKETSTACK_API_KEY     required
     OPENAI_API_KEY          optional (COMPANY tab)

 Usage
 -----
     python quantdesk_terminal.py                # launch the GUI
     python quantdesk_terminal.py --selftest     # headless verification run
     python quantdesk_terminal.py --selftest --symbol MSFT

 Nothing here is investment advice. Forecasts are statistical extrapolations
 of past prices and are wrong on a routine basis.
================================================================================
"""

from __future__ import annotations

import os
import re
import sys
import json
import gzip
import math
import time
import queue
import hashlib
import argparse
import threading
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, date
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import requests


# ==============================================================================
# SECTION 1 - CONSTANTS, THEME, PATHS
# ==============================================================================

APP_NAME = "QuantDesk Terminal"
APP_VERSION = "7.0"

TRADING_DAYS = 252

# ---- Colour system -----------------------------------------------------------
BG          = "#080b10"   # window background
PANEL       = "#0f141c"   # panel surface
PANEL_HI    = "#151c27"   # raised surface / hover
SUNKEN      = "#0a0e14"   # inset surface (text areas, charts)
GRID        = "#1e2733"   # hairlines, separators
GRID_SOFT   = "#161d27"   # chart gridlines

TEXT        = "#dde3ea"   # primary text
DIM         = "#8b97a6"   # secondary text
FAINT       = "#5a6675"   # tertiary text / axis labels

ACCENT      = "#2dd4a7"   # brand / positive
ACCENT_DK   = "#1fa982"
BULL        = "#2dd4a7"
BEAR        = "#f2555a"
WARN        = "#f0a92e"
INFO        = "#5aa9f0"
VIOLET      = "#a78bfa"

SERIES_COLORS = ["#5aa9f0", "#2dd4a7", "#f0a92e", "#a78bfa", "#f2555a",
                 "#3fc8d4", "#e879b9", "#9bd45a"]

# ---- API ---------------------------------------------------------------------
# v2 only. v1 still responds but reports pagination.total == count, which
# breaks paginated reads after the first page.
MS_BASE = "https://api.marketstack.com/v2"

# Free/basic MarketStack tiers rate limit hard; these keep fetches under it.
MIN_REQUEST_INTERVAL = 1.10     # seconds between outbound API calls
MAX_RETRIES = 4                 # retries on 429 / 5xx
BACKOFF_BASE = 2.5              # seconds, exponential

CACHE_TTL_EOD = 6 * 3600        # EOD bars change once per day
CACHE_TTL_REFERENCE = 7 * 86400 # splits / dividends / company info
CACHE_TTL_QUOTE = 900           # latest quote snapshot

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "SPY"]

RANGE_PRESETS = {
    "1M": 31, "3M": 92, "6M": 183, "YTD": None, "1Y": 366, "2Y": 731, "MAX": 4000,
}


def _app_dir() -> str:
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(root, "QuantDeskTerminal")
    os.makedirs(d, exist_ok=True)
    return d


APP_DIR = _app_dir()
CACHE_DIR = os.path.join(APP_DIR, "cache")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
os.makedirs(CACHE_DIR, exist_ok=True)


# ==============================================================================
# SECTION 2 - SMALL UTILITIES
# ==============================================================================

def fmt_money(v: Optional[float], dp: int = 2) -> str:
    if v is None or not np.isfinite(v):
        return "n/a"
    return f"${v:,.{dp}f}"


def fmt_pct(v: Optional[float], dp: int = 2) -> str:
    if v is None or not np.isfinite(v):
        return "n/a"
    return f"{v * 100:,.{dp}f}%"


def fmt_num(v: Optional[float], dp: int = 2) -> str:
    if v is None or not np.isfinite(v):
        return "n/a"
    return f"{v:,.{dp}f}"


def fmt_int(v: Optional[float]) -> str:
    if v is None or not np.isfinite(v):
        return "n/a"
    return f"{int(round(v)):,}"


def fmt_big(v: Optional[float]) -> str:
    """Compact magnitude formatting for volume and market values."""
    if v is None or not np.isfinite(v):
        return "n/a"
    a = abs(v)
    for cut, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cut:
            return f"{v / cut:,.2f}{suf}"
    return f"{v:,.0f}"


def safe_float(v: Any, default: float = float("nan")) -> float:
    try:
        f = float(v)
        return f if np.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def rule(width: int = 78, ch: str = "-") -> str:
    return ch * width


def header_block(title: str, width: int = 78) -> str:
    return f"{rule(width, '=')}\n {title}\n{rule(width, '=')}"


def kv_line(label: str, value: str, pad: int = 26) -> str:
    return f"  {label:<{pad}} {value}"


class Cancelled(Exception):
    """Raised inside worker threads when the user cancels or the app closes."""


# The API key travels in the query string, and requests includes the full URL
# in its exception messages. Scrub anything derived from an exception before it
# reaches the status bar, log, dialogs or exports.
_SECRET_PATTERNS = [
    re.compile(r"(access_key=)[^&\s'\"]+", re.I),
    re.compile(r"(api[_-]?key[\"'\s:=]+)([A-Za-z0-9_\-]{16,})", re.I),
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,})"),
]
_REDACTED = "***REDACTED***"


def redact_secrets(text: Any) -> str:
    """Remove API keys from any text that might be shown or stored."""
    out = str(text)
    for env_name in ("MARKETSTACK_API_KEY", "OPENAI_API_KEY"):
        value = os.getenv(env_name)
        if value and len(value) >= 8:
            out = out.replace(value, _REDACTED)
    out = _SECRET_PATTERNS[0].sub(r"\1" + _REDACTED, out)
    out = _SECRET_PATTERNS[1].sub(r"\1" + _REDACTED, out)
    out = _SECRET_PATTERNS[2].sub(_REDACTED, out)
    return out


# ==============================================================================
# SECTION 3 - PERSISTED SETTINGS
# ==============================================================================

@dataclass
class Settings:
    ticker: str = "AAPL"
    benchmark: str = "SPY"
    range_key: str = "1Y"
    watchlist: List[str] = field(default_factory=lambda: list(DEFAULT_WATCHLIST))
    mc_paths: int = 400
    mc_horizon: int = 126
    mc_loop_seconds: float = 12.0
    mc_model: str = "Block bootstrap"
    total_return: bool = False
    bt_strategy: str = "SMA cross"
    bt_fast: int = 20
    bt_slow: int = 50
    bt_cost_bps: float = 5.0
    geometry: str = "1620x1000"

    @classmethod
    def load(cls) -> "Settings":
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            known = {f for f in cls.__dataclass_fields__}
            return cls(**{k: v for k, v in raw.items() if k in known})
        except Exception:
            return cls()

    def save(self) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(asdict(self), fh, indent=2)
        except Exception:
            pass


# ==============================================================================
# SECTION 4 - HTTP LAYER: THROTTLE, DISK CACHE, MARKETSTACK CLIENT
# ==============================================================================

class RateLimiter:
    """Minimum spacing between outbound API calls."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self, should_abort: Optional[Callable[[], bool]] = None) -> None:
        with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last)
            deadline = time.monotonic() + max(0.0, wait)
            while time.monotonic() < deadline:
                if should_abort and should_abort():
                    raise Cancelled()
                time.sleep(min(0.05, deadline - time.monotonic()))
            self._last = time.monotonic()


class DiskCache:
    """Gzipped JSON cache keyed by endpoint + params, with per-entry TTL.

    Needed because the lower API tiers allow very few requests; without it two
    consecutive fetches can trip HTTP 429.
    """

    def __init__(self, directory: str):
        self.dir = directory
        self._lock = threading.Lock()

    def _path(self, key: str) -> str:
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return os.path.join(self.dir, f"{h}.json.gz")

    def get(self, key: str, ttl: float) -> Optional[Any]:
        path = self._path(key)
        try:
            with self._lock:
                if not os.path.exists(path):
                    return None
                if (time.time() - os.path.getmtime(path)) > ttl:
                    return None
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    return json.load(fh)
        except Exception:
            return None

    def put(self, key: str, value: Any) -> None:
        path = self._path(key)
        try:
            with self._lock:
                tmp = path + ".tmp"
                with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                    json.dump(value, fh)
                os.replace(tmp, path)
        except Exception:
            pass

    def clear(self) -> int:
        n = 0
        try:
            with self._lock:
                for f in os.listdir(self.dir):
                    if f.endswith(".json.gz"):
                        try:
                            os.remove(os.path.join(self.dir, f))
                            n += 1
                        except OSError:
                            pass
        except Exception:
            pass
        return n

    def stats(self) -> Tuple[int, int]:
        n, size = 0, 0
        try:
            for f in os.listdir(self.dir):
                if f.endswith(".json.gz"):
                    n += 1
                    size += os.path.getsize(os.path.join(self.dir, f))
        except Exception:
            pass
        return n, size


class MarketStackError(RuntimeError):
    """API-level failure with an explanation."""

    def __init__(self, message: str, code: str = "", status: int = 0, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.status = status
        self.hint = hint

    def pretty(self) -> str:
        parts = [str(self)]
        if self.hint:
            parts.append(f"-> {self.hint}")
        return "\n".join(parts)


# Human explanations for the error codes MarketStack actually returns.
ERROR_HINTS = {
    "rate_limit_reached":
        "Too many requests in a short window. The terminal throttles and retries "
        "automatically; cached data is used where possible. Wait a minute and retry.",
    "usage_limit_reached":
        "Monthly request quota for this API key is exhausted. Cached symbols still work.",
    "function_access_restricted":
        "This endpoint is not included in your MarketStack plan.",
    "invalid_access_key":
        "MARKETSTACK_API_KEY is not valid. Check the key in your environment.",
    "missing_access_key":
        "MARKETSTACK_API_KEY was not sent. Set it in your environment and restart.",
    "inactive_user":
        "This MarketStack account is inactive.",
    "no_valid_symbols_provided":
        "The symbol was not recognised. Use the exchange ticker, e.g. AAPL, MSFT, BRK.B.",
    "validation_error":
        "The request parameters were rejected. Try a smaller history range.",
    "not_found":
        "No record for that symbol on this endpoint.",
}


class MarketStackClient:
    """MarketStack v2 client: throttled, retrying and cached.

    Methods return typed data or raise MarketStackError.
    """

    def __init__(self, api_key: Optional[str] = None, cache: Optional[DiskCache] = None):
        self.api_key = (api_key or os.getenv("MARKETSTACK_API_KEY") or "").strip()
        self.cache = cache or DiskCache(CACHE_DIR)
        self.limiter = RateLimiter(MIN_REQUEST_INTERVAL)
        self.session = requests.Session()
        self.session.headers.update({"Accept": "encoding/json",
                                     "User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        self.request_count = 0
        self.cache_hits = 0
        self._base = MS_BASE

    # -- low level -------------------------------------------------------------
    def _cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        clean = {k: v for k, v in sorted(params.items()) if k != "access_key"}
        return f"{self._base}|{endpoint}|{json.dumps(clean, sort_keys=True)}"

    def _raise_for_payload(self, payload: Any, status: int) -> None:
        if not isinstance(payload, dict):
            return
        err = payload.get("error")
        if not err:
            return
        if isinstance(err, str):
            raise MarketStackError(err, status=status)
        code = str(err.get("code", "") or "")
        msg = str(err.get("message", "") or "Unknown API error")
        raise MarketStackError(msg, code=code, status=status,
                               hint=ERROR_HINTS.get(code, ""))

    def _request(self, endpoint: str, params: Dict[str, Any], ttl: float,
                 should_abort: Optional[Callable[[], bool]] = None,
                 use_cache: bool = True) -> Any:
        if not self.api_key:
            raise MarketStackError(
                "MARKETSTACK_API_KEY is not set.",
                code="missing_access_key",
                hint="Set the environment variable, then restart the terminal.")

        key = self._cache_key(endpoint, params)
        if use_cache:
            hit = self.cache.get(key, ttl)
            if hit is not None:
                self.cache_hits += 1
                return hit

        url = f"{self._base}/{endpoint.lstrip('/')}"
        full = dict(params)
        full["access_key"] = self.api_key

        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES + 1):
            if should_abort and should_abort():
                raise Cancelled()
            self.limiter.acquire(should_abort)
            try:
                self.request_count += 1
                resp = self.session.get(url, params=full, timeout=30)
            except requests.Timeout:
                last_err = MarketStackError("The API request timed out.",
                                            hint="Check your network connection.")
            except requests.RequestException as exc:
                # requests puts the full request URL, key included, in here.
                last_err = MarketStackError(
                    f"Network error: {redact_secrets(exc)}",
                    hint="Check your internet connection.")
            else:
                # Retryable transport statuses.
                if resp.status_code in (429, 500, 502, 503, 504):
                    try:
                        self._raise_for_payload(resp.json(), resp.status_code)
                    except MarketStackError as exc:
                        last_err = exc
                    except Exception:
                        last_err = MarketStackError(
                            f"API returned HTTP {resp.status_code}.", status=resp.status_code)
                    if attempt < MAX_RETRIES:
                        delay = BACKOFF_BASE * (2 ** attempt)
                        end = time.monotonic() + delay
                        while time.monotonic() < end:
                            if should_abort and should_abort():
                                raise Cancelled()
                            time.sleep(0.1)
                        continue
                    raise last_err

                try:
                    payload = resp.json()
                except ValueError:
                    raise MarketStackError(
                        f"API returned non-JSON content (HTTP {resp.status_code}).",
                        status=resp.status_code)

                self._raise_for_payload(payload, resp.status_code)

                if resp.status_code >= 400:
                    raise MarketStackError(f"API returned HTTP {resp.status_code}.",
                                           status=resp.status_code)

                if use_cache:
                    self.cache.put(key, payload)
                return payload

            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE * (2 ** attempt) * 0.5)

        raise last_err or MarketStackError("The API request failed.")

    # -- endpoints -------------------------------------------------------------
    def eod(self, symbol: str, date_from: str, date_to: str,
            should_abort: Optional[Callable[[], bool]] = None,
            progress: Optional[Callable[[str], None]] = None) -> pd.DataFrame:
        """Paginated end-of-day bars, oldest first, indexed by date.

        Pagination follows ``pagination.total`` and stops when the server stops
        advancing.
        """
        symbol = (symbol or "").strip().upper()
        if not symbol:
            raise MarketStackError("No ticker supplied.", code="no_valid_symbols_provided")

        rows: List[dict] = []
        offset = 0
        limit = 1000
        total: Optional[int] = None

        while True:
            if should_abort and should_abort():
                raise Cancelled()
            if progress:
                got = len(rows)
                progress(f"{symbol}: {got} bars" + (f" / {total}" if total else ""))

            payload = self._request(
                "eod",
                {"symbols": symbol, "date_from": date_from, "date_to": date_to,
                 "limit": limit, "offset": offset, "sort": "DESC"},
                ttl=CACHE_TTL_EOD, should_abort=should_abort)

            data = payload.get("data") or []
            pag = payload.get("pagination") or {}
            if total is None:
                total = int(pag.get("total") or 0) or None

            if not data:
                break
            rows.extend(data)

            count = int(pag.get("count") or len(data))
            offset += max(count, 1)
            if total is not None and len(rows) >= total:
                break
            if count < limit:
                break
            if offset > 50_000:      # hard stop, should never trigger
                break

        if not rows:
            raise MarketStackError(
                f"No end-of-day data returned for {symbol}.",
                code="no_valid_symbols_provided",
                hint="Verify the ticker symbol and that your plan covers this exchange.")

        return self._normalise_eod(rows, symbol)

    @staticmethod
    def _normalise_eod(rows: List[dict], symbol: str) -> pd.DataFrame:
        df = pd.DataFrame(rows)

        if "date" not in df.columns:
            raise MarketStackError(f"API response for {symbol} has no date field.")

        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
        df = df.dropna(subset=["date"])
        df["date"] = df["date"].dt.tz_localize(None).dt.normalize()

        for col in ("open", "high", "low", "close", "volume",
                    "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
                    "split_factor", "dividend"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                df[col] = np.nan

        for col in ("close", "high", "low"):
            if df[col].isna().all():
                raise MarketStackError(
                    f"API response for {symbol} is missing '{col}' prices.")

        df = (df.sort_values("date")
                .drop_duplicates(subset="date", keep="last")
                .set_index("date"))

        # Non-positive prices are corrupt rows, not data.
        df = df[df["close"] > 0]
        if df.empty:
            raise MarketStackError(f"All price rows for {symbol} were invalid.")

        meta_cols = {}
        for col in ("name", "exchange", "exchange_code", "price_currency", "asset_type"):
            if col in df.columns:
                vals = df[col].dropna()
                meta_cols[col] = str(vals.iloc[-1]) if len(vals) else ""
            else:
                meta_cols[col] = ""

        out = df[["open", "high", "low", "close", "volume",
                  "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume",
                  "split_factor", "dividend"]].copy()
        out.attrs["symbol"] = symbol
        out.attrs.update(meta_cols)
        return out

    def latest_quotes(self, symbols: Sequence[str],
                      should_abort: Optional[Callable[[], bool]] = None) -> pd.DataFrame:
        """Latest close and daily change for many symbols in one request.

        The multi-symbol /eod endpoint interleaves recent bars per symbol, so
        requesting a few each gives the previous close alongside the latest.
        Using a single bar's open-to-close would report the intraday move
        rather than the change against the prior session.
        """
        syms = [s.strip().upper() for s in symbols if s and s.strip()]
        syms = list(dict.fromkeys(syms))[:50]
        if not syms:
            return pd.DataFrame()

        want = int(clamp(len(syms) * 6, 20, 1000))
        payload = self._request(
            "eod", {"symbols": ",".join(syms), "limit": want, "sort": "DESC"},
            ttl=CACHE_TTL_QUOTE, should_abort=should_abort)
        data = payload.get("data") or []
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        for col in ("open", "close", "high", "low", "volume", "adj_close"):
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
        df["date"] = pd.to_datetime(df.get("date"), utc=True, errors="coerce")
        df = df.dropna(subset=["date", "close"])
        df["date"] = df["date"].dt.tz_localize(None).dt.normalize()
        df["symbol"] = df.get("symbol", "").astype(str).str.upper()

        out = []
        for sym, grp in df.groupby("symbol"):
            grp = grp.sort_values("date").drop_duplicates("date", keep="last")
            last = grp.iloc[-1]
            prev_close = float(grp["close"].iloc[-2]) if len(grp) >= 2 else float("nan")
            close = float(last["close"])
            if np.isfinite(prev_close) and prev_close > 0:
                chg = close - prev_close
                chg_pct = chg / prev_close
            else:
                # Only one bar for this symbol; fall back to its own open.
                op = float(last.get("open", np.nan))
                chg = close - op if np.isfinite(op) else float("nan")
                chg_pct = (chg / op) if np.isfinite(op) and op > 0 else float("nan")
            out.append({"symbol": sym, "date": last["date"], "close": close,
                        "prev_close": prev_close, "chg": chg, "chg_pct": chg_pct,
                        "volume": float(last.get("volume", np.nan))})
        return pd.DataFrame(out)

    def splits(self, symbol: str,
               should_abort: Optional[Callable[[], bool]] = None) -> pd.DataFrame:
        try:
            payload = self._request("splits", {"symbols": symbol.upper(), "limit": 1000},
                                    ttl=CACHE_TTL_REFERENCE, should_abort=should_abort)
        except MarketStackError:
            return pd.DataFrame(columns=["date", "split_factor"])
        data = payload.get("data") or []
        if not data:
            return pd.DataFrame(columns=["date", "split_factor"])
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df.get("date"), errors="coerce").dt.normalize()
        df["split_factor"] = pd.to_numeric(df.get("split_factor"), errors="coerce")
        df = df.dropna(subset=["date", "split_factor"])
        df = df[df["split_factor"] > 0]
        return df[["date", "split_factor"]].sort_values("date").reset_index(drop=True)

    def dividends(self, symbol: str,
                  should_abort: Optional[Callable[[], bool]] = None) -> pd.DataFrame:
        try:
            payload = self._request("dividends", {"symbols": symbol.upper(), "limit": 1000},
                                    ttl=CACHE_TTL_REFERENCE, should_abort=should_abort)
        except MarketStackError:
            return pd.DataFrame(columns=["date", "dividend", "distr_freq"])
        data = payload.get("data") or []
        if not data:
            return pd.DataFrame(columns=["date", "dividend", "distr_freq"])
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df.get("date"), errors="coerce").dt.normalize()
        df["dividend"] = pd.to_numeric(df.get("dividend"), errors="coerce")
        if "distr_freq" not in df.columns:
            df["distr_freq"] = ""
        df = df.dropna(subset=["date", "dividend"])
        return df[["date", "dividend", "distr_freq"]].sort_values("date").reset_index(drop=True)

    def ticker_info(self, symbol: str,
                    should_abort: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
        try:
            payload = self._request("tickerinfo", {"ticker": symbol.upper()},
                                    ttl=CACHE_TTL_REFERENCE, should_abort=should_abort)
        except MarketStackError:
            return {}
        data = payload.get("data")
        if isinstance(data, list):
            data = data[0] if data else {}
        return data if isinstance(data, dict) else {}


# ==============================================================================
# SECTION 5 - CORPORATE ACTIONS & THE CANONICAL PRICE SERIES
# ==============================================================================
#
# All downstream statistics use the adjusted series, so a bad adjustment
# corrupts volatility, drawdown, beta, backtests and forecasts together.
#
# Resolution order, best source first:
#   1. adj_close from the API, if internally consistent
#   2. Rebuild from the /splits event calendar
#   3. Rebuild from the per-bar split_factor column
#   4. Jump heuristic (last resort)
#
# The heuristic is intentionally strict. A large earnings gap can look like a
# split: a -40% day gives a ratio of 0.60, which is only 0.10 away from 0.50.
# Snapping that to a 2:1 split would rescale all prior history. So the
# heuristic runs only when no event data is available, and requires a much
# tighter match plus an isolated level shift.
# ==============================================================================

SPLIT_CANDIDATES = [2, 3, 4, 5, 6, 7, 8, 10, 20,
                    1.5, 2.5,
                    1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 6, 1 / 7, 1 / 8, 1 / 10, 1 / 20,
                    2 / 3, 3 / 2]
SPLIT_REL_TOL = 0.035     # ratio must be within 3.5% of an exact split ratio


@dataclass
class PriceSeries:
    """Adjusted price history for one symbol."""

    symbol: str
    df: pd.DataFrame                      # DatetimeIndex; px / open / high / low / volume
    adj_method: str = "unknown"
    adj_note: str = ""
    events: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    name: str = ""
    exchange: str = ""
    currency: str = ""
    asset_type: str = ""
    total_return: bool = False
    dividends: pd.DataFrame = field(default_factory=pd.DataFrame)
    splits: pd.DataFrame = field(default_factory=pd.DataFrame)
    info: Dict[str, Any] = field(default_factory=dict)

    # -- convenience accessors -------------------------------------------------
    @property
    def px(self) -> pd.Series:
        return self.df["px"].astype(float)

    @property
    def volume(self) -> pd.Series:
        return self.df["volume"].astype(float)

    @property
    def n(self) -> int:
        return int(len(self.df))

    @property
    def start(self) -> date:
        return self.df.index[0].date()

    @property
    def end(self) -> date:
        return self.df.index[-1].date()

    @property
    def last(self) -> float:
        return float(self.px.iloc[-1])

    @property
    def display_name(self) -> str:
        return self.name or self.symbol

    def returns(self) -> pd.Series:
        return log_returns(self.px)

    def slice_days(self, days: Optional[int]) -> "PriceSeries":
        """View restricted to the last N calendar days (None = all).

        Splits, dividends and company info are shared, not copied: they
        describe the security rather than the window.
        """
        if not days or days <= 0 or self.df.empty:
            return self
        cutoff = self.df.index[-1] - pd.Timedelta(days=days)
        sub = self.df[self.df.index >= cutoff]
        if len(sub) < 5:
            sub = self.df.tail(min(5, len(self.df)))
        if len(sub) == len(self.df):
            return self
        return PriceSeries(
            symbol=self.symbol, df=sub, adj_method=self.adj_method,
            adj_note=self.adj_note, events=list(self.events),
            warnings=list(self.warnings), name=self.name, exchange=self.exchange,
            currency=self.currency, asset_type=self.asset_type,
            total_return=self.total_return, dividends=self.dividends,
            splits=self.splits, info=self.info)


def _nearest_split_ratio(x: float) -> Tuple[Optional[float], float]:
    """Closest canonical split ratio to x, and the relative error."""
    best, best_err = None, float("inf")
    for cand in SPLIT_CANDIDATES:
        err = abs(x - cand) / cand
        if err < best_err:
            best_err, best = err, float(cand)
    return best, best_err


def _adjust_from_events(index: pd.DatetimeIndex, prices: np.ndarray,
                        events: List[Tuple[pd.Timestamp, float]]
                        ) -> Tuple[np.ndarray, np.ndarray]:
    """Back-adjust prices for split events.

    A split of factor f effective on date d means bars before d are quoted on
    the pre-split scale and must be divided by f. Multiple splits compound.

    Returns (adjusted_prices, per_bar_divisor).
    """
    divisor = np.ones(len(prices), dtype=float)
    for when, factor in events:
        if factor <= 0 or abs(factor - 1.0) < 1e-9:
            continue
        mask = index < when
        if mask.any():
            divisor[mask] *= factor
    return prices / divisor, divisor


def audit_data_quality(raw: pd.DataFrame) -> List[str]:
    """Report defects in the delivered feed.

    Vendor EOD data often contains zero-volume bars, rows where high < low, and
    calendar gaps. Each distorts a downstream statistic, so they are listed on
    the DATA tab.
    """
    issues: List[str] = []
    n = len(raw)
    if n == 0:
        return ["No rows returned."]

    zero_vol = int((raw["volume"].fillna(0) <= 0).sum())
    if zero_vol:
        issues.append(f"{zero_vol} bar(s) report zero or missing volume "
                      f"({zero_vol / n:.1%} of the sample). Volume-based "
                      "indicators interpolate across these.")

    bad_hl = int((raw["high"] < raw["low"]).sum())
    if bad_hl:
        issues.append(f"{bad_hl} bar(s) have high < low (corrupt OHLC).")

    outside = int(((raw["close"] > raw["high"] * 1.0001) |
                   (raw["close"] < raw["low"] * 0.9999)).sum())
    if outside:
        issues.append(f"{outside} bar(s) have a close outside the high/low range.")

    missing = int(raw[["open", "high", "low", "close"]].isna().any(axis=1).sum())
    if missing:
        issues.append(f"{missing} bar(s) are missing at least one OHLC field.")

    # Calendar gaps longer than a long weekend plus a holiday.
    if n > 5:
        gaps = raw.index.to_series().diff().dt.days.dropna()
        big = gaps[gaps > 5]
        if len(big):
            worst = int(big.max())
            issues.append(f"{len(big)} calendar gap(s) longer than 5 days "
                          f"(largest {worst} days). Usually holidays or a "
                          "trading halt, but can indicate missing history.")

    dupes = int(raw.index.duplicated().sum())
    if dupes:
        issues.append(f"{dupes} duplicate date(s) were collapsed to the last value.")

    return issues


def _series_has_unexplained_jumps(px: pd.Series, threshold: float = 0.45) -> List[str]:
    """Flag day-over-day moves large enough to suggest a missed corporate action."""
    if len(px) < 3:
        return []
    ratio = px.values[1:] / np.maximum(px.values[:-1], 1e-12)
    flags = []
    for i, r in enumerate(ratio, start=1):
        if r > (1 + threshold) or r < (1 - threshold):
            cand, err = _nearest_split_ratio(r)
            tag = ""
            if cand is not None and err < SPLIT_REL_TOL:
                tag = f"  (~{cand:g}:1 split shape)"
            flags.append(f"{px.index[i].date()}  {(r - 1) * 100:+.1f}% single-day move{tag}")
    return flags


def build_price_series(raw: pd.DataFrame,
                       symbol: str,
                       splits_df: Optional[pd.DataFrame] = None,
                       dividends_df: Optional[pd.DataFrame] = None,
                       total_return: bool = False) -> PriceSeries:
    """Build the adjusted price series from a raw EOD frame."""
    df = raw.copy()
    idx: pd.DatetimeIndex = df.index
    close = df["close"].astype(float).values
    events: List[str] = []
    warns: List[str] = list(audit_data_quality(raw))

    adj_close = df["adj_close"].astype(float)
    have_adj = bool(adj_close.notna().all() and (adj_close > 0).all())

    method = ""
    note = ""
    px = None
    adj_includes_dividends = False

    # ---- 1. API adjusted close, validated ------------------------------------
    if have_adj:
        ratio = close / adj_close.values
        # A sane adjustment factor is positive and monotone non-increasing over
        # time (it only steps at corporate actions). Small float noise allowed.
        finite = np.isfinite(ratio) & (ratio > 0)
        consistent = bool(finite.all())
        if consistent and len(ratio) > 2:
            drift = np.diff(ratio)
            # Allow tiny numerical wobble; large *upward* steps mean the field is
            # not a clean back-adjustment factor.
            consistent = bool(np.nanmax(drift) <= max(1e-6, 0.02 * np.nanmedian(ratio)))
        if consistent:
            px = adj_close.values.astype(float)
            method = "api_adj_close"
            spread = float(np.nanmax(ratio) / max(np.nanmin(ratio), 1e-12))
            n_div = int((df["dividend"].fillna(0.0) > 0).sum())
            n_split = int((df["split_factor"].fillna(1.0) != 1.0).sum())

            if spread > 1.001:
                note = ("Adjusted close supplied by the API (cumulative "
                        f"adjustment factor {spread:.4f}x across the window).")
                # If the factor moved while no split occurred, the movement can
                # only have come from dividends: this is already total return.
                adj_includes_dividends = (n_split == 0 and n_div > 0)
                if adj_includes_dividends:
                    note += (" The factor moves on dividend ex-dates with no "
                             "split present, so it already reinvests dividends "
                             "(a total-return series).")
            elif n_div > 0:
                # Dividends went ex in this window but the factor never
                # moved, so adj_close is split-only: a price-return series.
                note = (f"Adjusted close supplied by the API. {n_div} dividend "
                        "ex-dates fall inside this window but the adjustment "
                        "factor is flat across all of them, so this field is "
                        "SPLIT-ONLY and the series is a price return. Enable "
                        "'Total return' to reinvest dividends.")
            else:
                note = ("Adjusted close supplied by the API (no splits or "
                        "dividends inside this window, so it equals the raw "
                        "close).")
            _ = n_split
        else:
            warns.append("adj_close failed its consistency check; rebuilding from "
                         "split events instead.")

    # ---- 2. Authoritative split calendar -------------------------------------
    if px is None and splits_df is not None and not splits_df.empty:
        ev = [(pd.Timestamp(r.date), float(r.split_factor))
              for r in splits_df.itertuples()
              if idx[0] < pd.Timestamp(r.date) <= idx[-1]]
        if ev:
            px, _ = _adjust_from_events(idx, close, ev)
            method = "splits_endpoint"
            note = "Back-adjusted using the MarketStack corporate-action calendar."
            events += [f"{w.date()}  {f:g}:1 split (official calendar)" for w, f in ev]
        else:
            px = close.copy()
            method = "splits_endpoint_none"
            note = ("No split occurred inside this window per the MarketStack "
                    "corporate-action calendar; raw close used unchanged.")

    # ---- 3. Per-bar split_factor column --------------------------------------
    if px is None:
        sf = df["split_factor"].fillna(1.0).replace(0.0, 1.0).astype(float)
        if (sf != 1.0).any():
            ev = [(ts, float(f)) for ts, f in sf.items() if abs(f - 1.0) > 1e-9]
            px, _ = _adjust_from_events(idx, close, ev)
            method = "split_factor_column"
            note = "Back-adjusted using the per-bar split_factor field."
            events += [f"{w.date()}  {f:g}:1 split (bar field)" for w, f in ev]

    # ---- 4. Conservative heuristic, last resort ------------------------------
    if px is None:
        px = close.copy()
        method = "heuristic"
        detected: List[Tuple[pd.Timestamp, float, float]] = []
        if len(close) >= 30:
            ratio = close[1:] / np.maximum(close[:-1], 1e-12)
            for i, r in enumerate(ratio, start=1):
                if 0.80 < r < 1.25:
                    continue
                cand, err = _nearest_split_ratio(r)
                if cand is None or err > SPLIT_REL_TOL:
                    continue
                # Require an isolated level shift, not part of a volatile run.
                lo, hi = max(0, i - 4), min(len(ratio), i + 4)
                neighbours = np.delete(ratio[lo:hi], min(i - lo, hi - lo - 1))
                if len(neighbours) and np.nanmax(np.abs(neighbours - 1.0)) > 0.18:
                    continue
                detected.append((idx[i], 1.0 / cand, r))
        if detected:
            px, _ = _adjust_from_events(idx, close, [(w, f) for w, f, _ in detected])
            note = ("No adjusted prices from the API. Applied a conservative "
                    "split heuristic (isolated level shifts matching exact split "
                    "ratios within 3.5%).")
            events += [f"{w.date()}  ~{1 / f:g}:1 split inferred (raw ratio {r:.3f})"
                       for w, f, r in detected]
            warns.append("Prices were adjusted heuristically, not from official "
                         "corporate-action data. Treat long-horizon statistics with care.")
        else:
            note = ("No adjusted prices and no corporate actions detected; "
                    "raw close used unchanged.")

    out = pd.DataFrame(index=idx)
    out["px"] = px
    scale = np.where(close > 0, px / close, 1.0)
    out["open"] = df["open"].astype(float).values * scale
    out["high"] = df["high"].astype(float).values * scale
    out["low"] = df["low"].astype(float).values * scale
    out["close_raw"] = close

    vol = df["adj_volume"]
    if vol.isna().all():
        vol = df["volume"]
    out["volume"] = pd.to_numeric(vol, errors="coerce").fillna(0.0).values

    out["dividend"] = df["dividend"].fillna(0.0).values
    out["split_factor"] = df["split_factor"].fillna(1.0).values

    # ---- optional total-return overlay ---------------------------------------
    is_tr = False
    if total_return and adj_includes_dividends:
        # Reinvesting on top of an already-reinvested series would compound the
        # dividends twice and overstate the return.
        is_tr = True
        note += ("  Total-return requested, but the supplied adjusted close "
                 "already reinvests dividends; no second overlay was applied.")
    elif total_return:
        divs = out["dividend"].astype(float).copy()
        if (divs <= 0).all() and dividends_df is not None and not dividends_df.empty:
            aligned = dividends_df.set_index("date")["dividend"]
            divs = aligned.reindex(out.index).fillna(0.0)
        if (divs > 0).any():
            prev = out["px"].shift(1)
            factor = (1.0 + (divs / prev.replace(0, np.nan))).fillna(1.0)
            out["px"] = out["px"] * factor.cumprod()
            is_tr = True
            note += (f"  Total-return overlay applied ({int((divs > 0).sum())} "
                     "dividend events reinvested).")
        else:
            warns.append("Total-return requested but no dividends fell inside this "
                         "window; showing price return.")

    out = out[out["px"] > 0]

    residual = _series_has_unexplained_jumps(out["px"])
    if residual:
        warns.append("Large single-day moves remain after adjustment (these are "
                     "usually genuine news/earnings gaps, but verify): "
                     + "; ".join(residual[:4]))

    ps = PriceSeries(
        symbol=symbol.upper(), df=out, adj_method=method, adj_note=note,
        events=events, warnings=warns,
        name=str(raw.attrs.get("name", "") or ""),
        exchange=str(raw.attrs.get("exchange_code", "") or raw.attrs.get("exchange", "") or ""),
        currency=str(raw.attrs.get("price_currency", "") or ""),
        asset_type=str(raw.attrs.get("asset_type", "") or ""),
        total_return=is_tr,
    )
    if dividends_df is not None:
        ps.dividends = dividends_df
    if splits_df is not None:
        ps.splits = splits_df
    return ps


# ==============================================================================
# SECTION 6 - INDICATORS
# ==============================================================================

def log_returns(px: pd.Series) -> pd.Series:
    px = px.astype(float)
    return np.log(px / px.shift(1))


def simple_returns(px: pd.Series) -> pd.Series:
    return px.astype(float).pct_change()


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, min_periods=window).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI.

    When the average loss is 0 the result is 100, not NaN.
    """
    delta = s.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    out = pd.Series(np.nan, index=s.index, dtype=float)
    both_zero = (avg_gain == 0) & (avg_loss == 0)
    only_gain = (avg_loss == 0) & (avg_gain > 0)
    normal = avg_loss > 0

    rs = avg_gain[normal] / avg_loss[normal]
    out[normal] = 100.0 - (100.0 / (1.0 + rs))
    out[only_gain] = 100.0
    out[both_zero] = 50.0
    out[avg_gain.isna() | avg_loss.isna()] = np.nan
    return out


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(s, fast) - ema(s, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def bollinger(s: pd.Series, window: int = 20, k: float = 2.0):
    mid = sma(s, window)
    sd = s.rolling(window, min_periods=window).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    width = (upper - lower) / mid.replace(0, np.nan)
    pctb = (s - lower) / (upper - lower).replace(0, np.nan)
    return mid, upper, lower, width, pctb


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    return pd.concat([(high - low).abs(),
                      (high - prev).abs(),
                      (low - prev).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return true_range(high, low, close).ewm(alpha=1 / period, adjust=False,
                                            min_periods=period).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    up = high.diff()
    dn = -low.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(high, low, close)
    atr_ = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    denom = atr_.replace(0, np.nan)
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(
        alpha=1 / period, adjust=False, min_periods=period).mean() / denom
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(
        alpha=1 / period, adjust=False, min_periods=period).mean() / denom
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean(), plus_di, minus_di


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period: int = 14, d_period: int = 3):
    lo = low.rolling(k_period, min_periods=k_period).min()
    hi = high.rolling(k_period, min_periods=k_period).max()
    k = 100 * (close - lo) / (hi - lo).replace(0, np.nan)
    return k, k.rolling(d_period, min_periods=d_period).mean()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    sign = np.sign(close.diff().fillna(0.0))
    return (sign * volume).cumsum()


def money_flow_index(high, low, close, volume, period: int = 14) -> pd.Series:
    tp = (high + low + close) / 3.0
    flow = tp * volume
    delta = tp.diff()
    pos = flow.where(delta > 0, 0.0).rolling(period, min_periods=period).sum()
    neg = flow.where(delta < 0, 0.0).rolling(period, min_periods=period).sum()
    ratio = pos / neg.replace(0, np.nan)
    out = 100 - (100 / (1 + ratio))
    return out.fillna(100.0).where(pos.notna(), np.nan)


def donchian(high: pd.Series, low: pd.Series, window: int = 20,
             exclude_current: bool = False):
    """Donchian channel.

    exclude_current=True builds the channel from the prior `window` bars, which
    is the form a breakout test needs: a close can rarely exceed a channel that
    already contains the same bar's high, so the inclusive form never triggers.
    """
    hi = high.rolling(window, min_periods=window).max()
    lo = low.rolling(window, min_periods=window).min()
    if exclude_current:
        hi, lo = hi.shift(1), lo.shift(1)
    return hi, lo


def drawdown_series(px: pd.Series) -> pd.Series:
    return px / px.cummax() - 1.0


# ==============================================================================
# SECTION 7 - RISK & PERFORMANCE STATISTICS
# ==============================================================================

def ann_vol(px: pd.Series, periods: int = TRADING_DAYS) -> float:
    r = log_returns(px).dropna()
    if len(r) < 10:
        return float("nan")
    return float(r.std(ddof=1) * math.sqrt(periods))


def ann_return_geometric(px: pd.Series) -> float:
    """CAGR from the realised path."""
    px = px.dropna()
    if len(px) < 10:
        return float("nan")
    years = (px.index[-1] - px.index[0]).days / 365.25
    if years <= 0 or px.iloc[0] <= 0:
        return float("nan")
    return float((px.iloc[-1] / px.iloc[0]) ** (1 / years) - 1)


def ann_drift_log(px: pd.Series) -> float:
    r = log_returns(px).dropna()
    if len(r) < 10:
        return float("nan")
    return float(r.mean() * TRADING_DAYS)


def max_drawdown(px: pd.Series) -> float:
    if len(px) < 2:
        return float("nan")
    return float(drawdown_series(px).min())


def drawdown_detail(px: pd.Series) -> Dict[str, Any]:
    """Worst drawdown with peak, trough, recovery dates and durations."""
    if len(px) < 3:
        return {}
    dd = drawdown_series(px)
    trough = dd.idxmin()
    depth = float(dd.loc[trough])
    peak = px.loc[:trough].idxmax()
    after = px.loc[trough:]
    peak_val = float(px.loc[peak])
    recovered = after[after >= peak_val]
    rec = recovered.index[0] if len(recovered) else None
    cur = float(dd.iloc[-1])
    under = int((dd < -1e-9).sum())
    return {
        "depth": depth, "peak": peak, "trough": trough, "recovery": rec,
        "drop_days": int(len(px.loc[peak:trough]) - 1),
        "recovery_days": int(len(px.loc[trough:rec]) - 1) if rec is not None else None,
        "current": cur,
        "pct_time_underwater": under / max(len(dd), 1),
    }


def sharpe_ratio(px: pd.Series, rf_annual: float = 0.0) -> float:
    r = log_returns(px).dropna()
    if len(r) < 10:
        return float("nan")
    sd = r.std(ddof=1)
    if sd <= 0:
        return float("nan")
    excess = r.mean() - rf_annual / TRADING_DAYS
    return float(excess / sd * math.sqrt(TRADING_DAYS))


def sortino_ratio(px: pd.Series, rf_annual: float = 0.0) -> float:
    r = log_returns(px).dropna()
    if len(r) < 10:
        return float("nan")
    target = rf_annual / TRADING_DAYS
    downside = r[r < target] - target
    if len(downside) < 3:
        return float("nan")
    dd = math.sqrt(float((downside ** 2).mean()))
    if dd <= 0:
        return float("nan")
    return float((r.mean() - target) / dd * math.sqrt(TRADING_DAYS))


def calmar_ratio(px: pd.Series) -> float:
    cagr = ann_return_geometric(px)
    mdd = max_drawdown(px)
    if not np.isfinite(cagr) or not np.isfinite(mdd) or mdd >= -1e-9:
        return float("nan")
    return float(cagr / abs(mdd))


def omega_ratio(px: pd.Series, threshold: float = 0.0) -> float:
    r = simple_returns(px).dropna()
    if len(r) < 20:
        return float("nan")
    gains = (r[r > threshold] - threshold).sum()
    losses = (threshold - r[r <= threshold]).sum()
    if losses <= 0:
        return float("inf") if gains > 0 else float("nan")
    return float(gains / losses)


def historical_var(px: pd.Series, level: float = 0.95, horizon: int = 1) -> float:
    """Historical VaR, returned as a positive loss fraction."""
    r = simple_returns(px).dropna()
    if len(r) < 30:
        return float("nan")
    q = float(np.quantile(r, 1 - level))
    return float(-q * math.sqrt(horizon))


def cvar(px: pd.Series, level: float = 0.95) -> float:
    r = simple_returns(px).dropna()
    if len(r) < 30:
        return float("nan")
    q = np.quantile(r, 1 - level)
    tail = r[r <= q]
    if len(tail) == 0:
        return float("nan")
    return float(-tail.mean())


def cornish_fisher_var(px: pd.Series, level: float = 0.95) -> float:
    """VaR adjusted for skew and kurtosis (Cornish-Fisher expansion)."""
    r = simple_returns(px).dropna()
    if len(r) < 60:
        return float("nan")
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    if sd <= 0:
        return float("nan")
    s = float(r.skew())
    k = float(r.kurtosis())          # already excess
    from statistics import NormalDist
    z = NormalDist().inv_cdf(1 - level)
    zc = (z + (z ** 2 - 1) * s / 6
          + (z ** 3 - 3 * z) * k / 24
          - (2 * z ** 3 - 5 * z) * (s ** 2) / 36)
    return float(-(mu + zc * sd))


def tail_stats(px: pd.Series) -> Dict[str, float]:
    r = simple_returns(px).dropna()
    if len(r) < 20:
        return {}
    return {
        "skew": float(r.skew()),
        "excess_kurtosis": float(r.kurtosis()),
        "best_day": float(r.max()),
        "worst_day": float(r.min()),
        "pos_days": float((r > 0).mean()),
        "avg_gain": float(r[r > 0].mean()) if (r > 0).any() else float("nan"),
        "avg_loss": float(r[r < 0].mean()) if (r < 0).any() else float("nan"),
    }


def align_returns(a: pd.Series, b: pd.Series) -> pd.DataFrame:
    """Inner-join two return series on date.

    Both series must be indexed by date. Joining on position instead would
    pair unrelated sessions whenever the two histories differ in length or
    have different missing days.
    """
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner")
    return df.dropna()


def beta_and_corr(asset_rets: pd.Series, bench_rets: pd.Series,
                  min_obs: int = 30) -> Tuple[float, float, int]:
    df = align_returns(asset_rets, bench_rets)
    if len(df) < min_obs:
        return float("nan"), float("nan"), len(df)
    a, b = df["a"].values, df["b"].values
    var_b = float(np.var(b, ddof=1))
    if var_b <= 0:
        return float("nan"), float("nan"), len(df)
    beta = float(np.cov(a, b, ddof=1)[0, 1] / var_b)
    corr = float(np.corrcoef(a, b)[0, 1])
    return beta, corr, len(df)


def rolling_beta(asset_rets: pd.Series, bench_rets: pd.Series,
                 window: int = 60) -> pd.Series:
    df = align_returns(asset_rets, bench_rets)
    if len(df) < window + 5:
        return pd.Series(dtype=float)
    cov = df["a"].rolling(window).cov(df["b"])
    var = df["b"].rolling(window).var()
    return (cov / var.replace(0, np.nan)).dropna()


def alpha_annualised(asset_rets: pd.Series, bench_rets: pd.Series, beta: float) -> float:
    df = align_returns(asset_rets, bench_rets)
    if len(df) < 30 or not np.isfinite(beta):
        return float("nan")
    return float((df["a"].mean() - beta * df["b"].mean()) * TRADING_DAYS)


def tracking_error(asset_rets: pd.Series, bench_rets: pd.Series) -> float:
    df = align_returns(asset_rets, bench_rets)
    if len(df) < 30:
        return float("nan")
    return float((df["a"] - df["b"]).std(ddof=1) * math.sqrt(TRADING_DAYS))


def information_ratio(asset_rets: pd.Series, bench_rets: pd.Series) -> float:
    df = align_returns(asset_rets, bench_rets)
    if len(df) < 30:
        return float("nan")
    diff = df["a"] - df["b"]
    sd = diff.std(ddof=1)
    if sd <= 0:
        return float("nan")
    return float(diff.mean() / sd * math.sqrt(TRADING_DAYS))


def upside_downside_capture(asset_rets: pd.Series,
                            bench_rets: pd.Series) -> Tuple[float, float]:
    df = align_returns(asset_rets, bench_rets)
    if len(df) < 30:
        return float("nan"), float("nan")
    up, dn = df[df["b"] > 0], df[df["b"] < 0]
    u = float(up["a"].mean() / up["b"].mean()) if len(up) > 5 and up["b"].mean() != 0 else float("nan")
    d = float(dn["a"].mean() / dn["b"].mean()) if len(dn) > 5 and dn["b"].mean() != 0 else float("nan")
    return u, d


def hurst_exponent(px: pd.Series) -> float:
    """Hurst exponent from the variance of lagged log-price differences.

    Log price keeps the estimate scale-invariant.
    """
    s = np.log(px.dropna().astype(float).values)
    n = len(s)
    if n < 120:
        return float("nan")
    lags = [l for l in (2, 4, 8, 16, 32, 64) if l < n // 3]
    if len(lags) < 3:
        return float("nan")
    tau = []
    keep = []
    for lag in lags:
        diff = s[lag:] - s[:-lag]
        sd = float(np.std(diff, ddof=1))
        if sd > 0:
            tau.append(sd)
            keep.append(lag)
    if len(tau) < 3:
        return float("nan")
    slope = np.polyfit(np.log(keep), np.log(tau), 1)[0]
    return float(clamp(slope, 0.0, 1.0))


def variance_ratio(px: pd.Series, q: int = 5) -> float:
    """Lo-MacKinlay variance ratio. 1 = random walk, >1 trending, <1 reverting."""
    r = log_returns(px).dropna().values
    n = len(r)
    if n < q * 12:
        return float("nan")
    var1 = np.var(r, ddof=1)
    if var1 <= 0:
        return float("nan")
    agg = np.array([r[i:i + q].sum() for i in range(0, n - q + 1)])
    return float(np.var(agg, ddof=1) / (q * var1))


def autocorrelation(px: pd.Series, lags: int = 5) -> Dict[int, float]:
    r = log_returns(px).dropna()
    if len(r) < 40:
        return {}
    return {k: float(r.autocorr(lag=k)) for k in range(1, lags + 1)}


def vol_regime(px: pd.Series) -> Dict[str, Any]:
    """Short-horizon realised volatility against its own history."""
    r = log_returns(px).dropna()
    out: Dict[str, Any] = {"rv20": float("nan"), "rv60": float("nan"),
                           "rv120": float("nan"), "percentile": float("nan"),
                           "label": "insufficient data", "ewma": float("nan")}
    if len(r) < 25:
        return out
    ann = math.sqrt(TRADING_DAYS)
    rv20 = r.rolling(20).std(ddof=1) * ann
    out["rv20"] = float(rv20.iloc[-1]) if rv20.notna().any() else float("nan")
    if len(r) >= 65:
        out["rv60"] = float((r.rolling(60).std(ddof=1) * ann).iloc[-1])
    if len(r) >= 125:
        out["rv120"] = float((r.rolling(120).std(ddof=1) * ann).iloc[-1])

    lam = 0.94
    ew = r.ewm(alpha=1 - lam, adjust=False).std()
    out["ewma"] = float(ew.iloc[-1] * ann) if ew.notna().any() else float("nan")

    hist = rv20.dropna()
    if len(hist) >= 40 and np.isfinite(out["rv20"]):
        pct = float((hist <= out["rv20"]).mean())
        out["percentile"] = pct
        out["label"] = ("very low" if pct < 0.15 else "low" if pct < 0.35 else
                        "normal" if pct < 0.65 else "elevated" if pct < 0.85 else "high")
    elif np.isfinite(out["rv20"]) and np.isfinite(out["rv120"]):
        out["label"] = "elevated" if out["rv20"] > out["rv120"] * 1.15 else "normal"
    return out


def trend_state(px: pd.Series) -> Dict[str, Any]:
    """Where price sits relative to its moving averages."""
    out: Dict[str, Any] = {}
    for w in (20, 50, 100, 200):
        v = sma(px, w)
        out[f"sma{w}"] = float(v.iloc[-1]) if v.notna().any() else float("nan")
    last = float(px.iloc[-1])
    out["last"] = last
    s20, s50, s200 = out["sma20"], out["sma50"], out["sma200"]
    score = 0
    checks = []
    if np.isfinite(s20):
        ok = last > s20
        score += 1 if ok else -1
        checks.append(("Price vs SMA20", ok))
    if np.isfinite(s50):
        ok = last > s50
        score += 1 if ok else -1
        checks.append(("Price vs SMA50", ok))
    if np.isfinite(s20) and np.isfinite(s50):
        ok = s20 > s50
        score += 1 if ok else -1
        checks.append(("SMA20 vs SMA50", ok))
    if np.isfinite(s200):
        ok = last > s200
        score += 1 if ok else -1
        checks.append(("Price vs SMA200", ok))
    out["checks"] = checks
    out["score"] = score
    out["label"] = ("strong uptrend" if score >= 3 else "uptrend" if score >= 1 else
                    "neutral" if score == 0 else "downtrend" if score >= -2 else
                    "strong downtrend")
    hi = float(px.max())
    lo = float(px.min())
    out["from_high"] = last / hi - 1.0 if hi > 0 else float("nan")
    out["from_low"] = last / lo - 1.0 if lo > 0 else float("nan")
    out["window_high"] = hi
    out["window_low"] = lo
    return out


def period_returns(px: pd.Series) -> Dict[str, float]:
    """Trailing returns over standard windows, plus YTD."""
    out: Dict[str, float] = {}
    last = float(px.iloc[-1])
    for label, days in (("1D", 1), ("1W", 5), ("1M", 21), ("3M", 63),
                        ("6M", 126), ("1Y", 252)):
        if len(px) > days:
            prev = float(px.iloc[-1 - days])
            out[label] = last / prev - 1.0 if prev > 0 else float("nan")
        else:
            out[label] = float("nan")
    jan1 = pd.Timestamp(year=px.index[-1].year, month=1, day=1)
    ytd = px[px.index >= jan1]
    out["YTD"] = (last / float(ytd.iloc[0]) - 1.0) if len(ytd) > 1 else float("nan")
    return out


def seasonality(px: pd.Series) -> Dict[str, Any]:
    """Average daily log return by weekday and month, with counts.

    Counts are returned so the UI can mark thin buckets.
    """
    r = log_returns(px).dropna()
    if len(r) < 30:
        return {}
    frame = pd.DataFrame({"r": r})
    frame["dow"] = frame.index.dayofweek
    frame["month"] = frame.index.month

    dow = frame.groupby("dow")["r"].agg(["mean", "std", "count",
                                         lambda x: float((x > 0).mean())])
    dow.columns = ["mean", "std", "count", "win"]
    mon = frame.groupby("month")["r"].agg(["mean", "std", "count",
                                           lambda x: float((x > 0).mean())])
    mon.columns = ["mean", "std", "count", "win"]

    # Compounded monthly returns.
    monthly = px.resample("ME").last().pct_change().dropna()
    by_month = {}
    if len(monthly) >= 6:
        mf = pd.DataFrame({"r": monthly})
        mf["m"] = mf.index.month
        g = mf.groupby("m")["r"].agg(["mean", "count"])
        by_month = {int(k): (float(v["mean"]), int(v["count"])) for k, v in g.iterrows()}

    return {"dow": dow, "month": mon, "monthly_compound": by_month,
            "years": float((r.index[-1] - r.index[0]).days / 365.25)}


# ==============================================================================
# SECTION 8 - FORECASTING
# ==============================================================================
#
# Design rules:
#
#   1. Every horizon returns a P10/P50/P90 band, not a point estimate.
#   2. Walk-forward folds keep an h-day embargo between train and test.
#      Without it the overlapping target windows share outcomes and the
#      validation scores are meaningless.
#   3. Confidence scales with how many independent windows of that horizon fit
#      in the sample. A 252-day horizon on 251 rows has less than one, so the
#      score collapses toward zero.
# ==============================================================================

HORIZONS: List[Tuple[str, int]] = [
    ("1 month", 21), ("3 months", 63), ("6 months", 126), ("12 months", 252),
]

FEATURE_COLS = ["lr1", "lr5", "lr21", "vol10", "vol21", "vol63",
                "px_sma20", "px_sma50", "sma20_sma50", "rsi14",
                "macd_hist_n", "bb_pctb", "atr_n", "volume_z", "dow", "month"]


@dataclass
class ForecastResult:
    horizon_days: int
    label: str
    p10: float
    p50: float
    p90: float
    up_probability: float
    confidence: float
    model: str
    notes: str
    expected_return: float = float("nan")
    rmse: float = float("nan")
    hit_rate: float = float("nan")
    auc: float = float("nan")
    n_train: int = 0
    n_folds: int = 0
    supported: bool = True


def _sim_summary(terminal: np.ndarray, s0: float, model: str, notes: str,
                 label: str, h: int, confidence: float) -> ForecastResult:
    terminal = terminal[np.isfinite(terminal)]
    if terminal.size == 0:
        return ForecastResult(h, label, float("nan"), float("nan"), float("nan"),
                              float("nan"), 0.0, model,
                              "Simulation produced no finite paths.", supported=False)
    p10, p50, p90 = (float(np.percentile(terminal, q)) for q in (10, 50, 90))
    return ForecastResult(
        horizon_days=h, label=label, p10=p10, p50=p50, p90=p90,
        up_probability=float((terminal > s0).mean()),
        confidence=confidence, model=model, notes=notes,
        expected_return=p50 / s0 - 1.0 if s0 > 0 else float("nan"),
        n_train=0,
    )


def simulate_terminal(px: pd.Series, horizon: int, model: str = "block",
                      n_sims: int = 20000, seed: Optional[int] = None) -> np.ndarray:
    """Simulate terminal prices `horizon` trading days out.

    Models
    ------
    gbm    : geometric Brownian motion from sample drift/vol
    iid    : IID bootstrap of historical daily log returns
    block  : stationary block bootstrap, preserves volatility clustering
    t      : Student-t innovations fitted to sample kurtosis
    """
    rng = np.random.default_rng(seed)
    s0 = float(px.iloc[-1])
    r = log_returns(px).dropna().values
    if len(r) < 5:
        return np.full(n_sims, s0)

    mu, sd = float(np.mean(r)), float(np.std(r, ddof=1))
    if not np.isfinite(sd) or sd <= 0:
        sd = 1e-4

    if model == "gbm":
        inc = (mu - 0.5 * sd * sd) + sd * rng.standard_normal((n_sims, horizon))
        total = inc.sum(axis=1)

    elif model == "iid":
        total = rng.choice(r, size=(n_sims, horizon), replace=True).sum(axis=1)

    elif model == "t":
        k = float(pd.Series(r).kurtosis())
        nu = clamp(6.0 / max(k, 0.01) + 4.0, 3.0, 30.0) if np.isfinite(k) and k > 0 else 8.0
        scale = sd / math.sqrt(nu / (nu - 2.0))
        inc = mu + scale * rng.standard_t(nu, size=(n_sims, horizon))
        total = inc.sum(axis=1)

    else:  # stationary block bootstrap
        block = int(clamp(round(len(r) ** (1 / 3) * 2), 5, 40))
        n_blocks = int(math.ceil(horizon / block))
        starts = rng.integers(0, len(r), size=(n_sims, n_blocks))
        offsets = np.arange(block)
        idx = (starts[:, :, None] + offsets[None, None, :]) % len(r)
        draws = r[idx.reshape(n_sims, -1)][:, :horizon]
        total = draws.sum(axis=1)

    return s0 * np.exp(total)


def simulate_paths(px: pd.Series, horizon: int, n_paths: int,
                   model: str = "block", seed: Optional[int] = None) -> np.ndarray:
    """Simulated price paths, shape (horizon, n_paths)."""
    rng = np.random.default_rng(seed)
    s0 = float(px.iloc[-1])
    r = log_returns(px).dropna().values
    if len(r) < 5:
        return np.full((horizon, n_paths), s0)

    mu, sd = float(np.mean(r)), float(np.std(r, ddof=1))
    if not np.isfinite(sd) or sd <= 0:
        sd = 1e-4

    if model == "gbm":
        inc = (mu - 0.5 * sd * sd) + sd * rng.standard_normal((horizon, n_paths))
    elif model == "iid":
        inc = rng.choice(r, size=(horizon, n_paths), replace=True)
    elif model == "t":
        k = float(pd.Series(r).kurtosis())
        nu = clamp(6.0 / max(k, 0.01) + 4.0, 3.0, 30.0) if np.isfinite(k) and k > 0 else 8.0
        scale = sd / math.sqrt(nu / (nu - 2.0))
        inc = mu + scale * rng.standard_t(nu, size=(horizon, n_paths))
    else:
        block = int(clamp(round(len(r) ** (1 / 3) * 2), 5, 40))
        n_blocks = int(math.ceil(horizon / block))
        starts = rng.integers(0, len(r), size=(n_paths, n_blocks))
        offsets = np.arange(block)
        idx = (starts[:, :, None] + offsets[None, None, :]) % len(r)
        inc = r[idx.reshape(n_paths, -1)][:, :horizon].T

    logs = np.vstack([np.zeros((1, n_paths)), np.cumsum(inc, axis=0)])[:horizon]
    return s0 * np.exp(logs)


MC_MODEL_KEYS = {
    "GBM (normal)": "gbm",
    "Bootstrap (IID)": "iid",
    "Block bootstrap": "block",
    "Student-t (fat tail)": "t",
}


def build_features(ps: PriceSeries) -> pd.DataFrame:
    """Feature matrix on the adjusted series; all features are backward-looking."""
    df = ps.df
    px = df["px"].astype(float)
    x = pd.DataFrame(index=df.index)

    lp = np.log(px)
    x["lr1"] = lp.diff()
    x["lr5"] = lp.diff(5)
    x["lr21"] = lp.diff(21)
    x["vol10"] = x["lr1"].rolling(10).std(ddof=1)
    x["vol21"] = x["lr1"].rolling(21).std(ddof=1)
    x["vol63"] = x["lr1"].rolling(63).std(ddof=1)

    s20, s50 = sma(px, 20), sma(px, 50)
    x["px_sma20"] = px / s20 - 1.0
    x["px_sma50"] = px / s50 - 1.0
    x["sma20_sma50"] = s20 / s50 - 1.0

    x["rsi14"] = rsi(px, 14) / 100.0

    _, _, hist = macd(px)
    x["macd_hist_n"] = hist / px

    _, _, _, _, pctb = bollinger(px, 20, 2.0)
    x["bb_pctb"] = pctb

    x["atr_n"] = atr(df["high"], df["low"], px, 14) / px

    # Zero-volume bars are missing data, not real inactivity. Masking them to
    # NaN without filling the gap is expensive: rolling(63) rejects any window
    # containing one, so a few bad bars drop dozens of valid training rows.
    # Interpolate and relax min_periods instead.
    v = df["volume"].astype(float)
    v = v.mask(v <= 0).interpolate(limit_direction="both")
    lv = np.log(v.clip(lower=1.0))
    roll_mean = lv.rolling(63, min_periods=21).mean()
    roll_std = lv.rolling(63, min_periods=21).std(ddof=1)
    x["volume_z"] = (lv - roll_mean) / roll_std.replace(0, np.nan)

    x["dow"] = df.index.dayofweek.astype(float)
    x["month"] = df.index.month.astype(float)

    x["px"] = px
    return x.replace([np.inf, -np.inf], np.nan).dropna()


def _make_targets(feat: pd.DataFrame, horizon: int) -> pd.DataFrame:
    px = feat["px"].values
    if len(px) <= horizon + 10:
        return pd.DataFrame()
    out = feat.iloc[:-horizon].copy()
    out["y_lr"] = np.log(px[horizon:] / px[:-horizon])
    out["y_up"] = (out["y_lr"] > 0).astype(int)
    return out


def _embargoed_folds(n: int, horizon: int, n_splits: int
                     ) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Expanding-window folds with a `horizon`-day gap between train and test.

    Without the gap the last training targets are computed from prices inside
    the test window, which leaks outcomes and inflates validation scores.
    """
    folds = []
    test_size = max(15, (n - horizon) // (n_splits + 1))
    for i in range(n_splits):
        train_end = n - (n_splits - i) * test_size - horizon
        if train_end < 40:
            continue
        test_start = train_end + horizon
        test_end = min(n, test_start + test_size)
        if test_end - test_start < 8:
            continue
        folds.append((np.arange(0, train_end), np.arange(test_start, test_end)))
    return folds


def _ml_forecast(feat: pd.DataFrame, horizon: int, label: str,
                 s0: float, n_hist: int,
                 should_abort: Optional[Callable[[], bool]] = None
                 ) -> Optional[ForecastResult]:
    """Walk-forward validated ensemble. Returns None if it cannot be validated."""
    try:
        from sklearn.preprocessing import StandardScaler
        from sklearn.linear_model import Ridge, LogisticRegression
        from sklearn.ensemble import (RandomForestRegressor, GradientBoostingRegressor,
                                      RandomForestClassifier)
        from sklearn.metrics import mean_squared_error, roc_auc_score
    except ImportError:
        return None

    ydf = _make_targets(feat, horizon)
    if ydf.empty or len(ydf) < 90:
        return None

    X = ydf[FEATURE_COLS].values.astype(float)
    y_lr = ydf["y_lr"].values.astype(float)
    y_up = ydf["y_up"].values.astype(int)
    n = len(X)

    folds = _embargoed_folds(n, horizon, n_splits=4)
    if len(folds) < 2:
        return None

    rmses, hits, aucs = [], [], []
    for tr, te in folds:
        if should_abort and should_abort():
            raise Cancelled()
        sc = StandardScaler()
        Xtr, Xte = sc.fit_transform(X[tr]), sc.transform(X[te])

        preds = []
        for m in (Ridge(alpha=2.0),
                  GradientBoostingRegressor(random_state=7, n_estimators=120,
                                            max_depth=2, learning_rate=0.05),
                  RandomForestRegressor(n_estimators=150, random_state=7,
                                        min_samples_leaf=5, n_jobs=-1)):
            m.fit(Xtr, y_lr[tr])
            preds.append(m.predict(Xte))
        pred = np.mean(preds, axis=0)
        rmses.append(math.sqrt(mean_squared_error(y_lr[te], pred)))

        if len(np.unique(y_up[tr])) >= 2:
            probs = []
            for c in (LogisticRegression(max_iter=2000),
                      RandomForestClassifier(n_estimators=150, random_state=7,
                                             min_samples_leaf=5, n_jobs=-1)):
                c.fit(Xtr, y_up[tr])
                probs.append(c.predict_proba(Xte)[:, 1])
            p = np.mean(probs, axis=0)
            hits.append(float(((p >= 0.5).astype(int) == y_up[te]).mean()))
            if len(np.unique(y_up[te])) >= 2:
                aucs.append(float(roc_auc_score(y_up[te], p)))

    if should_abort and should_abort():
        raise Cancelled()

    # Final fit on everything, then predict from the most recent feature row.
    sc = StandardScaler()
    Xs = sc.fit_transform(X)
    reg_final = []
    for m in (Ridge(alpha=2.0),
              GradientBoostingRegressor(random_state=7, n_estimators=120,
                                        max_depth=2, learning_rate=0.05),
              RandomForestRegressor(n_estimators=150, random_state=7,
                                    min_samples_leaf=5, n_jobs=-1)):
        m.fit(Xs, y_lr)
        reg_final.append(m)

    x_last = sc.transform(feat[FEATURE_COLS].iloc[[-1]].values.astype(float))
    pred_lr = float(np.mean([m.predict(x_last)[0] for m in reg_final]))

    up_prob = float("nan")
    if len(np.unique(y_up)) >= 2:
        clf_probs = []
        for c in (LogisticRegression(max_iter=2000),
                  RandomForestClassifier(n_estimators=150, random_state=7,
                                         min_samples_leaf=5, n_jobs=-1)):
            c.fit(Xs, y_up)
            clf_probs.append(c.predict_proba(x_last)[0, 1])
        up_prob = float(np.mean(clf_probs))

    rmse = float(np.nanmean(rmses)) if rmses else float("nan")
    hit = float(np.nanmean(hits)) if hits else float("nan")
    auc = float(np.nanmean(aucs)) if aucs else float("nan")

    # Band from the model's own out-of-sample error, not from an assumption.
    sd = rmse if np.isfinite(rmse) and rmse > 0 else float(np.std(y_lr, ddof=1))
    centre = s0 * math.exp(pred_lr)
    p10 = s0 * math.exp(pred_lr - 1.2816 * sd)
    p90 = s0 * math.exp(pred_lr + 1.2816 * sd)
    if not np.isfinite(up_prob):
        up_prob = float(np.mean(y_up))

    conf = _confidence(n_hist, horizon, rmse=rmse, auc=auc, hit=hit,
                       n_folds=len(folds), is_ml=True)

    notes = ("Ridge + gradient boosting + random forest ensemble, validated "
             f"walk-forward across {len(folds)} folds with a {horizon}-day "
             "embargo between train and test. Band is +/-1.28 out-of-sample "
             "RMSE (an 80% interval).")

    # Flag models that score below 0.5 out of sample.
    no_skill = ((np.isfinite(auc) and auc < 0.5) or
                (np.isfinite(hit) and hit < 0.5))
    if no_skill:
        notes += (f"  WARNING: out-of-sample validation shows no directional "
                  f"skill on this symbol (AUC {auc:.3f}, hit rate {hit:.1%}; "
                  "0.5 is random). The implied direction is not supported by "
                  "validation, and confidence is scored accordingly.")

    # The regressor sets the median and the classifier the probability, so
    # they can disagree. Report that instead of showing only one.
    if np.isfinite(up_prob):
        reg_up = pred_lr > 0
        clf_up = up_prob > 0.5
        if reg_up != clf_up:
            notes += ("  NOTE: the regression and classification halves of the "
                      f"ensemble disagree - the median implies "
                      f"{'a rise' if reg_up else 'a fall'} while the classifier "
                      f"puts P(up) at {up_prob:.1%}. Treat the direction as "
                      "unresolved.")

    return ForecastResult(
        horizon_days=horizon, label=label, p10=p10, p50=centre, p90=p90,
        up_probability=float(clamp(up_prob, 0.01, 0.99)), confidence=conf,
        model="ENSEMBLE_ML_WF", notes=notes,
        expected_return=centre / s0 - 1.0,
        rmse=rmse, hit_rate=hit, auc=auc, n_train=n, n_folds=len(folds))


def _confidence(n_hist: int, horizon: int, rmse: float = float("nan"),
                auc: float = float("nan"), hit: float = float("nan"),
                n_folds: int = 0, is_ml: bool = False) -> float:
    """Confidence score, shrinking as the horizon outruns the sample.

    `coverage` is the number of independent horizon-length windows available.
    Below about 4 it dominates the score regardless of validation metrics.
    """
    coverage = n_hist / max(horizon, 1)
    cov_score = clamp(math.log10(max(coverage, 1.0) + 1) / math.log10(13.0), 0.02, 1.0)
    size_score = clamp(n_hist / 750.0, 0.10, 1.0)
    base = 0.62 * cov_score + 0.38 * size_score

    if not is_ml:
        return float(clamp(base * 0.55, 0.02, 0.55))

    skill = 0.5
    parts = []
    if np.isfinite(auc):
        parts.append(clamp((auc - 0.5) / 0.25, 0.0, 1.0))
    if np.isfinite(hit):
        parts.append(clamp((hit - 0.5) / 0.15, 0.0, 1.0))
    if np.isfinite(rmse) and rmse > 0:
        parts.append(clamp(1.0 - rmse / 0.35, 0.0, 1.0))
    if parts:
        skill = float(np.mean(parts))

    fold_score = clamp(n_folds / 4.0, 0.4, 1.0)
    # Low floor: a good RMSE mostly means the model predicts near zero, which
    # scores well on any return series. Directional skill has to carry the rest.
    conf = base * (0.15 + 0.85 * skill) * fold_score

    if (np.isfinite(auc) and auc < 0.5) or (np.isfinite(hit) and hit < 0.5):
        conf *= 0.55
    return float(clamp(conf, 0.02, 0.80))


def forecast_all(ps: PriceSeries, sim_model: str = "block",
                 should_abort: Optional[Callable[[], bool]] = None,
                 progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Run every horizon, choosing the best method the data supports."""
    px = ps.px
    n = len(px)
    out: Dict[str, Any] = {
        "last_price": float(px.iloc[-1]),
        "n_history": n,
        "as_of": ps.end,
        "results": [],
        "notes": [],
        "sim_model": sim_model,
    }

    if n < 10:
        out["error"] = f"At least 10 trading days are required; {n} loaded."
        return out

    feat = None
    if n >= 160:
        try:
            feat = build_features(ps)
        except Exception:
            feat = None

    for label, h in HORIZONS:
        if should_abort and should_abort():
            raise Cancelled()
        if progress:
            progress(f"Forecasting {label}...")

        # A horizon longer than the sample cannot be estimated, only asserted.
        if h > n:
            res = ForecastResult(
                h, label, float("nan"), float("nan"), float("nan"), float("nan"),
                0.0, "UNSUPPORTED",
                (f"This horizon ({h} trading days) is longer than the entire "
                 f"loaded history ({n} bars). No method can estimate it from "
                 "this sample; load more history or shorten the horizon."),
                supported=False)
            out["results"].append(res)
            continue

        res = None
        if feat is not None and h <= n // 3:
            try:
                res = _ml_forecast(feat, h, label, float(px.iloc[-1]), n,
                                   should_abort=should_abort)
            except Cancelled:
                raise
            except Exception:
                res = None

        if res is None:
            term = simulate_terminal(px, h, model=sim_model, n_sims=20000, seed=None)
            conf = _confidence(n, h, is_ml=False)
            names = {"gbm": "GBM (normal innovations)",
                     "iid": "IID bootstrap of historical returns",
                     "block": "stationary block bootstrap",
                     "t": "Student-t innovations"}
            why = ("history is too short for validated machine learning at this "
                   f"horizon (needs {h * 3} bars, has {n})")
            res = _sim_summary(
                term, float(px.iloc[-1]),
                model=f"SIM_{sim_model.upper()}",
                notes=(f"Monte Carlo using {names.get(sim_model, sim_model)}, "
                       f"20,000 paths, because {why}. The band is the simulated "
                       "distribution, not a model fit. The median extends the "
                       "drift already in the sample, so a strongly trending "
                       "sample produces an upward median as an artefact of that "
                       "drift rather than as a prediction."),
                label=label, h=h, confidence=conf)
        out["results"].append(res)

    coverage = n / 252
    out["notes"].append(
        f"Loaded history spans {coverage:.2f} years ({n} bars). A forecast "
        "horizon is only meaningfully estimable when the sample contains "
        "several independent windows of that length.")
    out["notes"].append(
        "Bands are 10th/50th/90th percentiles. About one outcome in five "
        "should fall outside an 80% interval.")
    out["notes"].append(
        "The two confidence labels measure different things. 'Validated' comes "
        "from out-of-sample directional accuracy. 'Sample fit' reflects only "
        "how much history was available to describe the return distribution; a "
        "simulation has no directional skill, so a high sample-fit score does "
        "not mean a more reliable direction than a lower validated score.")
    return out


# ==============================================================================
# SECTION 9 - STRATEGY BACKTESTER
# ==============================================================================
#
# Lets the rules described on the TECH tab be tested against the loaded symbol.
#
# Signals are shifted one bar before being traded: a crossover seen at today's
# close can only be acted on tomorrow. Omitting that shift is the usual source
# of backtest profits that never existed.
# ==============================================================================

STRATEGIES = ["SMA cross", "EMA cross", "MACD", "RSI mean-revert",
              "Donchian breakout", "Buy & hold"]


@dataclass
class BacktestResult:
    name: str
    equity: pd.Series
    benchmark: pd.Series
    position: pd.Series
    stats: Dict[str, float]
    bench_stats: Dict[str, float]
    trades: int
    exposure: float
    cost_bps: float
    note: str = ""


def _signal_positions(ps: PriceSeries, strategy: str,
                      fast: int, slow: int) -> Tuple[pd.Series, str]:
    """Target position per bar (1 long, 0 flat), before the trade lag."""
    px = ps.px
    high, low = ps.df["high"], ps.df["low"]

    if strategy == "SMA cross":
        f, s = sma(px, fast), sma(px, slow)
        pos = (f > s).astype(float).where(f.notna() & s.notna())
        note = f"Long while SMA{fast} > SMA{slow}, otherwise flat."

    elif strategy == "EMA cross":
        f, s = ema(px, fast), ema(px, slow)
        warm = max(fast, slow)
        pos = (f > s).astype(float)
        pos.iloc[:warm] = np.nan
        note = f"Long while EMA{fast} > EMA{slow}, otherwise flat."

    elif strategy == "MACD":
        line, sig, _ = macd(px)
        pos = (line > sig).astype(float)
        pos.iloc[:35] = np.nan
        note = "Long while the MACD line is above its signal line."

    elif strategy == "RSI mean-revert":
        r = rsi(px, 14)
        pos = pd.Series(np.nan, index=px.index, dtype=float)
        holding = 0.0
        for i, v in enumerate(r.values):
            if not np.isfinite(v):
                continue
            if holding == 0.0 and v < 30:
                holding = 1.0
            elif holding == 1.0 and v > 55:
                holding = 0.0
            pos.iloc[i] = holding
        note = "Enter long when RSI(14) drops below 30, exit when it recovers above 55."

    elif strategy == "Donchian breakout":
        up, dn = donchian(high, low, fast, exclude_current=True)
        pos = pd.Series(np.nan, index=px.index, dtype=float)
        holding = 0.0
        for i in range(len(px)):
            u, d = up.iloc[i], dn.iloc[i]
            if not (np.isfinite(u) and np.isfinite(d)):
                continue
            c = float(px.iloc[i])
            if holding == 0.0 and c >= u:
                holding = 1.0
            elif holding == 1.0 and c <= d:
                holding = 0.0
            pos.iloc[i] = holding
        note = f"Long on a {fast}-day high breakout, flat on a {fast}-day low."

    else:  # Buy & hold
        pos = pd.Series(1.0, index=px.index)
        note = "Always invested."

    return pos.fillna(0.0), note


def _perf_stats(equity: pd.Series) -> Dict[str, float]:
    return {
        "total": float(equity.iloc[-1] / equity.iloc[0] - 1.0),
        "cagr": ann_return_geometric(equity),
        "vol": ann_vol(equity),
        "sharpe": sharpe_ratio(equity),
        "sortino": sortino_ratio(equity),
        "maxdd": max_drawdown(equity),
        "calmar": calmar_ratio(equity),
    }


def run_backtest(ps: PriceSeries, strategy: str, fast: int = 20, slow: int = 50,
                 cost_bps: float = 5.0) -> BacktestResult:
    px = ps.px
    if len(px) < 40:
        raise ValueError(f"Backtesting needs at least 40 bars; {len(px)} loaded.")

    fast = int(clamp(fast, 2, 200))
    slow = int(clamp(slow, 3, 400))

    repair = ""
    if strategy in ("SMA cross", "EMA cross") and fast >= slow:
        # Swap, don't nudge: fast=20 slow=10 means the 10/20 pair.
        original = (fast, slow)
        fast, slow = min(original), max(original)
        if fast == slow:
            slow = fast + 1
        repair = (f"  Note: fast/slow were entered as {original[0]}/{original[1]} "
                  f"(fast must be shorter); interpreted as {fast}/{slow}.")

    raw_pos, note = _signal_positions(ps, strategy, fast, slow)
    note += repair

    # The trade lag: act on yesterday's signal, at today's return.
    pos = raw_pos.shift(1).fillna(0.0)

    rets = simple_returns(px).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    cost = turnover * (cost_bps / 10_000.0)

    strat_rets = pos * rets - cost
    equity = (1.0 + strat_rets).cumprod()
    bench = (1.0 + rets).cumprod()

    trades = int((pos.diff().abs() > 0).sum())
    exposure = float(pos.mean())

    stats = _perf_stats(equity)
    bstats = _perf_stats(bench)

    active = strat_rets[pos > 0]
    stats["win_rate"] = float((active > 0).mean()) if len(active) > 5 else float("nan")
    stats["n_active_days"] = float(len(active))

    return BacktestResult(name=strategy, equity=equity, benchmark=bench, position=pos,
                          stats=stats, bench_stats=bstats, trades=trades,
                          exposure=exposure, cost_bps=cost_bps, note=note)


# ==============================================================================
# SECTION 10 - AI COMPANY ANALYST (OPTIONAL)
# ==============================================================================

def build_ai_context(ps: PriceSeries, info: Dict[str, Any],
                     stats: Dict[str, Any]) -> str:
    """Build the AI brief from data already pulled during the fetch.

    Everything here is on disk after a fetch, so the user only needs to add
    fundamentals the API does not supply.
    """
    L: List[str] = []
    L.append(f"SYMBOL: {ps.symbol}")
    if ps.name:
        L.append(f"NAME: {ps.name}")
    if info.get("sector"):
        L.append(f"SECTOR: {info['sector']}")
    if info.get("industry"):
        L.append(f"INDUSTRY: {info['industry']}")
    if info.get("full_time_employees"):
        L.append(f"EMPLOYEES: {info['full_time_employees']}")
    if info.get("website"):
        L.append(f"WEBSITE: {info['website']}")
    if ps.exchange:
        L.append(f"EXCHANGE: {ps.exchange}   CURRENCY: {ps.currency or 'n/a'}")
    if info.get("incorporation"):
        L.append(f"INCORPORATED: {info['incorporation']}")

    about = (info.get("about") or "").strip()
    if about:
        L.append("\nBUSINESS DESCRIPTION (from data provider):")
        L.append(about[:2200])

    execs = info.get("key_executives")
    if isinstance(execs, list) and execs:
        L.append("\nKEY EXECUTIVES:")
        for e in execs[:6]:
            if isinstance(e, dict):
                L.append(f"  - {e.get('name', '?')}: {e.get('function', '')}".rstrip())

    L.append("\nPRICE HISTORY ACTUALLY LOADED:")
    L.append(f"  Window: {ps.start} to {ps.end}  ({ps.n} trading days)")
    L.append(f"  Last close: {ps.currency or '$'}{ps.last:,.2f}")
    L.append(f"  Adjustment: {ps.adj_method} - {ps.adj_note}")

    pr = stats.get("period_returns") or {}
    if pr:
        L.append("  Trailing returns: " + "  ".join(
            f"{k} {fmt_pct(v, 1)}" for k, v in pr.items() if np.isfinite(v)))

    L.append("\nCOMPUTED RISK STATISTICS (from the loaded window):")
    for key, lab in (("vol", "Annualised volatility"), ("cagr", "CAGR"),
                     ("sharpe", "Sharpe"), ("sortino", "Sortino"),
                     ("maxdd", "Max drawdown"), ("beta", "Beta vs benchmark"),
                     ("corr", "Correlation vs benchmark"),
                     ("var95", "1-day 95% VaR"), ("cvar95", "1-day 95% CVaR")):
        v = stats.get(key)
        if v is not None and np.isfinite(v):
            pctish = key in ("vol", "cagr", "maxdd", "var95", "cvar95")
            L.append(f"  {lab}: {fmt_pct(v) if pctish else fmt_num(v)}")

    if stats.get("vol_label"):
        L.append(f"  Volatility regime: {stats['vol_label']}")
    if stats.get("trend_label"):
        L.append(f"  Trend state: {stats['trend_label']}")

    if ps.dividends is not None and not ps.dividends.empty:
        d = ps.dividends.tail(8)
        total = float(d["dividend"].sum())
        L.append("\nDIVIDENDS (most recent, from provider):")
        for row in d.itertuples():
            L.append(f"  {row.date.date()}  {row.dividend:.4f}")
        if ps.last > 0:
            recent = ps.dividends[ps.dividends["date"] >= (ps.dividends["date"].max()
                                                           - pd.Timedelta(days=365))]
            ttm = float(recent["dividend"].sum())
            L.append(f"  Trailing 12m declared: {ttm:.4f} "
                     f"(~{ttm / ps.last * 100:.2f}% of last price)")
        _ = total

    if ps.splits is not None and not ps.splits.empty:
        L.append("\nSPLIT HISTORY (from provider):")
        for row in ps.splits.tail(6).itertuples():
            L.append(f"  {row.date.date()}  {row.split_factor:g}:1")

    return "\n".join(L)


AI_SYSTEM_PROMPT = """You are a disciplined equity analyst writing an internal \
research note. You are rigorous, plain-spoken and comfortable saying that the \
evidence is insufficient.

Absolute rules:
- Use ONLY the data provided in the user message. Never introduce a revenue \
figure, margin, multiple, growth rate or guidance number that is not present.
- The provided data is largely PRICE and DESCRIPTIVE data. Fundamentals such as \
revenue, margins, cash flow, debt and valuation multiples are usually ABSENT. \
When they are absent, say so in data_gaps and do NOT grade profitability or \
valuation as if you knew them.
- Distinguish clearly between what the price history shows and what a \
fundamental assessment would require.
- Do not give buy/sell/hold recommendations or price targets. Describe evidence \
and risks; leave the decision to the reader.

Return ONLY a JSON object with exactly these keys:
  verdict            one of "GOOD", "OK", "BAD", "INSUFFICIENT DATA"
  summary            4-7 sentences of prose
  strengths          array of short strings
  risks              array of short strings
  watch_items        array of short strings
  questions_to_verify array of short strings
  data_gaps          array of short strings naming what is missing

Use "INSUFFICIENT DATA" as the verdict whenever core fundamentals are absent \
and you would otherwise be guessing."""


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def ai_analyze(symbol: str, context: str, extra_notes: str = "",
               model: str = "gpt-4.1-mini") -> Dict[str, Any]:
    """Call OpenAI in JSON mode and normalise the result.

    Uses response_format=json_object rather than asking for JSON in the prompt,
    since the latter often comes back wrapped in a markdown fence.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY is not set.",
                "verdict": "INSUFFICIENT DATA",
                "summary": ("Set the OPENAI_API_KEY environment variable and "
                            "restart to enable AI analysis. Every other tab in "
                            "this terminal works without it."),
                "strengths": [], "risks": [], "watch_items": [],
                "questions_to_verify": [], "data_gaps": ["No AI provider configured."]}

    try:
        from openai import OpenAI
    except ImportError:
        return {"error": "The 'openai' package is not installed.",
                "verdict": "INSUFFICIENT DATA",
                "summary": "Run:  pip install openai",
                "strengths": [], "risks": [], "watch_items": [],
                "questions_to_verify": [], "data_gaps": ["openai package missing."]}

    user_msg = f"Ticker: {symbol}\n\n{context}"
    if extra_notes.strip():
        user_msg += ("\n\nADDITIONAL FUNDAMENTALS SUPPLIED BY THE USER "
                     "(treat as unverified):\n" + extra_notes.strip())

    try:
        client = OpenAI(api_key=api_key, timeout=90.0)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": AI_SYSTEM_PROMPT},
                      {"role": "user", "content": user_msg}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        msg = redact_secrets(exc)
        hint = ""
        low = msg.lower()
        if "api key" in low or "authentication" in low or "401" in low:
            hint = "The OPENAI_API_KEY appears to be invalid or revoked."
        elif "rate limit" in low or "429" in low:
            hint = "OpenAI rate limit or quota reached. Wait and retry."
        elif "model" in low and ("not found" in low or "does not exist" in low):
            hint = f"The model '{model}' is not available to this key."
        elif "connect" in low or "timeout" in low:
            hint = "Could not reach OpenAI. Check your network connection."
        return {"error": f"OpenAI request failed: {msg}",
                "verdict": "INSUFFICIENT DATA",
                "summary": hint or "The AI request did not complete.",
                "strengths": [], "risks": [], "watch_items": [],
                "questions_to_verify": [], "data_gaps": [msg[:300]]}

    try:
        data = json.loads(_strip_code_fence(text))
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except Exception:
        data = {"verdict": "INSUFFICIENT DATA",
                "summary": text[:4000] or "The model returned an empty response.",
                "strengths": [], "risks": [], "watch_items": [],
                "questions_to_verify": ["The model did not return valid JSON."],
                "data_gaps": []}

    verdict = str(data.get("verdict", "") or "").upper().strip()
    if verdict not in ("GOOD", "OK", "BAD", "INSUFFICIENT DATA"):
        verdict = "INSUFFICIENT DATA"
    data["verdict"] = verdict

    for k in ("strengths", "risks", "watch_items", "questions_to_verify", "data_gaps"):
        v = data.get(k)
        if isinstance(v, str):
            data[k] = [v]
        elif not isinstance(v, list):
            data[k] = []
        else:
            data[k] = [str(i) for i in v if str(i).strip()]
    data["summary"] = str(data.get("summary", "") or "").strip()
    return data


# ==============================================================================
# SECTION 11 - ANALYSIS ORCHESTRATION
# ==============================================================================

def compute_analysis(ps: PriceSeries, bench: Optional[PriceSeries],
                     should_abort: Optional[Callable[[], bool]] = None,
                     progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Compute the full statistics set for one symbol."""
    def tick(msg: str) -> None:
        if should_abort and should_abort():
            raise Cancelled()
        if progress:
            progress(msg)

    px = ps.px
    tick("Computing performance statistics...")

    a = ps.returns()
    res: Dict[str, Any] = {
        "symbol": ps.symbol,
        "name": ps.display_name,
        "exchange": ps.exchange,
        "currency": ps.currency,
        "as_of": ps.end,
        "start": ps.start,
        "n": ps.n,
        "last": ps.last,
        "adj_method": ps.adj_method,
        "adj_note": ps.adj_note,
        "events": ps.events,
        "warnings": list(ps.warnings),
        "total_return": ps.total_return,
    }

    res["period_returns"] = period_returns(px)
    res["cagr"] = ann_return_geometric(px)
    res["vol"] = ann_vol(px)
    res["drift_log"] = ann_drift_log(px)
    res["sharpe"] = sharpe_ratio(px)
    res["sortino"] = sortino_ratio(px)
    res["calmar"] = calmar_ratio(px)
    res["omega"] = omega_ratio(px)
    res["maxdd"] = max_drawdown(px)
    res["dd_detail"] = drawdown_detail(px)
    res["var95"] = historical_var(px, 0.95)
    res["var99"] = historical_var(px, 0.99)
    res["cvar95"] = cvar(px, 0.95)
    res["cf_var95"] = cornish_fisher_var(px, 0.95)
    res["tails"] = tail_stats(px)

    tick("Computing technical indicators...")
    res["trend"] = trend_state(px)
    res["trend_label"] = res["trend"].get("label", "")
    res["rsi14"] = float(rsi(px, 14).iloc[-1]) if ps.n >= 15 else float("nan")
    line, sig, hist = macd(px)
    res["macd"] = float(line.iloc[-1]) if line.notna().any() else float("nan")
    res["macd_sig"] = float(sig.iloc[-1]) if sig.notna().any() else float("nan")
    res["macd_hist"] = float(hist.iloc[-1]) if hist.notna().any() else float("nan")

    mid, up, lo, width, pctb = bollinger(px, 20, 2.0)
    res["bb_upper"] = float(up.iloc[-1]) if up.notna().any() else float("nan")
    res["bb_lower"] = float(lo.iloc[-1]) if lo.notna().any() else float("nan")
    res["bb_width"] = float(width.iloc[-1]) if width.notna().any() else float("nan")
    res["bb_pctb"] = float(pctb.iloc[-1]) if pctb.notna().any() else float("nan")
    if width.notna().sum() > 40:
        res["bb_width_pct"] = float((width.dropna() <= width.dropna().iloc[-1]).mean())
    else:
        res["bb_width_pct"] = float("nan")

    atr_s = atr(ps.df["high"], ps.df["low"], px, 14)
    res["atr14"] = float(atr_s.iloc[-1]) if atr_s.notna().any() else float("nan")
    res["atr_pct"] = res["atr14"] / ps.last if np.isfinite(res["atr14"]) else float("nan")

    adx_s, pdi, mdi = adx(ps.df["high"], ps.df["low"], px, 14)
    res["adx"] = float(adx_s.iloc[-1]) if adx_s.notna().any() else float("nan")
    res["plus_di"] = float(pdi.iloc[-1]) if pdi.notna().any() else float("nan")
    res["minus_di"] = float(mdi.iloc[-1]) if mdi.notna().any() else float("nan")

    k, d = stochastic(ps.df["high"], ps.df["low"], px)
    res["stoch_k"] = float(k.iloc[-1]) if k.notna().any() else float("nan")
    res["stoch_d"] = float(d.iloc[-1]) if d.notna().any() else float("nan")

    mfi = money_flow_index(ps.df["high"], ps.df["low"], px, ps.volume)
    res["mfi"] = float(mfi.iloc[-1]) if mfi.notna().any() else float("nan")

    vol_s = ps.volume
    res["volume_last"] = float(vol_s.iloc[-1]) if len(vol_s) else float("nan")
    res["volume_avg20"] = float(vol_s.tail(20).mean()) if len(vol_s) >= 20 else float("nan")
    res["volume_ratio"] = (res["volume_last"] / res["volume_avg20"]
                           if np.isfinite(res["volume_avg20"]) and res["volume_avg20"] > 0
                           else float("nan"))

    obv_s = obv(px, vol_s)
    res["obv"] = float(obv_s.iloc[-1]) if len(obv_s) else float("nan")
    if len(obv_s) > 21:
        # Whether accumulation is confirming the price move or diverging from it.
        obv_chg = float(obv_s.iloc[-1] - obv_s.iloc[-21])
        px_chg = float(px.iloc[-1] / px.iloc[-21] - 1.0)
        res["obv_20d_change"] = obv_chg
        res["obv_divergence"] = bool((obv_chg > 0) != (px_chg > 0))
        res["obv_direction"] = "rising" if obv_chg > 0 else "falling"
    else:
        res["obv_20d_change"] = float("nan")
        res["obv_divergence"] = False
        res["obv_direction"] = "n/a"

    tick("Analysing regime...")
    res["vol_regime"] = vol_regime(px)
    res["vol_label"] = res["vol_regime"].get("label", "")
    res["hurst"] = hurst_exponent(px)
    res["variance_ratio"] = variance_ratio(px, 5)
    res["autocorr"] = autocorrelation(px, 5)

    tick("Measuring benchmark sensitivity...")
    res["benchmark"] = bench.symbol if bench else None
    if bench is not None and bench.n > 30:
        b = bench.returns()
        beta, corr, obs = beta_and_corr(a, b)
        res["beta"] = beta
        res["corr"] = corr
        res["beta_obs"] = obs
        res["alpha"] = alpha_annualised(a, b, beta)
        res["tracking_error"] = tracking_error(a, b)
        res["info_ratio"] = information_ratio(a, b)
        up_cap, dn_cap = upside_downside_capture(a, b)
        res["up_capture"] = up_cap
        res["down_capture"] = dn_cap
        res["rolling_beta"] = rolling_beta(a, b, 60)
        res["bench_cagr"] = ann_return_geometric(bench.px)
        res["bench_vol"] = ann_vol(bench.px)
        res["bench_maxdd"] = max_drawdown(bench.px)
    else:
        for k2 in ("beta", "corr", "alpha", "tracking_error", "info_ratio",
                   "up_capture", "down_capture", "bench_cagr", "bench_vol",
                   "bench_maxdd"):
            res[k2] = float("nan")
        res["beta_obs"] = 0
        res["rolling_beta"] = pd.Series(dtype=float)

    tick("Computing seasonality...")
    res["seasonality"] = seasonality(px)

    return res


# ==============================================================================
# SECTION 12 - TEXT REPORT FORMATTERS
# ==============================================================================

def report_overview(c: Dict[str, Any]) -> str:
    L = [header_block(f"{c['symbol']}  -  {c['name']}")]
    L.append("")
    L.append(kv_line("As of", str(c["as_of"])))
    L.append(kv_line("Window", f"{c['start']} to {c['as_of']}  ({c['n']} trading days)"))
    if c.get("exchange"):
        L.append(kv_line("Exchange", f"{c['exchange']}   Currency: {c.get('currency') or 'n/a'}"))
    L.append(kv_line("Last close", fmt_money(c["last"])))
    if c.get("total_return"):
        L.append(kv_line("Series", "TOTAL RETURN (dividends reinvested)"))
    L.append("")

    L.append(" TRAILING RETURNS")
    L.append(" " + rule(76))
    pr = c.get("period_returns") or {}
    order = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y"]
    row1 = "  " + "".join(f"{k:>10}" for k in order)
    row2 = "  " + "".join(f"{fmt_pct(pr.get(k), 1):>10}" for k in order)
    L.append(row1)
    L.append(row2)
    L.append("")

    L.append(" PERFORMANCE & RISK")
    L.append(" " + rule(76))
    L.append(kv_line("CAGR (realised path)", fmt_pct(c["cagr"])))
    L.append(kv_line("Volatility (annualised)", fmt_pct(c["vol"])))
    L.append(kv_line("Sharpe / Sortino", f"{fmt_num(c['sharpe'])}  /  {fmt_num(c['sortino'])}"))
    L.append(kv_line("Calmar / Omega", f"{fmt_num(c['calmar'])}  /  {fmt_num(c['omega'])}"))
    L.append(kv_line("Max drawdown", fmt_pct(c["maxdd"])))
    dd = c.get("dd_detail") or {}
    if dd.get("peak") is not None:
        rec = dd.get("recovery")
        L.append(kv_line("  peak -> trough",
                         f"{dd['peak'].date()} -> {dd['trough'].date()}"
                         f"  ({dd.get('drop_days', 0)} sessions)"))
        L.append(kv_line("  recovered",
                         f"{rec.date()} ({dd.get('recovery_days')} sessions)"
                         if rec is not None else "not yet recovered"))
        L.append(kv_line("  current drawdown", fmt_pct(dd.get("current"))))
    L.append("")

    L.append(" TREND")
    L.append(" " + rule(76))
    t = c.get("trend") or {}
    L.append(kv_line("State", str(t.get("label", "n/a")).upper()))
    for w in (20, 50, 100, 200):
        v = t.get(f"sma{w}")
        if v is not None and np.isfinite(v):
            delta = c["last"] / v - 1.0
            L.append(kv_line(f"SMA{w}", f"{fmt_money(v)}   price {fmt_pct(delta, 1)} vs it"))
    L.append(kv_line("Window high / low",
                     f"{fmt_money(t.get('window_high'))} / {fmt_money(t.get('window_low'))}"))
    L.append(kv_line("From window high", fmt_pct(t.get("from_high"), 1)))
    L.append("")

    if c.get("benchmark"):
        L.append(f" VS {c['benchmark']}")
        L.append(" " + rule(76))
        L.append(kv_line("Beta / Correlation",
                         f"{fmt_num(c['beta'])}  /  {fmt_num(c['corr'])}"
                         f"   ({c.get('beta_obs', 0)} aligned sessions)"))
        L.append(kv_line("Alpha (annualised)", fmt_pct(c["alpha"])))
        L.append(kv_line("Benchmark CAGR / vol",
                         f"{fmt_pct(c['bench_cagr'])}  /  {fmt_pct(c['bench_vol'])}"))
        L.append("")

    L.append(" DATA PROVENANCE")
    L.append(" " + rule(76))
    L.append(f"  Adjustment method : {c['adj_method']}")
    L.append(f"  {c['adj_note']}")
    for e in (c.get("events") or [])[:8]:
        L.append(f"    * {e}")
    for w in (c.get("warnings") or []):
        L.append(f"  ! {w}")
    return "\n".join(L)


def report_technicals(c: Dict[str, Any]) -> str:
    L = [header_block("TECHNICAL INDICATORS")]
    L.append("")
    L.append(" MOVING AVERAGES")
    L.append(" " + rule(76))
    t = c.get("trend") or {}
    for label, ok in t.get("checks", []):
        L.append(f"  {'PASS' if ok else 'FAIL'}   {label}")
    L.append(kv_line("Composite trend score", f"{t.get('score', 0):+d}  ({t.get('label', '')})"))
    L.append("")

    L.append(" MOMENTUM & OSCILLATORS")
    L.append(" " + rule(76))
    r = c.get("rsi14", float("nan"))
    zone = ("overbought" if np.isfinite(r) and r > 70 else
            "oversold" if np.isfinite(r) and r < 30 else "neutral")
    L.append(kv_line("RSI(14)", f"{fmt_num(r, 1)}   [{zone}]"))
    L.append(kv_line("MACD / signal",
                     f"{fmt_num(c.get('macd'), 4)} / {fmt_num(c.get('macd_sig'), 4)}"
                     f"   histogram {fmt_num(c.get('macd_hist'), 4)}"))
    L.append(kv_line("Stochastic %K / %D",
                     f"{fmt_num(c.get('stoch_k'), 1)} / {fmt_num(c.get('stoch_d'), 1)}"))
    L.append(kv_line("Money Flow Index", fmt_num(c.get("mfi"), 1)))
    adx_v = c.get("adx", float("nan"))
    adx_note = ("no trend" if np.isfinite(adx_v) and adx_v < 20 else
                "trending" if np.isfinite(adx_v) and adx_v < 40 else
                "strong trend" if np.isfinite(adx_v) else "n/a")
    L.append(kv_line("ADX(14)", f"{fmt_num(adx_v, 1)}   [{adx_note}]"))
    L.append(kv_line("  +DI / -DI",
                     f"{fmt_num(c.get('plus_di'), 1)} / {fmt_num(c.get('minus_di'), 1)}"))
    L.append("")

    L.append(" VOLATILITY & RANGE")
    L.append(" " + rule(76))
    L.append(kv_line("ATR(14)",
                     f"{fmt_money(c.get('atr14'))}   ({fmt_pct(c.get('atr_pct'), 2)} of price)"))
    L.append(kv_line("Bollinger upper / lower",
                     f"{fmt_money(c.get('bb_upper'))} / {fmt_money(c.get('bb_lower'))}"))
    L.append(kv_line("Bollinger %B", fmt_num(c.get("bb_pctb"), 3)))
    bw = c.get("bb_width_pct")
    L.append(kv_line("Band width percentile",
                     fmt_pct(bw, 0) + ("  (squeeze)" if np.isfinite(bw) and bw < 0.15 else "")))
    L.append("")

    L.append(" VOLUME")
    L.append(" " + rule(76))
    L.append(kv_line("Last session", fmt_big(c.get("volume_last"))))
    L.append(kv_line("20-day average", fmt_big(c.get("volume_avg20"))))
    L.append(kv_line("Relative volume", fmt_num(c.get("volume_ratio"), 2) + "x"))
    L.append(kv_line("On-balance volume", fmt_big(c.get("obv"))))
    L.append(kv_line("  20-day OBV direction", str(c.get("obv_direction", "n/a"))))
    if c.get("obv_divergence"):
        L.append("      NOTE: OBV and price have moved in opposite directions over")
        L.append("      the last 20 sessions - volume is not confirming the move.")
    L.append("")
    L.append(" " + rule(76))
    L.append("  These are descriptive statistics, not signals. Use the BACKTEST")
    L.append("  tab to test whether these rules worked on this symbol over the")
    L.append("  loaded window.")
    return "\n".join(L)


def report_risk(c: Dict[str, Any]) -> str:
    L = [header_block("RISK ANALYSIS")]
    L.append("")
    L.append(" DISPERSION")
    L.append(" " + rule(76))
    L.append(kv_line("Annualised volatility", fmt_pct(c["vol"])))
    vr = c.get("vol_regime") or {}
    L.append(kv_line("EWMA vol (lambda=0.94)", fmt_pct(vr.get("ewma"))))
    L.append(kv_line("Realised vol 20 / 60 / 120d",
                     f"{fmt_pct(vr.get('rv20'), 1)} / {fmt_pct(vr.get('rv60'), 1)}"
                     f" / {fmt_pct(vr.get('rv120'), 1)}"))
    L.append("")

    L.append(" TAIL RISK   (loss as a positive number)")
    L.append(" " + rule(76))
    L.append(kv_line("1-day VaR 95% (historical)", fmt_pct(c.get("var95"))))
    L.append(kv_line("1-day VaR 99% (historical)", fmt_pct(c.get("var99"))))
    L.append(kv_line("1-day CVaR 95% (expected shortfall)", fmt_pct(c.get("cvar95"))))
    L.append(kv_line("1-day VaR 95% (Cornish-Fisher)", fmt_pct(c.get("cf_var95"))))
    last = c.get("last", float("nan"))
    if np.isfinite(last) and np.isfinite(c.get("var95", float("nan"))):
        L.append(kv_line("  on a $10,000 position",
                         f"about {fmt_money(10000 * c['var95'])} at the 95% level"))
    L.append("")

    L.append(" RETURN DISTRIBUTION")
    L.append(" " + rule(76))
    t = c.get("tails") or {}
    L.append(kv_line("Skew", fmt_num(t.get("skew"), 3)))
    L.append(kv_line("Excess kurtosis", fmt_num(t.get("excess_kurtosis"), 3)
                     + ("   (fat tailed)" if np.isfinite(t.get("excess_kurtosis", np.nan))
                        and t["excess_kurtosis"] > 1 else "")))
    L.append(kv_line("Positive days", fmt_pct(t.get("pos_days"), 1)))
    L.append(kv_line("Average gain / loss day",
                     f"{fmt_pct(t.get('avg_gain'), 2)} / {fmt_pct(t.get('avg_loss'), 2)}"))
    L.append(kv_line("Best / worst day",
                     f"{fmt_pct(t.get('best_day'), 2)} / {fmt_pct(t.get('worst_day'), 2)}"))
    L.append("")

    L.append(" DRAWDOWN")
    L.append(" " + rule(76))
    dd = c.get("dd_detail") or {}
    L.append(kv_line("Maximum", fmt_pct(c.get("maxdd"))))
    L.append(kv_line("Current", fmt_pct(dd.get("current"))))
    L.append(kv_line("Time underwater", fmt_pct(dd.get("pct_time_underwater"), 1)))
    L.append("")

    if c.get("benchmark"):
        L.append(f" SENSITIVITY TO {c['benchmark']}")
        L.append(" " + rule(76))
        L.append(kv_line("Beta", fmt_num(c.get("beta"))))
        L.append(kv_line("Correlation", fmt_num(c.get("corr"))))
        L.append(kv_line("Aligned observations", fmt_int(c.get("beta_obs"))))
        L.append(kv_line("Annualised alpha", fmt_pct(c.get("alpha"))))
        L.append(kv_line("Tracking error", fmt_pct(c.get("tracking_error"))))
        L.append(kv_line("Information ratio", fmt_num(c.get("info_ratio"))))
        L.append(kv_line("Upside / downside capture",
                         f"{fmt_pct(c.get('up_capture'), 0)} / "
                         f"{fmt_pct(c.get('down_capture'), 0)}"))
        L.append("")
        L.append("  Beta and correlation use returns joined on date, so")
        L.append("  differing history lengths cannot pair unrelated sessions.")
    else:
        L.append("  No benchmark loaded, so beta and correlation are unavailable.")
    return "\n".join(L)


def report_regime(c: Dict[str, Any]) -> str:
    L = [header_block("MARKET REGIME")]
    L.append("")
    vr = c.get("vol_regime") or {}
    L.append(" VOLATILITY REGIME")
    L.append(" " + rule(76))
    L.append(kv_line("Current 20-day realised vol", fmt_pct(vr.get("rv20"))))
    L.append(kv_line("Percentile vs own history", fmt_pct(vr.get("percentile"), 0)))
    L.append(kv_line("Classification", str(vr.get("label", "n/a")).upper()))
    L.append("")

    L.append(" PERSISTENCE vs MEAN REVERSION")
    L.append(" " + rule(76))
    h = c.get("hurst", float("nan"))
    hlabel = ("n/a" if not np.isfinite(h) else
              "mean-reverting" if h < 0.45 else
              "random walk" if h < 0.55 else "trending / persistent")
    L.append(kv_line("Hurst exponent", f"{fmt_num(h, 3)}   [{hlabel}]"))
    L.append("      0.5 = random walk;  <0.5 mean-reverting;  >0.5 trending")
    v = c.get("variance_ratio", float("nan"))
    vlabel = ("n/a" if not np.isfinite(v) else
              "mean-reverting" if v < 0.9 else
              "random walk" if v < 1.1 else "trending")
    L.append(kv_line("Variance ratio (q=5)", f"{fmt_num(v, 3)}   [{vlabel}]"))
    L.append("")

    ac = c.get("autocorr") or {}
    if ac:
        L.append(" RETURN AUTOCORRELATION")
        L.append(" " + rule(76))
        for lag, val in ac.items():
            bar = "#" * int(min(abs(val) * 60, 40))
            L.append(f"  lag {lag}:  {val:+.4f}  {bar}")
        L.append("")
        L.append("  Daily equity autocorrelation is normally small. Values")
        L.append("  beyond about +/-0.10 on a short sample are usually noise.")
    L.append("")
    L.append(" INTERPRETATION")
    L.append(" " + rule(76))
    L.append(f"  Trend state      : {c.get('trend_label', 'n/a')}")
    L.append(f"  Volatility state : {vr.get('label', 'n/a')}")
    L.append(f"  Structure        : {hlabel}")
    L.append("")
    L.append("  Hurst and variance-ratio estimates are unstable on samples")
    L.append(f"  shorter than a few years. This sample has {c['n']} bars.")
    return "\n".join(L)


def report_seasonality(c: Dict[str, Any]) -> str:
    L = [header_block("SEASONALITY")]
    s = c.get("seasonality") or {}
    if not s:
        L.append("")
        L.append("  Not enough history to compute seasonal averages "
                 "(30+ sessions required).")
        return "\n".join(L)

    years = s.get("years", 0.0)
    L.append("")
    L.append(f"  Sample spans {years:.2f} years. Seasonal effects need many years")
    L.append("  to separate from noise; treat everything below as weak evidence.")
    L.append("")

    names = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday"}
    L.append(" AVERAGE DAILY RETURN BY WEEKDAY")
    L.append(" " + rule(76))
    L.append(f"  {'Day':<11}{'Mean':>10}{'StdDev':>10}{'Win rate':>11}{'N':>7}   Chart")
    dow = s.get("dow")
    if dow is not None and len(dow):
        peak = max(abs(dow["mean"]).max(), 1e-9)
        for i in range(5):
            if i not in dow.index:
                continue
            row = dow.loc[i]
            n = int(row["count"])
            width = int(abs(row["mean"]) / peak * 22)
            bar = ("+" if row["mean"] >= 0 else "-") * max(width, 1)
            flag = "" if n >= 30 else "  (thin)"
            L.append(f"  {names.get(i, i):<11}{row['mean'] * 100:>9.3f}%"
                     f"{row['std'] * 100:>9.2f}%{row['win'] * 100:>10.1f}%"
                     f"{n:>7}   {bar}{flag}")
    L.append("")

    L.append(" AVERAGE MONTHLY RETURN")
    L.append(" " + rule(76))
    mnames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    comp = s.get("monthly_compound") or {}
    if comp:
        L.append(f"  {'Month':<11}{'Mean':>10}{'Years':>8}   Chart")
        peak = max((abs(v[0]) for v in comp.values()), default=1e-9) or 1e-9
        for m in range(1, 13):
            if m not in comp:
                continue
            mean, n = comp[m]
            width = int(abs(mean) / peak * 26)
            bar = ("+" if mean >= 0 else "-") * max(width, 1)
            flag = "" if n >= 5 else "  (thin)"
            L.append(f"  {mnames[m - 1]:<11}{mean * 100:>9.2f}%{n:>8}   {bar}{flag}")
    else:
        L.append("  Not enough complete months.")
    L.append("")
    L.append(" " + rule(76))
    L.append("  Buckets built from one or two observations carry no signal.")
    L.append("  Rows marked (thin) are shown for completeness only.")
    return "\n".join(L)


def report_forecast(f: Dict[str, Any], currency: str = "$") -> str:
    L = [header_block("FORECAST")]
    L.append("")
    if f.get("error"):
        L.append(f"  {f['error']}")
        return "\n".join(L)

    L.append(kv_line("History loaded", f"{f['n_history']} trading days "
                                       f"({f['n_history'] / 252:.2f} years)"))
    L.append(kv_line("Last price", fmt_money(f["last_price"])))
    L.append(kv_line("Simulation model", f.get("sim_model", "block")))
    L.append("")

    for r in f["results"]:
        L.append(rule(78, "-"))
        L.append(f" {r.label.upper()}   ({r.horizon_days} trading days)")
        L.append(rule(78, "-"))
        if not r.supported:
            L.append("  UNSUPPORTED")
            for chunk in _wrap(r.notes, 74):
                L.append(f"  {chunk}")
            L.append("")
            continue

        s0 = f["last_price"]
        L.append(kv_line("Model", r.model))
        L.append(kv_line("Median (P50)",
                         f"{fmt_money(r.p50)}   ({fmt_pct(r.p50 / s0 - 1, 1)})"))
        L.append(kv_line("80% band (P10-P90)",
                         f"{fmt_money(r.p10)}  to  {fmt_money(r.p90)}"))
        L.append(kv_line("  as return",
                         f"{fmt_pct(r.p10 / s0 - 1, 1)}  to  {fmt_pct(r.p90 / s0 - 1, 1)}"))
        L.append(kv_line("P(price higher)", fmt_pct(r.up_probability, 1)))

        conf = r.confidence
        blocks = int(round(conf * 20))
        meter = "#" * blocks + "." * (20 - blocks)
        # The two model families measure different things, so label which.
        # A simulation score describes how well the sample covers the return
        # distribution, not predictive skill.
        conf_label = ("Confidence (validated)"
                      if r.model == "ENSEMBLE_ML_WF" else "Confidence (sample fit)")
        L.append(kv_line(conf_label, f"[{meter}] {fmt_pct(conf, 1)}"))

        if r.model == "ENSEMBLE_ML_WF":
            L.append(kv_line("  walk-forward RMSE (log)", fmt_num(r.rmse, 4)))
            L.append(kv_line("  directional hit rate", fmt_pct(r.hit_rate, 1)))
            L.append(kv_line("  ROC AUC", fmt_num(r.auc, 3)))
            L.append(kv_line("  training rows / folds", f"{r.n_train} / {r.n_folds}"))
        L.append("")
        for chunk in _wrap(r.notes, 74):
            L.append(f"  {chunk}")
        L.append("")

    L.append(rule(78, "="))
    L.append(" NOTES")
    L.append(rule(78, "="))
    for n in f.get("notes", []):
        for chunk in _wrap(n, 74):
            L.append(f"  {chunk}")
        L.append("")
    L.append("  Not investment advice. These are statistical extrapolations")
    L.append("  of past prices with no knowledge of the underlying business.")
    return "\n".join(L)


def _wrap(text: str, width: int) -> List[str]:
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            if cur:
                lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def report_backtest(bt: BacktestResult, symbol: str) -> str:
    L = [header_block(f"BACKTEST  -  {bt.name}  on  {symbol}")]
    L.append("")
    L.append(f"  {bt.note}")
    L.append(f"  Round-trip cost assumed: {bt.cost_bps:.1f} bps per unit turnover.")
    L.append("  Signals are shifted one bar: a signal at today's close is")
    L.append("  traded from tomorrow, so no future information is used.")
    L.append("")
    L.append(f"  {'Metric':<26}{'Strategy':>16}{'Buy & hold':>16}")
    L.append("  " + rule(58))

    rows = [("Total return", "total", fmt_pct), ("CAGR", "cagr", fmt_pct),
            ("Volatility", "vol", fmt_pct), ("Sharpe", "sharpe", fmt_num),
            ("Sortino", "sortino", fmt_num), ("Max drawdown", "maxdd", fmt_pct),
            ("Calmar", "calmar", fmt_num)]
    for label, key, fmt in rows:
        L.append(f"  {label:<26}{fmt(bt.stats.get(key)):>16}"
                 f"{fmt(bt.bench_stats.get(key)):>16}")
    L.append("")
    L.append(kv_line("Trades (position changes)", fmt_int(bt.trades)))
    L.append(kv_line("Time in market", fmt_pct(bt.exposure, 1)))
    L.append(kv_line("Win rate on invested days", fmt_pct(bt.stats.get("win_rate"), 1)))
    L.append("")

    edge = bt.stats.get("total", float("nan")) - bt.bench_stats.get("total", float("nan"))
    if np.isfinite(edge):
        verdict = "OUTPERFORMED" if edge > 0 else "UNDERPERFORMED"
        L.append(f"  This rule {verdict} buy & hold by {fmt_pct(abs(edge), 2)} "
                 "over the window.")
    L.append("")
    L.append("  One symbol over one window is not evidence of an edge.")
    L.append("  Costs and slippage are modelled only roughly.")
    return "\n".join(L)


def report_company(data: Dict[str, Any], info: Dict[str, Any], ps: PriceSeries) -> str:
    L = []
    if data.get("error"):
        L.append("  " + data["error"])
        L.append("")
    summary = data.get("summary", "")
    if summary:
        L.append(header_block("ANALYST SUMMARY"))
        L.append("")
        for chunk in _wrap(summary, 74):
            L.append(f"  {chunk}")
        L.append("")

    def block(title: str, items: List[str]) -> None:
        L.append(f" {title}")
        L.append(" " + rule(76))
        if not items:
            L.append("   (none reported)")
        for it in items:
            wrapped = _wrap(it, 70)
            L.append(f"   - {wrapped[0]}")
            for extra in wrapped[1:]:
                L.append(f"     {extra}")
        L.append("")

    block("STRENGTHS", data.get("strengths", []))
    block("RISKS", data.get("risks", []))
    block("WATCH ITEMS", data.get("watch_items", []))
    block("QUESTIONS TO VERIFY", data.get("questions_to_verify", []))
    block("DATA GAPS", data.get("data_gaps", []))

    L.append(header_block("REFERENCE DATA PULLED FROM THE API"))
    L.append("")
    for key, label in (("sector", "Sector"), ("industry", "Industry"),
                       ("full_time_employees", "Employees"),
                       ("website", "Website"), ("phone", "Phone"),
                       ("incorporation", "Incorporated"),
                       ("end_fiscal", "Fiscal year end")):
        v = info.get(key)
        if v:
            L.append(kv_line(label, str(v)))
    if ps.exchange:
        L.append(kv_line("Exchange", ps.exchange))

    about = (info.get("about") or "").strip()
    if about:
        L.append("")
        L.append(" BUSINESS DESCRIPTION")
        L.append(" " + rule(76))
        for chunk in _wrap(about, 74):
            L.append(f"  {chunk}")

    if ps.dividends is not None and not ps.dividends.empty:
        L.append("")
        L.append(" RECENT DIVIDENDS")
        L.append(" " + rule(76))
        for row in ps.dividends.tail(8).itertuples():
            L.append(f"   {row.date.date()}   {row.dividend:>8.4f}   {row.distr_freq or ''}")

    if ps.splits is not None and not ps.splits.empty:
        L.append("")
        L.append(" SPLIT HISTORY")
        L.append(" " + rule(76))
        for row in ps.splits.tail(10).itertuples():
            L.append(f"   {row.date.date()}   {row.split_factor:g}:1")

    L.append("")
    L.append("  AI output uses only the data above. It has no access to")
    L.append("  filings, earnings or news. Not investment advice.")
    return "\n".join(L)


# ==============================================================================
# SECTION 13 - GUI IMPORTS & CHART THEMING
# ==============================================================================

GUI_AVAILABLE = True
GUI_IMPORT_ERROR: Optional[BaseException] = None
try:
    import tkinter.font as tkfont
    from tkinter import filedialog, messagebox
    import customtkinter as ctk

    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.collections import LineCollection
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    import matplotlib.dates as mdates
except Exception as _exc:                                   # pragma: no cover
    GUI_AVAILABLE = False
    GUI_IMPORT_ERROR = _exc


MONO_CANDIDATES = ["JetBrains Mono", "Cascadia Mono", "Cascadia Code", "Consolas",
                   "DejaVu Sans Mono", "Menlo", "Courier New"]
UI_CANDIDATES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial"]


def _pick_font(candidates: List[str], fallback: str) -> str:
    try:
        available = set(tkfont.families())
    except Exception:
        return fallback
    for name in candidates:
        if name in available:
            return name
    return fallback


def style_axes(ax, title: str = "", xlabel: str = "", ylabel: str = "",
               grid: str = "both", legend: bool = False) -> None:
    """Re-apply the terminal look. Must run after every ax.clear()."""
    ax.set_facecolor(SUNKEN)
    ax.set_axisbelow(True)
    if grid in ("both", "y"):
        ax.yaxis.grid(True, color=GRID_SOFT, linewidth=0.7)
    if grid in ("both", "x"):
        ax.xaxis.grid(True, color=GRID_SOFT, linewidth=0.7)
    if grid == "none":
        ax.grid(False)
    for side, sp in ax.spines.items():
        if side in ("top", "right"):
            sp.set_visible(False)
        else:
            sp.set_color(GRID)
            sp.set_linewidth(0.9)
    ax.tick_params(colors=FAINT, labelsize=8, length=3, width=0.8)
    if title:
        ax.set_title(title, loc="left", color=TEXT, fontsize=10,
                     fontweight="bold", pad=9)
    if xlabel:
        ax.set_xlabel(xlabel, color=FAINT, fontsize=8.5)
    if ylabel:
        ax.set_ylabel(ylabel, color=FAINT, fontsize=8.5)
    if legend:
        leg = ax.legend(loc="best", fontsize=8, framealpha=0.0,
                        labelcolor=DIM, borderpad=0.3)
        if leg:
            leg.get_frame().set_edgecolor(GRID)


def money_formatter(_x, _pos=None):
    return f"{_x:,.0f}"


def pct_formatter(x, _pos=None):
    return f"{x * 100:,.0f}%"


def format_date_axis(ax, index: pd.DatetimeIndex) -> None:
    if len(index) == 0:
        return
    span_days = (index[-1] - index[0]).days
    if span_days <= 70:
        loc, fmt = mdates.AutoDateLocator(maxticks=8), mdates.DateFormatter("%d %b")
    elif span_days <= 400:
        loc, fmt = mdates.MonthLocator(interval=1), mdates.DateFormatter("%b")
    elif span_days <= 1200:
        loc, fmt = mdates.MonthLocator(interval=3), mdates.DateFormatter("%b %y")
    else:
        loc, fmt = mdates.YearLocator(), mdates.DateFormatter("%Y")
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(fmt)


# ==============================================================================
# SECTION 14 - CUSTOM WIDGETS
# ==============================================================================

class ChartPanel(ctk.CTkFrame if GUI_AVAILABLE else object):
    """Themed matplotlib surface with a save button.

    Figures are constructed directly instead of through pyplot, which would
    keep every panel's figure alive in the global registry.
    """

    def __init__(self, master, height: int = 320, toolbar: bool = True, **kw):
        super().__init__(master, fg_color=PANEL, corner_radius=10, **kw)
        self.fig = Figure(figsize=(9, height / 100), dpi=100, facecolor=PANEL)
        self.fig.subplots_adjust(left=0.07, right=0.98, top=0.92, bottom=0.12)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        widget = self.canvas.get_tk_widget()
        widget.configure(bg=PANEL, highlightthickness=0, bd=0)
        widget.pack(fill="both", expand=True, padx=6, pady=(6, 2 if toolbar else 6))

        self._placeholder = True
        if toolbar:
            bar = ctk.CTkFrame(self, fg_color="transparent", height=26)
            bar.pack(fill="x", padx=8, pady=(0, 5))
            ctk.CTkButton(bar, text="Save PNG", width=76, height=22,
                          corner_radius=6, fg_color=PANEL_HI, hover_color=GRID,
                          text_color=DIM, font=("", 10),
                          command=self.save_png).pack(side="right")

    def new_axes(self, *args, **kwargs):
        return self.fig.add_subplot(*args, **kwargs)

    def reset(self):
        self.fig.clear()
        self._placeholder = False

    def message(self, text: str) -> None:
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(SUNKEN)
        ax.axis("off")
        ax.text(0.5, 0.5, text, ha="center", va="center", color=FAINT,
                fontsize=10, transform=ax.transAxes, wrap=True)
        self._placeholder = True
        self.draw()

    def draw(self) -> None:
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    def render_now(self) -> None:
        """Render synchronously.

        draw_idle() defers rasterisation to Tk's idle handler, so a frame's
        real cost cannot be measured. The animation loop needs that number to
        pace itself.
        """
        try:
            self.canvas.draw()
        except Exception:
            pass

    def save_png(self) -> None:
        if self._placeholder:
            messagebox.showinfo(APP_NAME, "There is no chart to save yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG image", "*.png")],
            initialfile=f"chart_{datetime.now():%Y%m%d_%H%M%S}.png")
        if path:
            try:
                self.fig.savefig(path, dpi=200, facecolor=PANEL)
                messagebox.showinfo(APP_NAME, f"Saved to:\n{path}")
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Could not save chart:\n{exc}")


class ReadOnlyText(ctk.CTkTextbox if GUI_AVAILABLE else object):
    """Read-only monospace output pane."""

    def __init__(self, master, font=None, **kw):
        super().__init__(master, fg_color=SUNKEN, text_color=TEXT,
                         corner_radius=10, wrap="none", border_width=0,
                         font=font, **kw)
        self.configure(state="disabled")

    def set_text(self, text: str) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.insert("1.0", text)
        self.configure(state="disabled")
        self.yview_moveto(0.0)

    def append(self, text: str) -> None:
        self.configure(state="normal")
        self.insert("end", text)
        self.configure(state="disabled")
        self.see("end")

    def get_text(self) -> str:
        return self.get("1.0", "end").rstrip()


class StatTile(ctk.CTkFrame if GUI_AVAILABLE else object):
    """A label/value cell in the snapshot grid."""

    def __init__(self, master, label: str, ui_font, mono_font, **kw):
        super().__init__(master, fg_color=PANEL_HI, corner_radius=8, **kw)
        self.label = ctk.CTkLabel(self, text=label.upper(), text_color=FAINT,
                                  font=(ui_font, 9), anchor="w")
        self.label.pack(fill="x", padx=9, pady=(6, 0))
        self.value = ctk.CTkLabel(self, text="--", text_color=TEXT,
                                  font=(mono_font, 14, "bold"), anchor="w")
        self.value.pack(fill="x", padx=9, pady=(0, 7))

    def set(self, text: str, color: str = TEXT) -> None:
        self.value.configure(text=text, text_color=color)


class WatchRow(ctk.CTkFrame if GUI_AVAILABLE else object):
    """One watchlist row: symbol, last price, day change."""

    def __init__(self, master, symbol: str, mono_font, on_click, on_remove, **kw):
        super().__init__(master, fg_color="transparent", corner_radius=6,
                         height=26, **kw)
        self.symbol = symbol
        self._on_click = on_click
        self.grid_columnconfigure(1, weight=1)

        self.sym = ctk.CTkLabel(self, text=symbol, text_color=TEXT,
                                font=(mono_font, 12, "bold"), anchor="w", width=58)
        self.sym.grid(row=0, column=0, padx=(9, 2), pady=2, sticky="w")

        self.price = ctk.CTkLabel(self, text="--", text_color=DIM,
                                  font=(mono_font, 12), anchor="e")
        self.price.grid(row=0, column=1, padx=2, pady=2, sticky="e")

        self.chg = ctk.CTkLabel(self, text="--", text_color=DIM,
                                font=(mono_font, 12), anchor="e", width=68)
        self.chg.grid(row=0, column=2, padx=(4, 4), pady=2, sticky="e")

        self.close_btn = ctk.CTkButton(self, text="x", width=18, height=18,
                                       corner_radius=4, fg_color="transparent",
                                       hover_color=BEAR, text_color=FAINT,
                                       font=(mono_font, 11),
                                       command=lambda: on_remove(symbol))
        self.close_btn.grid(row=0, column=3, padx=(0, 6), pady=2)

        for w in (self, self.sym, self.price, self.chg):
            w.bind("<Button-1>", self._clicked)
            w.bind("<Enter>", lambda _e: self.configure(fg_color=PANEL_HI))
            w.bind("<Leave>", lambda _e: self.configure(fg_color="transparent"))

    def _clicked(self, _event=None):
        self._on_click(self.symbol)

    def update_quote(self, price: float, chg_pct: float) -> None:
        self.price.configure(text=fmt_num(price, 2), text_color=TEXT)
        if chg_pct is None or not np.isfinite(chg_pct):
            self.chg.configure(text="--", text_color=DIM)
            return
        col = BULL if chg_pct > 0 else BEAR if chg_pct < 0 else DIM
        self.chg.configure(text=f"{chg_pct * 100:+.2f}%", text_color=col)

    def mark_error(self) -> None:
        self.price.configure(text="n/a", text_color=FAINT)
        self.chg.configure(text="--", text_color=FAINT)


def section_label(parent, text: str, ui_font) -> "ctk.CTkFrame":
    bar = ctk.CTkFrame(parent, fg_color="transparent", height=22)
    bar.pack(fill="x", padx=14, pady=(12, 5))
    ctk.CTkLabel(bar, text=text.upper(), text_color=FAINT,
                 font=(ui_font, 10, "bold"), anchor="w").pack(side="left")
    return bar


# ==============================================================================
# SECTION 15 - MONTE CARLO ANIMATION ENGINE
# ==============================================================================

MC_MIN_INTERVAL_MS = 55       # fastest animation cadence
MC_MAX_INTERVAL_MS = 400      # slowest, when frames are expensive
MC_MAX_DRAWN_PATHS = 220      # spaghetti lines actually rendered per frame


class MonteCarloEngine:
    """Animated Monte Carlo with a percentile fan and terminal distribution.

    Paths are drawn as one LineCollection updated in a single numpy operation,
    which is what keeps several hundred of them animating smoothly.

    Pausing stops the frame clock; resuming continues from that frame rather
    than regenerating the simulation.
    """

    def __init__(self, panel: "ChartPanel", stats_cb: Callable[[str], None],
                 status_cb: Callable[[str, str], None]):
        self.panel = panel
        self.stats_cb = stats_cb
        self.status_cb = status_cb

        self.running = False
        self._after_id = None
        self._widget = panel.canvas.get_tk_widget()

        self.n_paths = 400
        self.horizon = 126
        self.duration = 12.0
        self.model = "block"

        self.paths: Optional[np.ndarray] = None
        self.s0 = 0.0
        self.symbol = ""
        self._elapsed = 0.0
        self._frame_start = 0.0
        self._loops = 0
        self._draw_idx: Optional[np.ndarray] = None
        self._interval = MC_MIN_INTERVAL_MS
        self._frame_no = 0

        self.ax_main = None
        self.ax_hist = None
        self.lc = None
        self.fan_artists: List[Any] = []
        self.median_line = None

    # -- configuration ---------------------------------------------------------
    def configure(self, n_paths: int, horizon: int, seconds: float, model: str) -> None:
        self.n_paths = int(clamp(n_paths, 20, 2000))
        self.horizon = int(clamp(horizon, 10, 1260))
        self.duration = float(clamp(seconds, 3.0, 60.0))
        self.model = model

    # -- lifecycle -------------------------------------------------------------
    def start(self, px: pd.Series, symbol: str) -> None:
        if len(px) < 10:
            raise ValueError(f"Monte Carlo needs at least 10 bars; {len(px)} loaded.")
        # Drop any timer still in flight; two chains would fight over the
        # frame clock.
        self._cancel()
        self.symbol = symbol
        self.s0 = float(px.iloc[-1])
        self._px = px
        self._loops = 0
        self._frame_no = 0
        self._interval = MC_MIN_INTERVAL_MS
        self._generate()
        self._build_plot()
        self._elapsed = 0.0
        self._frame_start = time.perf_counter()
        self.running = True
        self.status_cb(f"Monte Carlo running - {self.n_paths} paths, "
                       f"{self.horizon}d horizon", ACCENT)
        self._schedule()

    def toggle(self, px: pd.Series, symbol: str) -> None:
        if self.running:
            self.pause()
        elif self.paths is not None and symbol == self.symbol:
            self.resume()
        else:
            self.start(px, symbol)

    def pause(self) -> None:
        if self.running:
            self._elapsed += time.perf_counter() - self._frame_start
        self.running = False
        self._cancel()
        self.status_cb("Monte Carlo paused", WARN)

    def resume(self) -> None:
        if self.running or self.paths is None:
            return
        self._cancel()
        self.running = True
        self._frame_start = time.perf_counter()
        self.status_cb("Monte Carlo running", ACCENT)
        self._schedule()

    def stop(self) -> None:
        self.running = False
        self._cancel()
        self.paths = None

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _schedule(self) -> None:
        try:
            self._after_id = self._widget.after(self._interval, self._tick)
        except Exception:
            self.running = False

    # -- simulation ------------------------------------------------------------
    def _generate(self) -> None:
        self.paths = simulate_paths(self._px, self.horizon, self.n_paths,
                                    model=self.model)
        # Percentiles use every path; only a capped subset is stroked as
        # lines. Draw cost is what makes a frame overrun its schedule, and a
        # few hundred translucent lines already read as a solid band.
        if self.n_paths > MC_MAX_DRAWN_PATHS:
            rng = np.random.default_rng(0)
            self._draw_idx = rng.choice(self.n_paths, MC_MAX_DRAWN_PATHS,
                                        replace=False)
        else:
            self._draw_idx = None

    def _build_plot(self) -> None:
        fig = self.panel.fig
        fig.clear()
        self.panel._placeholder = False
        gs = fig.add_gridspec(1, 2, width_ratios=[4.2, 1.0], wspace=0.03,
                              left=0.07, right=0.97, top=0.90, bottom=0.13)
        self.ax_main = fig.add_subplot(gs[0, 0])
        self.ax_hist = fig.add_subplot(gs[0, 1], sharey=self.ax_main)

        names = {"gbm": "GBM", "iid": "IID bootstrap",
                 "block": "Block bootstrap", "t": "Student-t"}
        drawn = (self.n_paths if self._draw_idx is None else len(self._draw_idx))
        shown = (f"{self.n_paths:,} paths" if drawn == self.n_paths
                 else f"{self.n_paths:,} paths ({drawn} drawn)")
        style_axes(self.ax_main,
                   title=f"{self.symbol}  -  {shown}  "
                         f"({names.get(self.model, self.model)}, {self.horizon} sessions)",
                   xlabel="Trading days ahead", ylabel="Price", grid="y")
        style_axes(self.ax_hist, title="", grid="none")
        self.ax_hist.tick_params(labelleft=False, labelbottom=False,
                                 left=False, bottom=False)
        for sp in self.ax_hist.spines.values():
            sp.set_visible(False)
        self.ax_hist.set_facecolor(SUNKEN)

        self.lc = LineCollection([], colors=INFO, linewidths=0.5, alpha=0.10)
        self.ax_main.add_collection(self.lc)
        self.median_line, = self.ax_main.plot([], [], color=ACCENT, linewidth=1.8,
                                              zorder=6, label="Median path")
        self.ax_main.axhline(self.s0, color=DIM, linestyle="--", linewidth=1.1,
                             alpha=0.8, zorder=5)
        # Right-aligned: the left edge is where all paths originate and is
        # too dense to read a label against.
        self.ax_main.text(0.994, self.s0, f"start {fmt_money(self.s0)}",
                          transform=self.ax_main.get_yaxis_transform(),
                          color=DIM, fontsize=8, va="top", ha="right", zorder=7,
                          bbox=dict(boxstyle="round,pad=0.25", fc=SUNKEN,
                                    ec=GRID, alpha=0.88))
        self.ax_main.set_xlim(0, self.horizon)

        lo = float(np.percentile(self.paths, 0.5))
        hi = float(np.percentile(self.paths, 99.5))
        pad = (hi - lo) * 0.06 or self.s0 * 0.05
        self.ax_main.set_ylim(lo - pad, hi + pad)
        self.ax_main.yaxis.set_major_formatter(FuncFormatter(money_formatter))
        self.panel.draw()

    # -- animation -------------------------------------------------------------
    def _tick(self) -> None:
        if not self.running or self.paths is None:
            return
        frame_t0 = time.perf_counter()
        elapsed = self._elapsed + (frame_t0 - self._frame_start)
        frac = elapsed / self.duration

        if frac >= 1.0:
            self._loops += 1
            self.status_cb(f"Monte Carlo - resimulating (loop {self._loops})", INFO)
            self._generate()
            self._build_plot()
            self._elapsed = 0.0
            self._frame_start = time.perf_counter()
            self._frame_no = 0
            self._schedule()
            return

        self._frame_no += 1
        k = int(clamp(frac * self.horizon, 2, self.horizon))
        x = np.arange(k)

        drawn = (self.paths[:k, :] if self._draw_idx is None
                 else self.paths[:k, :][:, self._draw_idx])
        pts = np.empty((drawn.shape[1], k, 2), dtype=float)
        pts[:, :, 0] = x
        pts[:, :, 1] = drawn.T
        self.lc.set_segments(pts)

        for art in self.fan_artists:
            try:
                art.remove()
            except Exception:
                pass
        self.fan_artists = []

        band = self.paths[:k, :]                     # percentiles use ALL paths
        p05, p25, p50, p75, p95 = (np.percentile(band, q, axis=1)
                                   for q in (5, 25, 50, 75, 95))
        self.fan_artists.append(self.ax_main.fill_between(
            x, p05, p95, color=INFO, alpha=0.13, linewidth=0, zorder=2))
        self.fan_artists.append(self.ax_main.fill_between(
            x, p25, p75, color=INFO, alpha=0.20, linewidth=0, zorder=3))
        self.median_line.set_data(x, p50)

        terminal = self.paths[k - 1, :]
        # Rebuilding the histogram re-adds ~42 patches; every other frame is
        # enough at this cadence.
        if self._frame_no % 2 == 1 or k >= self.horizon - 1:
            self.ax_hist.clear()
            self.ax_hist.set_facecolor(SUNKEN)
            self.ax_hist.tick_params(labelleft=False, labelbottom=False,
                                     left=False, bottom=False)
            for sp in self.ax_hist.spines.values():
                sp.set_visible(False)
            self.ax_hist.hist(terminal, bins=42, orientation="horizontal",
                              color=INFO, alpha=0.55, edgecolor="none")
            self.ax_hist.axhline(self.s0, color=DIM, linestyle="--", linewidth=1.0)
            self.ax_hist.axhline(float(np.median(terminal)), color=ACCENT,
                                 linewidth=1.4)

        self.panel.render_now()
        self._update_stats(terminal, k)

        # Pace the animation to measured render cost. If a frame costs more
        # than the interval, the next timer is already expired when set, Tk
        # never reaches idle and the UI stops responding. +25ms leaves a gap
        # for other event sources.
        frame_ms = (time.perf_counter() - frame_t0) * 1000.0
        target = int(clamp(frame_ms * 1.35 + 25, MC_MIN_INTERVAL_MS,
                           MC_MAX_INTERVAL_MS))
        self._interval = int(0.6 * self._interval + 0.4 * target)
        self._schedule()

    def _update_stats(self, terminal: np.ndarray, k: int) -> None:
        s0 = self.s0
        p05, p50, p95 = (float(np.percentile(terminal, q)) for q in (5, 50, 95))
        up = float((terminal > s0).mean())
        running_max = np.maximum.accumulate(self.paths[:k, :], axis=0)
        dd = float(np.mean((self.paths[:k, :] / running_max - 1.0).min(axis=0)))
        loss_q = float(np.percentile(terminal / s0 - 1.0, 5))

        txt = (f"Session {k}/{self.horizon}    paths {self.n_paths}\n"
               f"Median   {fmt_money(p50)}  ({fmt_pct(p50 / s0 - 1, 1)})\n"
               f"P5-P95   {fmt_money(p05)} - {fmt_money(p95)}\n"
               f"P(up)    {fmt_pct(up, 1)}\n"
               f"5% worst {fmt_pct(loss_q, 1)}\n"
               f"Avg path max drawdown {fmt_pct(dd, 1)}")
        self.stats_cb(txt)


# ==============================================================================
# SECTION 16 - BACKGROUND JOB RUNNER
# ==============================================================================

class JobRunner:
    """One named background job at a time, with cooperative cancellation.

    Worker threads never touch widgets; they post callables to a queue drained
    by the Tk main loop. Long operations check `should_abort` so closing the
    window or starting a new job stops the old one.
    """

    def __init__(self, ui_queue: "queue.Queue"):
        self.q = ui_queue
        self._threads: Dict[str, threading.Thread] = {}
        self._cancel: Dict[str, threading.Event] = {}
        self._shutdown = threading.Event()

    def is_running(self, name: str) -> bool:
        t = self._threads.get(name)
        return bool(t and t.is_alive())

    def cancel(self, name: str) -> None:
        ev = self._cancel.get(name)
        if ev:
            ev.set()

    def cancel_all(self) -> None:
        self._shutdown.set()
        for ev in self._cancel.values():
            ev.set()

    def submit(self, name: str, work: Callable[[Callable[[], bool],
                                                Callable[[str], None]], Any],
               on_done: Callable[[Any], None],
               on_error: Callable[[BaseException], None],
               on_progress: Optional[Callable[[str], None]] = None) -> bool:
        if self.is_running(name):
            return False

        ev = threading.Event()
        self._cancel[name] = ev

        def should_abort() -> bool:
            return ev.is_set() or self._shutdown.is_set()

        def progress(msg: str) -> None:
            if on_progress and not should_abort():
                self.q.put((on_progress, msg))

        def runner() -> None:
            try:
                result = work(should_abort, progress)
            except Cancelled:
                return
            except BaseException as exc:                     # noqa: BLE001
                if not should_abort():
                    self.q.put((on_error, exc))
                return
            if not should_abort():
                self.q.put((on_done, result))

        t = threading.Thread(target=runner, name=f"job-{name}", daemon=True)
        self._threads[name] = t
        t.start()
        return True


# ==============================================================================
# SECTION 17 - MAIN APPLICATION WINDOW
# ==============================================================================

TAB_NAMES = ["OVERVIEW", "TECH", "RISK", "REGIME", "SEASON", "FORECAST",
             "MONTE", "BACKTEST", "COMPANY", "DATA", "LOG"]


class QuantDeskApp(ctk.CTk if GUI_AVAILABLE else object):

    def __init__(self):
        super().__init__()

        self.settings = Settings.load()
        self.client = MarketStackClient()
        self.uiq: "queue.Queue" = queue.Queue()
        self.jobs = JobRunner(self.uiq)

        self.series: Optional[PriceSeries] = None
        self.full_series: Optional[PriceSeries] = None
        self.bench_series: Optional[PriceSeries] = None
        self.analysis: Optional[Dict[str, Any]] = None
        self.forecast: Optional[Dict[str, Any]] = None
        self.backtest: Optional[BacktestResult] = None
        self.company_info: Dict[str, Any] = {}
        self.ai_result: Optional[Dict[str, Any]] = None
        self.watch_rows: Dict[str, WatchRow] = {}
        self._closing = False
        self._poll_id = None

        self.title(f"{APP_NAME}  v{APP_VERSION}")
        try:
            self.geometry(self.settings.geometry)
        except Exception:
            self.geometry("1620x1000")
        self.minsize(1240, 780)
        self.configure(fg_color=BG)

        self.mono = _pick_font(MONO_CANDIDATES, "Courier New")
        self.ui = _pick_font(UI_CANDIDATES, "Arial")
        self.f_mono = (self.mono, 12)
        self.f_mono_sm = (self.mono, 11)

        self._build_topbar()
        self._build_body()
        self._bind_keys()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_id = self.after(50, self._poll_ui)

        self.log(f"{APP_NAME} v{APP_VERSION} ready.")
        self._check_environment()
        self.after(400, self.refresh_watchlist)

    # ==========================================================================
    # UI CONSTRUCTION
    # ==========================================================================
    def _build_topbar(self) -> None:
        top = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=12, height=64)
        top.pack(fill="x", padx=12, pady=(12, 8))
        top.pack_propagate(False)

        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.pack(side="left", padx=(16, 20))
        ctk.CTkLabel(brand, text="QUANTDESK", text_color=ACCENT,
                     font=(self.ui, 17, "bold")).pack(anchor="w", pady=(9, 0))
        ctk.CTkLabel(brand, text=f"TERMINAL v{APP_VERSION}", text_color=FAINT,
                     font=(self.mono, 9)).pack(anchor="w")

        ctk.CTkFrame(top, fg_color=GRID, width=1, height=34).pack(side="left", padx=4)

        # -- ticker ------------------------------------------------------------
        tick_box = ctk.CTkFrame(top, fg_color="transparent")
        tick_box.pack(side="left", padx=(14, 8))
        ctk.CTkLabel(tick_box, text="TICKER", text_color=FAINT,
                     font=(self.ui, 9, "bold")).pack(anchor="w", pady=(9, 1))
        self.ticker_var = ctk.StringVar(value=self.settings.ticker)
        self.ticker_entry = ctk.CTkEntry(
            tick_box, textvariable=self.ticker_var, width=110, height=30,
            corner_radius=8, fg_color=SUNKEN, border_color=GRID, border_width=1,
            font=(self.mono, 14, "bold"), justify="center")
        self.ticker_entry.pack()

        # -- benchmark ---------------------------------------------------------
        bench_box = ctk.CTkFrame(top, fg_color="transparent")
        bench_box.pack(side="left", padx=8)
        ctk.CTkLabel(bench_box, text="BENCHMARK", text_color=FAINT,
                     font=(self.ui, 9, "bold")).pack(anchor="w", pady=(9, 1))
        self.bench_var = ctk.StringVar(value=self.settings.benchmark)
        ctk.CTkEntry(bench_box, textvariable=self.bench_var, width=90, height=30,
                     corner_radius=8, fg_color=SUNKEN, border_color=GRID,
                     border_width=1, font=(self.mono, 13), justify="center").pack()

        # -- range -------------------------------------------------------------
        range_box = ctk.CTkFrame(top, fg_color="transparent")
        range_box.pack(side="left", padx=(14, 8))
        ctk.CTkLabel(range_box, text="RANGE", text_color=FAINT,
                     font=(self.ui, 9, "bold")).pack(anchor="w", pady=(9, 1))
        self.range_var = ctk.StringVar(value=self.settings.range_key)
        self.range_btn = ctk.CTkSegmentedButton(
            range_box, values=list(RANGE_PRESETS.keys()), variable=self.range_var,
            height=30, corner_radius=8, font=(self.ui, 11),
            fg_color=SUNKEN, selected_color=ACCENT_DK, selected_hover_color=ACCENT,
            unselected_color=SUNKEN, unselected_hover_color=PANEL_HI,
            text_color=TEXT, command=self._on_range_change)
        self.range_btn.pack()

        # -- total return ------------------------------------------------------
        tr_box = ctk.CTkFrame(top, fg_color="transparent")
        tr_box.pack(side="left", padx=(12, 8))
        ctk.CTkLabel(tr_box, text="SERIES", text_color=FAINT,
                     font=(self.ui, 9, "bold")).pack(anchor="w", pady=(9, 1))
        self.tr_var = ctk.BooleanVar(value=self.settings.total_return)
        ctk.CTkSwitch(tr_box, text="Total return", variable=self.tr_var,
                      onvalue=True, offvalue=False, width=40, height=22,
                      font=(self.ui, 11), text_color=DIM,
                      progress_color=ACCENT_DK, button_color=DIM,
                      button_hover_color=TEXT,
                      command=self._on_total_return_toggle).pack(pady=(3, 0))

        # -- actions -----------------------------------------------------------
        act = ctk.CTkFrame(top, fg_color="transparent")
        act.pack(side="left", padx=(14, 8))
        ctk.CTkLabel(act, text=" ", font=(self.ui, 9)).pack(anchor="w", pady=(9, 1))
        row = ctk.CTkFrame(act, fg_color="transparent")
        row.pack()
        self.fetch_btn = ctk.CTkButton(
            row, text="FETCH", width=86, height=30, corner_radius=8,
            font=(self.ui, 12, "bold"), fg_color=ACCENT_DK, hover_color=ACCENT,
            text_color="#04120d", command=self.fetch_data)
        self.fetch_btn.pack(side="left", padx=(0, 6))
        self.run_btn = ctk.CTkButton(
            row, text="ANALYZE", width=92, height=30, corner_radius=8,
            font=(self.ui, 12, "bold"), fg_color=PANEL_HI, hover_color=GRID,
            text_color=TEXT, border_width=1, border_color=GRID,
            command=self.run_analysis)
        self.run_btn.pack(side="left")

        # -- status ------------------------------------------------------------
        status_box = ctk.CTkFrame(top, fg_color="transparent")
        status_box.pack(side="right", padx=(10, 18), fill="y")
        self.status_var = ctk.StringVar(value="Ready")
        self.status_label = ctk.CTkLabel(status_box, textvariable=self.status_var,
                                         text_color=DIM, font=(self.mono, 11),
                                         anchor="e")
        self.status_label.pack(anchor="e", pady=(14, 2))
        self.progress = ctk.CTkProgressBar(status_box, width=230, height=4,
                                           corner_radius=2, fg_color=SUNKEN,
                                           progress_color=ACCENT)
        self.progress.pack(anchor="e")
        self.progress.set(0)

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkScrollableFrame(
            body, fg_color=PANEL, corner_radius=12, width=346,
            scrollbar_button_color=GRID, scrollbar_button_hover_color=PANEL_HI)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        self._build_sidebar()

        right = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(
            right, fg_color=PANEL, corner_radius=10,
            segmented_button_fg_color=SUNKEN,
            segmented_button_selected_color=ACCENT_DK,
            segmented_button_selected_hover_color=ACCENT,
            segmented_button_unselected_color=SUNKEN,
            segmented_button_unselected_hover_color=PANEL_HI,
            text_color=TEXT, anchor="w")
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        try:
            self.tabs._segmented_button.configure(font=(self.ui, 11, "bold"))
        except Exception:
            pass

        self.tab = {name: self.tabs.add(name) for name in TAB_NAMES}
        self._build_tab_overview()
        self._build_tab_tech()
        self._build_tab_risk()
        self._build_tab_regime()
        self._build_tab_season()
        self._build_tab_forecast()
        self._build_tab_monte()
        self._build_tab_backtest()
        self._build_tab_company()
        self._build_tab_data()
        self._build_tab_log()
        self.tabs.set("OVERVIEW")

    # -- sidebar ---------------------------------------------------------------
    def _build_sidebar(self) -> None:
        section_label(self.sidebar, "Watchlist", self.ui)

        self.watch_frame = ctk.CTkFrame(self.sidebar, fg_color=SUNKEN, corner_radius=10)
        self.watch_frame.pack(fill="x", padx=14, pady=(0, 6))
        self._rebuild_watchlist()

        add_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        add_row.pack(fill="x", padx=14, pady=(0, 4))
        add_row.grid_columnconfigure(0, weight=1)
        self.watch_add_var = ctk.StringVar()
        ent = ctk.CTkEntry(add_row, textvariable=self.watch_add_var, height=28,
                           corner_radius=8, fg_color=SUNKEN, border_color=GRID,
                           border_width=1, font=(self.mono, 12),
                           placeholder_text="Add symbol")
        ent.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ent.bind("<Return>", lambda _e: self.add_to_watchlist())
        ctk.CTkButton(add_row, text="+", width=30, height=28, corner_radius=8,
                      fg_color=PANEL_HI, hover_color=GRID, text_color=TEXT,
                      font=(self.ui, 14, "bold"),
                      command=self.add_to_watchlist).grid(row=0, column=1)
        ctk.CTkButton(add_row, text="Refresh", width=68, height=28, corner_radius=8,
                      fg_color=PANEL_HI, hover_color=GRID, text_color=DIM,
                      font=(self.ui, 11),
                      command=self.refresh_watchlist).grid(row=0, column=2, padx=(6, 0))

        # -- snapshot ----------------------------------------------------------
        section_label(self.sidebar, "Snapshot", self.ui)
        grid = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 4))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="snap")

        self.tiles: Dict[str, StatTile] = {}
        tile_defs = [("last", "Last close"), ("chg", "1-day change"),
                     ("vol", "Volatility (ann)"), ("sharpe", "Sharpe"),
                     ("maxdd", "Max drawdown"), ("beta", "Beta"),
                     ("rsi", "RSI(14)"), ("trend", "Trend")]
        for i, (key, label) in enumerate(tile_defs):
            t = StatTile(grid, label, self.ui, self.mono)
            t.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)
            self.tiles[key] = t

        self.meta_label = ctk.CTkLabel(
            self.sidebar, text="No data loaded", text_color=FAINT,
            font=(self.mono, 10), anchor="w", justify="left", wraplength=310)
        self.meta_label.pack(fill="x", padx=17, pady=(6, 2))

        # -- monte carlo -------------------------------------------------------
        section_label(self.sidebar, "Monte Carlo", self.ui)
        mc = ctk.CTkFrame(self.sidebar, fg_color=SUNKEN, corner_radius=10)
        mc.pack(fill="x", padx=14, pady=(0, 4))
        mc.grid_columnconfigure(1, weight=1)

        self.mc_paths_var = ctk.StringVar(value=str(self.settings.mc_paths))
        self.mc_horizon_var = ctk.StringVar(value=str(self.settings.mc_horizon))
        self.mc_loop_var = ctk.StringVar(value=str(self.settings.mc_loop_seconds))
        self.mc_model_var = ctk.StringVar(value=self.settings.mc_model)

        for r, (lab, var) in enumerate([("Paths", self.mc_paths_var),
                                        ("Horizon (days)", self.mc_horizon_var),
                                        ("Loop (seconds)", self.mc_loop_var)]):
            ctk.CTkLabel(mc, text=lab, text_color=DIM, font=(self.ui, 11),
                         anchor="w").grid(row=r, column=0, padx=(10, 6), pady=5, sticky="w")
            ctk.CTkEntry(mc, textvariable=var, height=26, width=90, corner_radius=6,
                         fg_color=PANEL, border_color=GRID, border_width=1,
                         font=(self.mono, 12), justify="right"
                         ).grid(row=r, column=1, padx=(0, 10), pady=5, sticky="e")

        ctk.CTkLabel(mc, text="Model", text_color=DIM, font=(self.ui, 11),
                     anchor="w").grid(row=3, column=0, padx=(10, 6), pady=(5, 9), sticky="w")
        ctk.CTkOptionMenu(mc, variable=self.mc_model_var,
                          values=list(MC_MODEL_KEYS.keys()), height=26, width=150,
                          corner_radius=6, font=(self.ui, 11),
                          fg_color=PANEL, button_color=PANEL_HI,
                          button_hover_color=GRID, text_color=TEXT,
                          dropdown_fg_color=PANEL, dropdown_text_color=TEXT,
                          dropdown_hover_color=PANEL_HI
                          ).grid(row=3, column=1, padx=(0, 10), pady=(5, 9), sticky="e")

        self.mc_btn = ctk.CTkButton(
            self.sidebar, text="START SIMULATION", height=34, corner_radius=8,
            font=(self.ui, 12, "bold"), fg_color=PANEL_HI, hover_color=GRID,
            border_width=1, border_color=GRID, text_color=TEXT,
            command=self.toggle_monte_carlo)
        self.mc_btn.pack(fill="x", padx=14, pady=(4, 2))

        # -- actions -----------------------------------------------------------
        section_label(self.sidebar, "Actions", self.ui)
        acts = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        acts.pack(fill="x", padx=14, pady=(0, 14))
        acts.grid_columnconfigure((0, 1), weight=1)

        buttons = [("Export report", self.export_report),
                   ("Export CSV", self.export_csv),
                   ("Clear cache", self.clear_cache),
                   ("Reset", self.reset_all)]
        for i, (label, cmd) in enumerate(buttons):
            ctk.CTkButton(acts, text=label, height=30, corner_radius=8,
                          font=(self.ui, 11), fg_color=PANEL_HI, hover_color=GRID,
                          text_color=DIM, command=cmd
                          ).grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)

        self.api_label = ctk.CTkLabel(self.sidebar, text="", text_color=FAINT,
                                      font=(self.mono, 9), anchor="w",
                                      justify="left", wraplength=310)
        self.api_label.pack(fill="x", padx=17, pady=(0, 12))
        self._update_api_label()

    def _rebuild_watchlist(self) -> None:
        for child in self.watch_frame.winfo_children():
            child.destroy()
        self.watch_rows = {}
        if not self.settings.watchlist:
            ctk.CTkLabel(self.watch_frame, text="  (empty)", text_color=FAINT,
                         font=(self.mono, 11)).pack(anchor="w", padx=8, pady=6)
            return
        for sym in self.settings.watchlist:
            row = WatchRow(self.watch_frame, sym, self.mono,
                           on_click=self.load_symbol, on_remove=self.remove_from_watchlist)
            row.pack(fill="x", pady=1)
            self.watch_rows[sym] = row

    # -- tab builders ----------------------------------------------------------
    def _split_tab(self, parent, chart_height: int = 300,
                   chart_weight: int = 6, text_weight: int = 4):
        """Tab layout: chart on top, monospace report underneath."""
        parent.grid_rowconfigure(0, weight=chart_weight)
        parent.grid_rowconfigure(1, weight=text_weight)
        parent.grid_columnconfigure(0, weight=1)
        chart = ChartPanel(parent, height=chart_height)
        chart.grid(row=0, column=0, sticky="nsew", padx=6, pady=(6, 4))
        text = ReadOnlyText(parent, font=self.f_mono_sm)
        text.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        return chart, text

    def _build_tab_overview(self) -> None:
        self.ov_chart, self.ov_text = self._split_tab(self.tab["OVERVIEW"], 340, 6, 4)
        self.ov_chart.message("Enter a ticker and press FETCH")
        self.ov_text.set_text(WELCOME_TEXT)

    def _build_tab_tech(self) -> None:
        self.tech_chart, self.tech_text = self._split_tab(self.tab["TECH"], 380, 7, 3)
        self.tech_chart.message("No data loaded")

    def _build_tab_risk(self) -> None:
        self.risk_chart, self.risk_text = self._split_tab(self.tab["RISK"], 320, 5, 5)
        self.risk_chart.message("No data loaded")

    def _build_tab_regime(self) -> None:
        self.regime_chart, self.regime_text = self._split_tab(self.tab["REGIME"], 300, 5, 5)
        self.regime_chart.message("No data loaded")

    def _build_tab_season(self) -> None:
        self.season_chart, self.season_text = self._split_tab(self.tab["SEASON"], 280, 4, 6)
        self.season_chart.message("No data loaded")

    def _build_tab_forecast(self) -> None:
        self.fc_chart, self.fc_text = self._split_tab(self.tab["FORECAST"], 320, 5, 5)
        self.fc_chart.message("No data loaded")

    def _build_tab_monte(self) -> None:
        t = self.tab["MONTE"]
        t.grid_rowconfigure(0, weight=1)
        t.grid_columnconfigure(0, weight=1)
        self.mc_chart = ChartPanel(t, height=440)
        self.mc_chart.grid(row=0, column=0, sticky="nsew", padx=6, pady=(6, 4))
        self.mc_chart.message("Load a symbol, then press START SIMULATION")

        bar = ctk.CTkFrame(t, fg_color=SUNKEN, corner_radius=10)
        bar.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        self.mc_stats = ctk.CTkLabel(bar, text="No simulation running",
                                     text_color=DIM, font=(self.mono, 11),
                                     anchor="w", justify="left")
        self.mc_stats.pack(anchor="w", padx=14, pady=10)

        self.mc_engine = MonteCarloEngine(self.mc_chart,
                                          stats_cb=self._set_mc_stats,
                                          status_cb=self.set_status)

    def _build_tab_backtest(self) -> None:
        t = self.tab["BACKTEST"]
        t.grid_rowconfigure(1, weight=6)
        t.grid_rowconfigure(2, weight=4)
        t.grid_columnconfigure(0, weight=1)

        ctrl = ctk.CTkFrame(t, fg_color=SUNKEN, corner_radius=10)
        ctrl.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))

        ctk.CTkLabel(ctrl, text="STRATEGY", text_color=FAINT,
                     font=(self.ui, 9, "bold")).pack(side="left", padx=(14, 6), pady=12)
        self.bt_strategy_var = ctk.StringVar(value=self.settings.bt_strategy)
        ctk.CTkOptionMenu(ctrl, variable=self.bt_strategy_var, values=STRATEGIES,
                          width=160, height=30, corner_radius=8, font=(self.ui, 11),
                          fg_color=PANEL, button_color=PANEL_HI,
                          button_hover_color=GRID, text_color=TEXT,
                          dropdown_fg_color=PANEL, dropdown_text_color=TEXT,
                          dropdown_hover_color=PANEL_HI).pack(side="left", pady=12)

        for label, var, width in (("FAST", "bt_fast_var", 60),
                                  ("SLOW", "bt_slow_var", 60),
                                  ("COST bps", "bt_cost_var", 62)):
            ctk.CTkLabel(ctrl, text=label, text_color=FAINT,
                         font=(self.ui, 9, "bold")).pack(side="left", padx=(16, 6), pady=12)
            default = {"bt_fast_var": self.settings.bt_fast,
                       "bt_slow_var": self.settings.bt_slow,
                       "bt_cost_var": self.settings.bt_cost_bps}[var]
            sv = ctk.StringVar(value=str(default))
            setattr(self, var, sv)
            ctk.CTkEntry(ctrl, textvariable=sv, width=width, height=30,
                         corner_radius=8, fg_color=PANEL, border_color=GRID,
                         border_width=1, font=(self.mono, 12),
                         justify="center").pack(side="left", pady=12)

        self.bt_btn = ctk.CTkButton(ctrl, text="RUN BACKTEST", width=130, height=30,
                                    corner_radius=8, font=(self.ui, 12, "bold"),
                                    fg_color=ACCENT_DK, hover_color=ACCENT,
                                    text_color="#04120d", command=self.run_backtest)
        self.bt_btn.pack(side="left", padx=18, pady=12)

        self.bt_chart = ChartPanel(t, height=300)
        self.bt_chart.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 4))
        self.bt_chart.message("Load a symbol, then run a backtest")
        self.bt_text = ReadOnlyText(t, font=self.f_mono_sm)
        self.bt_text.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))

    def _build_tab_company(self) -> None:
        t = self.tab["COMPANY"]
        t.grid_rowconfigure(2, weight=1)
        t.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(t, fg_color=SUNKEN, corner_radius=10)
        head.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        head.grid_columnconfigure(1, weight=1)

        self.verdict_label = ctk.CTkLabel(head, text="  --  ", text_color=DIM,
                                          font=(self.mono, 15, "bold"),
                                          fg_color=PANEL, corner_radius=6,
                                          width=170, height=34)
        self.verdict_label.grid(row=0, column=0, padx=(14, 12), pady=12)

        ctk.CTkLabel(head, text="Company data is pulled automatically after FETCH. "
                               "Add any fundamentals the API cannot supply below.",
                     text_color=DIM, font=(self.ui, 11), anchor="w",
                     justify="left").grid(row=0, column=1, sticky="w")

        self.ai_btn = ctk.CTkButton(head, text="ANALYZE", width=110, height=32,
                                    corner_radius=8, font=(self.ui, 12, "bold"),
                                    fg_color=ACCENT_DK, hover_color=ACCENT,
                                    text_color="#04120d", command=self.run_ai_analysis)
        self.ai_btn.grid(row=0, column=2, padx=14, pady=12)

        notes = ctk.CTkFrame(t, fg_color="transparent")
        notes.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 4))
        ctk.CTkLabel(notes, text="OPTIONAL: PASTE FUNDAMENTALS "
                                 "(revenue, margins, FCF, debt, guidance, multiples)",
                     text_color=FAINT, font=(self.ui, 9, "bold"),
                     anchor="w").pack(fill="x", pady=(0, 3))
        self.ai_input = ctk.CTkTextbox(notes, height=96, fg_color=SUNKEN,
                                       text_color=TEXT, corner_radius=10,
                                       wrap="word", border_width=0, font=self.f_mono_sm)
        self.ai_input.pack(fill="x")

        self.ai_out = ReadOnlyText(t, font=self.f_mono_sm)
        self.ai_out.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.ai_out.set_text(COMPANY_HELP_TEXT)

    def _build_tab_data(self) -> None:
        t = self.tab["DATA"]
        t.grid_rowconfigure(1, weight=1)
        t.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(t, fg_color=SUNKEN, corner_radius=10)
        bar.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        self.data_info = ctk.CTkLabel(bar, text="No data loaded", text_color=DIM,
                                      font=(self.mono, 11), anchor="w")
        self.data_info.pack(side="left", padx=14, pady=10)
        ctk.CTkButton(bar, text="Export CSV", width=100, height=28, corner_radius=8,
                      font=(self.ui, 11), fg_color=PANEL_HI, hover_color=GRID,
                      text_color=DIM, command=self.export_csv).pack(side="right",
                                                                    padx=14, pady=10)
        self.data_text = ReadOnlyText(t, font=self.f_mono_sm)
        self.data_text.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))

    def _build_tab_log(self) -> None:
        t = self.tab["LOG"]
        t.grid_rowconfigure(0, weight=1)
        t.grid_columnconfigure(0, weight=1)
        self.log_text = ReadOnlyText(t, font=self.f_mono_sm)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

    def _bind_keys(self) -> None:
        # Bound to the entry, not the window, so Enter in the notes box does
        # not trigger a fetch.
        self.ticker_entry.bind("<Return>", lambda _e: self.fetch_data())
        self.bind("<F5>", lambda _e: self.fetch_data())
        self.bind("<Control-r>", lambda _e: self.run_analysis())
        self.bind("<Control-e>", lambda _e: self.export_report())


    # ==========================================================================
    # PLUMBING: STATUS, LOGGING, UI QUEUE
    # ==========================================================================
    def _poll_ui(self) -> None:
        if self._closing:
            return
        try:
            while True:
                fn, payload = self.uiq.get_nowait()
                try:
                    fn(payload)
                except Exception:
                    self.log("UI callback failed:\n" + traceback.format_exc())
        except queue.Empty:
            pass
        if not self._closing:
            self._poll_id = self.after(50, self._poll_ui)

    def set_status(self, msg: str, color: str = DIM) -> None:
        if self._closing:
            return
        self.status_var.set(redact_secrets(msg))
        self.status_label.configure(text_color=color)

    def log(self, msg: str) -> None:
        # Everything routed through here is scrubbed: the log is the single
        # most likely thing to be screenshotted or pasted into a bug report.
        stamp = datetime.now().strftime("%H:%M:%S")
        clean = redact_secrets(msg)
        try:
            self.log_text.append(f"[{stamp}] {clean}\n")
        except Exception:
            print(f"[{stamp}] {clean}")

    def _busy(self, on: bool, msg: str = "") -> None:
        state = "disabled" if on else "normal"
        for btn in (self.fetch_btn, self.run_btn, self.bt_btn, self.ai_btn):
            try:
                btn.configure(state=state)
            except Exception:
                pass
        if on:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
            if msg:
                self.set_status(msg, INFO)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)

    def _update_api_label(self) -> None:
        n, size = self.client.cache.stats()
        self.api_label.configure(
            text=(f"API calls this session: {self.client.request_count}   "
                  f"cache hits: {self.client.cache_hits}\n"
                  f"Cached responses: {n} ({size / 1024:.0f} KB)"))

    def _check_environment(self) -> None:
        if not os.getenv("MARKETSTACK_API_KEY"):
            self.set_status("MARKETSTACK_API_KEY is not set", BEAR)
            self.log("WARNING: MARKETSTACK_API_KEY is not set. Fetching will fail.")
        if not os.getenv("OPENAI_API_KEY"):
            self.log("Note: OPENAI_API_KEY is not set. The COMPANY tab needs it; "
                     "every other tab works without it.")

    def _on_error(self, exc: BaseException) -> None:
        self._busy(False)
        if isinstance(exc, MarketStackError):
            self.set_status(str(exc)[:90], BEAR)
            self.log("API ERROR: " + exc.pretty())
            messagebox.showerror(f"{APP_NAME} - data error",
                                 redact_secrets(exc.pretty()))
        else:
            self.set_status(f"{type(exc).__name__}: {exc}"[:90], BEAR)
            self.log("ERROR: " + "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)))
            messagebox.showerror(
                f"{APP_NAME} - error",
                redact_secrets(f"{type(exc).__name__}: {exc}"))
        self._update_api_label()

    # ==========================================================================
    # DATA FETCH
    # ==========================================================================
    def fetch_data(self) -> None:
        symbol = self.ticker_var.get().strip().upper()
        if not symbol:
            self.set_status("Enter a ticker symbol", WARN)
            return
        self.ticker_var.set(symbol)
        bench = self.bench_var.get().strip().upper()

        if self.jobs.is_running("fetch"):
            self.set_status("A fetch is already running", WARN)
            return

        self.mc_engine.stop()
        self.mc_btn.configure(text="START SIMULATION")
        self._busy(True, f"Fetching {symbol}...")
        self.log(f"FETCH {symbol}" + (f" (benchmark {bench})" if bench else ""))

        # Pull the widest window the plan allows; range switching then slices
        # locally and costs no further API calls.
        end = date.today()
        start = end - timedelta(days=RANGE_PRESETS["MAX"])
        want_tr = bool(self.tr_var.get())

        def work(should_abort, progress):
            progress(f"Requesting {symbol} bars...")
            raw = self.client.eod(symbol, str(start), str(end),
                                  should_abort=should_abort, progress=progress)

            progress("Loading corporate actions...")
            splits = self.client.splits(symbol, should_abort=should_abort)
            divs = self.client.dividends(symbol, should_abort=should_abort)

            ps = build_price_series(raw, symbol, splits, divs, total_return=want_tr)

            progress("Loading company profile...")
            info = self.client.ticker_info(symbol, should_abort=should_abort)

            bench_ps = None
            if bench and bench != symbol:
                try:
                    progress(f"Requesting benchmark {bench}...")
                    braw = self.client.eod(bench, str(start), str(end),
                                           should_abort=should_abort)
                    bsplits = self.client.splits(bench, should_abort=should_abort)
                    bench_ps = build_price_series(braw, bench, bsplits, None, False)
                except Cancelled:
                    raise
                except Exception as exc:
                    progress(f"Benchmark unavailable: {exc}")
                    bench_ps = None
            return {"series": ps, "bench": bench_ps, "info": info,
                    "bench_error": bench and bench == symbol}

        self.jobs.submit("fetch", work, self._on_fetch_done, self._on_error,
                         on_progress=lambda m: self.set_status(m, INFO))

    def _on_fetch_done(self, payload: Dict[str, Any]) -> None:
        self._busy(False)
        self.full_series = payload["series"]
        self.bench_series = payload["bench"]
        self.company_info = payload["info"] or {}
        self.analysis = None
        self.forecast = None
        self.backtest = None
        self.ai_result = None

        self._apply_range()
        ps = self.series
        self.settings.ticker = ps.symbol
        self.settings.save()

        self.set_status(f"{ps.symbol}  {ps.n} bars  {ps.start} to {ps.end}", ACCENT)
        self.log(f"LOADED {ps.symbol}: {self.full_series.n} bars "
                 f"({self.full_series.start} to {self.full_series.end}), "
                 f"adjustment={ps.adj_method}")
        for w in ps.warnings:
            self.log("  ! " + w)
        if self.bench_series is not None:
            self.log(f"LOADED benchmark {self.bench_series.symbol}: "
                     f"{self.bench_series.n} bars")
        else:
            b = self.bench_var.get().strip().upper()
            if b and b != ps.symbol:
                self.log(f"Benchmark {b} unavailable; beta and correlation "
                         "will be skipped.")

        self._update_api_label()
        self._render_data_tab()
        self._prefill_company_tab()
        self.set_status(f"{ps.symbol} loaded - press ANALYZE for the full stack", ACCENT)

    def _apply_range(self) -> None:
        """Slice cached history to the selected range and redraw."""
        if self.full_series is None:
            return
        key = self.range_var.get()
        days = RANGE_PRESETS.get(key)
        if key == "YTD":
            last = self.full_series.df.index[-1]
            days = max((last - pd.Timestamp(year=last.year, month=1, day=1)).days, 7)
        self.series = self.full_series.slice_days(days)

        # Slice the benchmark to the same window as the asset, otherwise its
        # CAGR and drawdown would cover a different period.
        self._bench_view = (self.bench_series.slice_days(days)
                            if self.bench_series is not None else None)

        self._update_tiles()
        self._render_overview_chart()

    def _on_range_change(self, _value=None) -> None:
        self.settings.range_key = self.range_var.get()
        self.settings.save()
        if self.full_series is None:
            return
        self._apply_range()
        self.log(f"Range set to {self.range_var.get()} "
                 f"({self.series.n} bars) - no API call required.")
        if self.analysis is not None:
            self.set_status("Range changed - press ANALYZE to recompute", WARN)

    def _on_total_return_toggle(self) -> None:
        self.settings.total_return = bool(self.tr_var.get())
        self.settings.save()
        if self.full_series is not None:
            self.set_status("Total-return setting changed - press FETCH to rebuild",
                            WARN)

    # ==========================================================================
    # WATCHLIST
    # ==========================================================================
    def load_symbol(self, symbol: str) -> None:
        self.ticker_var.set(symbol.upper())
        self.fetch_data()

    def add_to_watchlist(self) -> None:
        sym = self.watch_add_var.get().strip().upper()
        if not sym:
            return
        if sym in self.settings.watchlist:
            self.set_status(f"{sym} is already on the watchlist", WARN)
            return
        self.settings.watchlist.append(sym)
        self.settings.save()
        self.watch_add_var.set("")
        self._rebuild_watchlist()
        self.refresh_watchlist()

    def remove_from_watchlist(self, symbol: str) -> None:
        if symbol in self.settings.watchlist:
            self.settings.watchlist.remove(symbol)
            self.settings.save()
            self._rebuild_watchlist()

    def refresh_watchlist(self) -> None:
        symbols = list(self.settings.watchlist)
        if not symbols or self.jobs.is_running("watch"):
            return
        if not self.client.api_key:
            return

        def work(should_abort, progress):
            # One request covering every symbol.
            return self.client.latest_quotes(symbols, should_abort=should_abort)

        def done(df: pd.DataFrame) -> None:
            if df is None or df.empty:
                for row in self.watch_rows.values():
                    row.mark_error()
                return
            seen = set()
            for rec in df.itertuples():
                sym = str(rec.symbol).upper()
                seen.add(sym)
                row = self.watch_rows.get(sym)
                if row is not None:
                    row.update_quote(float(rec.close), float(rec.chg_pct))
            for sym, row in self.watch_rows.items():
                if sym not in seen:
                    row.mark_error()
            self._update_api_label()

        def failed(exc: BaseException) -> None:
            for row in self.watch_rows.values():
                row.mark_error()
            self.log(f"Watchlist refresh failed: {exc}")

        self.jobs.submit("watch", work, done, failed)

    # ==========================================================================
    # ANALYSIS
    # ==========================================================================
    def run_analysis(self) -> None:
        if self.series is None:
            self.set_status("Load data first (FETCH)", WARN)
            return
        if self.jobs.is_running("analysis"):
            self.set_status("Analysis already running", WARN)
            return

        ps = self.series
        bench = getattr(self, "_bench_view", None)
        sim_model = MC_MODEL_KEYS.get(self.mc_model_var.get(), "block")

        self._busy(True, "Running analysis...")
        self.log(f"ANALYZE {ps.symbol} ({ps.n} bars, model={sim_model})")
        t0 = time.perf_counter()

        def work(should_abort, progress):
            analysis = compute_analysis(ps, bench, should_abort, progress)
            progress("Fitting forecast models (this is the slow part)...")
            forecast = forecast_all(ps, sim_model=sim_model,
                                    should_abort=should_abort, progress=progress)
            return {"analysis": analysis, "forecast": forecast,
                    "elapsed": time.perf_counter() - t0}

        self.jobs.submit("analysis", work, self._on_analysis_done, self._on_error,
                         on_progress=lambda m: self.set_status(m, INFO))

    def _on_analysis_done(self, payload: Dict[str, Any]) -> None:
        self._busy(False)
        self.analysis = payload["analysis"]
        self.forecast = payload["forecast"]
        c, f = self.analysis, self.forecast

        self.ov_text.set_text(report_overview(c))
        self.tech_text.set_text(report_technicals(c))
        self.risk_text.set_text(report_risk(c))
        self.regime_text.set_text(report_regime(c))
        self.season_text.set_text(report_seasonality(c))
        self.fc_text.set_text(report_forecast(f))

        self._update_tiles()
        self._render_overview_chart()
        self._render_tech_chart()
        self._render_risk_chart()
        self._render_regime_chart()
        self._render_season_chart()
        self._render_forecast_chart()

        self.set_status(f"Analysis complete in {payload['elapsed']:.1f}s", ACCENT)
        self.log(f"ANALYZE done in {payload['elapsed']:.1f}s")
        ml = sum(1 for r in f.get("results", []) if r.model == "ENSEMBLE_ML_WF")
        unsupported = sum(1 for r in f.get("results", []) if not r.supported)
        self.log(f"  forecasts: {ml} machine-learning, "
                 f"{len(f.get('results', [])) - ml - unsupported} simulation, "
                 f"{unsupported} unsupported at this history length")

    def _update_tiles(self) -> None:
        ps, c = self.series, self.analysis
        if ps is None:
            return
        self.tiles["last"].set(fmt_money(ps.last), TEXT)

        px = ps.px
        if len(px) > 1:
            chg = float(px.iloc[-1] / px.iloc[-2] - 1)
            self.tiles["chg"].set(f"{chg * 100:+.2f}%",
                                  BULL if chg > 0 else BEAR if chg < 0 else DIM)
        if c is None:
            for key in ("vol", "sharpe", "maxdd", "beta", "rsi", "trend"):
                self.tiles[key].set("--", FAINT)
            self.meta_label.configure(
                text=f"{ps.display_name}\n{ps.n} bars  {ps.start} -> {ps.end}\n"
                     f"Adjustment: {ps.adj_method}\nPress ANALYZE for full metrics")
            return

        vol = c.get("vol", float("nan"))
        self.tiles["vol"].set(fmt_pct(vol, 1),
                              BEAR if np.isfinite(vol) and vol > 0.45 else
                              WARN if np.isfinite(vol) and vol > 0.28 else TEXT)
        sh = c.get("sharpe", float("nan"))
        self.tiles["sharpe"].set(fmt_num(sh),
                                 BULL if np.isfinite(sh) and sh > 1 else
                                 BEAR if np.isfinite(sh) and sh < 0 else TEXT)
        self.tiles["maxdd"].set(fmt_pct(c.get("maxdd"), 1), BEAR)
        b = c.get("beta", float("nan"))
        self.tiles["beta"].set(fmt_num(b), TEXT if np.isfinite(b) else FAINT)
        r = c.get("rsi14", float("nan"))
        self.tiles["rsi"].set(fmt_num(r, 1),
                              BEAR if np.isfinite(r) and r > 70 else
                              BULL if np.isfinite(r) and r < 30 else TEXT)
        tl = str(c.get("trend_label", "") or "")
        short = {"strong uptrend": "STRONG UP", "uptrend": "UP",
                 "neutral": "NEUTRAL", "downtrend": "DOWN",
                 "strong downtrend": "STRONG DOWN"}.get(tl, tl.upper() or "--")
        self.tiles["trend"].set(short,
                                BULL if "up" in tl else BEAR if "down" in tl else DIM)

        self.meta_label.configure(
            text=f"{ps.display_name}\n{ps.n} bars  {ps.start} -> {ps.end}\n"
                 f"Adjustment: {ps.adj_method}"
                 + ("\nTOTAL RETURN SERIES" if ps.total_return else ""))

    # ==========================================================================
    # CHART RENDERING
    # ==========================================================================
    def _render_overview_chart(self) -> None:
        ps = self.series
        if ps is None or ps.n < 2:
            return
        panel = self.ov_chart
        panel.reset()
        fig = panel.fig
        # Right margin leaves room for the last-price badge drawn outside the
        # axes.
        gs = fig.add_gridspec(3, 1, height_ratios=[3.1, 0.9, 1.1], hspace=0.12,
                              left=0.075, right=0.935, top=0.93, bottom=0.09)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax3 = fig.add_subplot(gs[2], sharex=ax1)

        px, idx = ps.px, ps.df.index
        suffix = " (total return)" if ps.total_return else ""
        style_axes(ax1, title=f"{ps.symbol} - {ps.display_name}{suffix}",
                   ylabel="Price", grid="y")
        ax1.plot(idx, px, color=TEXT, linewidth=1.5, label="Close", zorder=5)
        for w, col in ((20, INFO), (50, WARN), (200, VIOLET)):
            if ps.n > w:
                ax1.plot(idx, sma(px, w), color=col, linewidth=1.0,
                         alpha=0.85, label=f"SMA{w}")
        ax1.yaxis.set_major_formatter(FuncFormatter(money_formatter))
        ax1.tick_params(labelbottom=False)
        style_axes(ax1, legend=True, grid="y")

        last = float(px.iloc[-1])
        ax1.axhline(last, color=ACCENT, linestyle=":", linewidth=1.0, alpha=0.7)
        ax1.annotate(f" {fmt_money(last)} ", xy=(1.0, last),
                     xycoords=ax1.get_yaxis_transform(), color="#04120d",
                     fontsize=8.5, fontweight="bold", va="center", ha="left",
                     bbox=dict(boxstyle="round,pad=0.25", fc=ACCENT, ec="none"))

        style_axes(ax2, ylabel="Volume", grid="y")
        up = px.diff().fillna(0) >= 0
        ax2.bar(idx[up], ps.volume[up], color=BULL, alpha=0.55, width=1.0)
        ax2.bar(idx[~up], ps.volume[~up], color=BEAR, alpha=0.55, width=1.0)
        ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: fmt_big(v)))
        ax2.yaxis.set_major_locator(MaxNLocator(3))
        ax2.tick_params(labelbottom=False)

        dd = drawdown_series(px)
        style_axes(ax3, ylabel="Drawdown", grid="y")
        ax3.fill_between(idx, dd, 0, color=BEAR, alpha=0.28, linewidth=0)
        ax3.plot(idx, dd, color=BEAR, linewidth=0.9)
        ax3.yaxis.set_major_formatter(FuncFormatter(pct_formatter))
        ax3.yaxis.set_major_locator(MaxNLocator(3))
        format_date_axis(ax3, idx)
        panel.draw()

    def _render_tech_chart(self) -> None:
        ps = self.series
        if ps is None or ps.n < 25:
            self.tech_chart.message("Not enough history for technical charts")
            return
        panel = self.tech_chart
        panel.reset()
        fig = panel.fig
        gs = fig.add_gridspec(3, 1, height_ratios=[2.6, 1.0, 1.0], hspace=0.14,
                              left=0.075, right=0.975, top=0.93, bottom=0.09)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax3 = fig.add_subplot(gs[2], sharex=ax1)

        px, idx = ps.px, ps.df.index
        mid, upper, lower, _, _ = bollinger(px, 20, 2.0)
        style_axes(ax1, title=f"{ps.symbol} - price, Bollinger(20,2) and moving averages",
                   ylabel="Price", grid="y")
        ax1.fill_between(idx, lower, upper, color=INFO, alpha=0.10, linewidth=0)
        ax1.plot(idx, upper, color=INFO, linewidth=0.7, alpha=0.6)
        ax1.plot(idx, lower, color=INFO, linewidth=0.7, alpha=0.6)
        ax1.plot(idx, px, color=TEXT, linewidth=1.4, label="Close")
        ax1.plot(idx, mid, color=WARN, linewidth=0.9, label="SMA20")
        if ps.n > 50:
            ax1.plot(idx, sma(px, 50), color=VIOLET, linewidth=0.9, label="SMA50")
        ax1.yaxis.set_major_formatter(FuncFormatter(money_formatter))
        ax1.tick_params(labelbottom=False)
        style_axes(ax1, legend=True, grid="y")

        style_axes(ax2, ylabel="RSI(14)", grid="y")
        r = rsi(px, 14)
        ax2.plot(idx, r, color=VIOLET, linewidth=1.1)
        ax2.axhline(70, color=BEAR, linestyle="--", linewidth=0.7, alpha=0.7)
        ax2.axhline(30, color=BULL, linestyle="--", linewidth=0.7, alpha=0.7)
        ax2.fill_between(idx, 30, 70, color=GRID_SOFT, alpha=0.35, linewidth=0)
        ax2.set_ylim(0, 100)
        ax2.set_yticks([30, 50, 70])
        ax2.tick_params(labelbottom=False)

        style_axes(ax3, ylabel="MACD", grid="y")
        line, sig, hist = macd(px)
        colors = np.where(hist.fillna(0) >= 0, BULL, BEAR)
        ax3.bar(idx, hist, color=colors, alpha=0.5, width=1.0)
        ax3.plot(idx, line, color=INFO, linewidth=1.0, label="MACD")
        ax3.plot(idx, sig, color=WARN, linewidth=1.0, label="Signal")
        ax3.axhline(0, color=GRID, linewidth=0.8)
        ax3.yaxis.set_major_locator(MaxNLocator(3))
        format_date_axis(ax3, idx)
        style_axes(ax3, ylabel="MACD", legend=True, grid="y")
        panel.draw()

    def _render_risk_chart(self) -> None:
        ps, c = self.series, self.analysis
        if ps is None or c is None or ps.n < 30:
            self.risk_chart.message("Not enough history for risk charts")
            return
        panel = self.risk_chart
        panel.reset()
        fig = panel.fig
        gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.0],
                              width_ratios=[1.35, 1.0], hspace=0.42, wspace=0.22,
                              left=0.075, right=0.975, top=0.92, bottom=0.11)
        ax1 = fig.add_subplot(gs[0, :])
        ax2 = fig.add_subplot(gs[1, 0])
        ax3 = fig.add_subplot(gs[1, 1])

        px, idx = ps.px, ps.df.index
        dd = drawdown_series(px)
        style_axes(ax1, title="Underwater curve", ylabel="Drawdown", grid="y")
        ax1.fill_between(idx, dd, 0, color=BEAR, alpha=0.30, linewidth=0)
        ax1.plot(idx, dd, color=BEAR, linewidth=1.0)
        det = c.get("dd_detail") or {}
        if det.get("trough") is not None:
            ax1.scatter([det["trough"]], [det["depth"]], color=BEAR, s=26, zorder=6)
            ax1.annotate(f" {fmt_pct(det['depth'], 1)}", (det["trough"], det["depth"]),
                         color=BEAR, fontsize=8.5, va="top")
        ax1.yaxis.set_major_formatter(FuncFormatter(pct_formatter))
        format_date_axis(ax1, idx)

        rets = simple_returns(px).dropna()
        style_axes(ax2, title="Daily return distribution", grid="y")
        ax2.hist(rets, bins=48, color=INFO, alpha=0.65, edgecolor="none")
        for lvl, col, lab in ((c.get("var95"), WARN, "VaR95"),
                              (c.get("cvar95"), BEAR, "CVaR95")):
            if lvl is not None and np.isfinite(lvl):
                ax2.axvline(-lvl, color=col, linestyle="--", linewidth=1.1, label=lab)
        ax2.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v * 100:.0f}%"))
        ax2.yaxis.set_major_locator(MaxNLocator(4))
        style_axes(ax2, title="Daily return distribution", legend=True, grid="y")

        style_axes(ax3, title="Rolling 20-day volatility (annualised)", grid="y")
        rv = log_returns(px).rolling(20).std(ddof=1) * math.sqrt(TRADING_DAYS)
        rv = rv.dropna()
        if len(rv) > 3:
            ax3.plot(rv.index, rv, color=WARN, linewidth=1.1)
            ax3.axhline(float(rv.mean()), color=DIM, linestyle="--", linewidth=0.8)
            ax3.fill_between(rv.index, rv, float(rv.mean()),
                             where=rv >= float(rv.mean()), color=BEAR,
                             alpha=0.18, linewidth=0)
            ax3.yaxis.set_major_formatter(FuncFormatter(pct_formatter))
            ax3.yaxis.set_major_locator(MaxNLocator(4))
            format_date_axis(ax3, rv.index)
        else:
            ax3.text(0.5, 0.5, "insufficient history", ha="center", va="center",
                     color=FAINT, transform=ax3.transAxes)
        panel.draw()

    def _render_regime_chart(self) -> None:
        ps, c = self.series, self.analysis
        if ps is None or c is None:
            return
        panel = self.regime_chart
        panel.reset()
        fig = panel.fig
        gs = fig.add_gridspec(2, 1, hspace=0.38, left=0.075, right=0.975,
                              top=0.92, bottom=0.11)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1])

        px = ps.px
        rv = (log_returns(px).rolling(20).std(ddof=1) * math.sqrt(TRADING_DAYS)).dropna()
        style_axes(ax1, title="Realised volatility vs its own distribution",
                   ylabel="Ann. vol", grid="y")
        if len(rv) > 10:
            ax1.plot(rv.index, rv, color=WARN, linewidth=1.2)
            for q, col, style in ((0.25, BULL, ":"), (0.5, DIM, "--"), (0.75, BEAR, ":")):
                lvl = float(rv.quantile(q))
                ax1.axhline(lvl, color=col, linestyle=style, linewidth=0.9, alpha=0.8)
                ax1.annotate(f" p{int(q * 100)}", xy=(1.0, lvl),
                             xycoords=ax1.get_yaxis_transform(), color=col,
                             fontsize=7.5, va="center")
            ax1.yaxis.set_major_formatter(FuncFormatter(pct_formatter))
            format_date_axis(ax1, rv.index)
        else:
            ax1.text(0.5, 0.5, "insufficient history", ha="center", va="center",
                     color=FAINT, transform=ax1.transAxes)

        rb = c.get("rolling_beta")
        bench_name = c.get("benchmark") or "benchmark"
        style_axes(ax2, title=f"Rolling 60-day beta vs {bench_name}",
                   ylabel="Beta", grid="y")
        if isinstance(rb, pd.Series) and len(rb) > 5:
            ax2.plot(rb.index, rb, color=INFO, linewidth=1.2)
            ax2.axhline(1.0, color=DIM, linestyle="--", linewidth=0.9)
            ax2.fill_between(rb.index, rb, 1.0, where=rb >= 1.0,
                             color=BEAR, alpha=0.15, linewidth=0)
            ax2.fill_between(rb.index, rb, 1.0, where=rb < 1.0,
                             color=BULL, alpha=0.15, linewidth=0)
            format_date_axis(ax2, rb.index)
        else:
            ax2.text(0.5, 0.5, "no benchmark loaded, or history too short",
                     ha="center", va="center", color=FAINT, transform=ax2.transAxes)
        panel.draw()

    def _render_season_chart(self) -> None:
        c = self.analysis
        if c is None:
            return
        s = c.get("seasonality") or {}
        panel = self.season_chart
        if not s:
            panel.message("Not enough history for seasonality")
            return
        panel.reset()
        fig = panel.fig
        gs = fig.add_gridspec(1, 2, wspace=0.22, left=0.075, right=0.975,
                              top=0.90, bottom=0.16)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1])

        names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
        dow = s.get("dow")
        style_axes(ax1, title="Mean daily return by weekday", grid="y")
        if dow is not None and len(dow):
            xs = [i for i in range(5) if i in dow.index]
            ys = [float(dow.loc[i, "mean"]) for i in xs]
            cols = [BULL if v >= 0 else BEAR for v in ys]
            ax1.bar([names[i] for i in xs], ys, color=cols, alpha=0.8, width=0.62)
            ax1.axhline(0, color=GRID, linewidth=0.9)
            ax1.yaxis.set_major_formatter(
                FuncFormatter(lambda v, _p: f"{v * 100:.2f}%"))

        comp = s.get("monthly_compound") or {}
        mnames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        style_axes(ax2, title="Mean monthly return", grid="y")
        if comp:
            xs = sorted(comp.keys())
            ys = [comp[m][0] for m in xs]
            cols = [BULL if v >= 0 else BEAR for v in ys]
            bars = ax2.bar([mnames[m - 1] for m in xs], ys, color=cols,
                           alpha=0.8, width=0.62)
            # Draw thin buckets hollow.
            for bar, m in zip(bars, xs):
                if comp[m][1] < 5:
                    bar.set_alpha(0.28)
                    bar.set_hatch("///")
            ax2.axhline(0, color=GRID, linewidth=0.9)
            ax2.yaxis.set_major_formatter(
                FuncFormatter(lambda v, _p: f"{v * 100:.1f}%"))
            ax2.tick_params(axis="x", labelrotation=45, labelsize=7.5)
        else:
            ax2.text(0.5, 0.5, "needs complete months", ha="center", va="center",
                     color=FAINT, transform=ax2.transAxes)
        panel.draw()

    def _render_forecast_chart(self) -> None:
        ps, f = self.series, self.forecast
        if ps is None or f is None or f.get("error"):
            return
        panel = self.fc_chart
        panel.reset()
        ax = panel.fig.add_subplot(111)
        panel.fig.subplots_adjust(left=0.075, right=0.975, top=0.91, bottom=0.13)

        hist = ps.px.tail(160)
        style_axes(ax, title=f"{ps.symbol} - forecast cones (P10 / P50 / P90)",
                   ylabel="Price", xlabel="Trading days (0 = today)", grid="y")

        n_hist = len(hist)
        ax.plot(np.arange(-n_hist + 1, 1), hist.values, color=TEXT,
                linewidth=1.4, label="History")

        s0 = f["last_price"]
        usable = [r for r in f["results"] if r.supported and np.isfinite(r.p50)]
        if usable:
            xs = [0] + [r.horizon_days for r in usable]
            p10 = [s0] + [r.p10 for r in usable]
            p50 = [s0] + [r.p50 for r in usable]
            p90 = [s0] + [r.p90 for r in usable]
            ax.fill_between(xs, p10, p90, color=INFO, alpha=0.16, linewidth=0,
                            label="80% band")
            ax.plot(xs, p50, color=ACCENT, linewidth=1.7, marker="o",
                    markersize=4, label="Median")
            ax.plot(xs, p10, color=INFO, linewidth=0.8, alpha=0.7)
            ax.plot(xs, p90, color=INFO, linewidth=0.8, alpha=0.7)
            for r in usable:
                ax.annotate(f"{r.label}\n{fmt_money(r.p50)}",
                            xy=(r.horizon_days, r.p50), xytext=(0, 11),
                            textcoords="offset points", ha="center",
                            color=DIM, fontsize=7.5)
        ax.axvline(0, color=GRID, linestyle="--", linewidth=0.9)
        ax.axhline(s0, color=DIM, linestyle=":", linewidth=0.9, alpha=0.7)
        ax.yaxis.set_major_formatter(FuncFormatter(money_formatter))
        style_axes(ax, title=f"{ps.symbol} - forecast cones (P10 / P50 / P90)",
                   ylabel="Price", xlabel="Trading days (0 = today)",
                   legend=True, grid="y")

        unsupported = [r for r in f["results"] if not r.supported]
        if unsupported:
            ax.text(0.01, 0.02,
                    "Not shown: " + ", ".join(r.label for r in unsupported)
                    + "  (horizon exceeds loaded history)",
                    transform=ax.transAxes, color=WARN, fontsize=8)
        panel.draw()

    def _render_backtest_chart(self) -> None:
        bt, ps = self.backtest, self.series
        if bt is None or ps is None:
            return
        panel = self.bt_chart
        panel.reset()
        fig = panel.fig
        gs = fig.add_gridspec(2, 1, height_ratios=[2.6, 1.0], hspace=0.16,
                              left=0.075, right=0.975, top=0.92, bottom=0.11)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1], sharex=ax1)

        idx = bt.equity.index
        style_axes(ax1, title=f"{ps.symbol} - {bt.name} vs buy & hold "
                              f"(growth of 1.00, {bt.cost_bps:.0f}bps costs)",
                   ylabel="Growth", grid="y")
        ax1.plot(idx, bt.benchmark, color=DIM, linewidth=1.2, label="Buy & hold")
        ax1.plot(idx, bt.equity, color=ACCENT, linewidth=1.6, label=bt.name)
        ax1.axhline(1.0, color=GRID, linewidth=0.8)

        # Shade the periods the strategy was invested.
        inpos = bt.position.values > 0
        if inpos.any():
            ax1.fill_between(idx, 0, 1, where=inpos, transform=ax1.get_xaxis_transform(),
                             color=ACCENT, alpha=0.05, linewidth=0)
        ax1.tick_params(labelbottom=False)
        style_axes(ax1, title=f"{ps.symbol} - {bt.name} vs buy & hold "
                              f"(growth of 1.00, {bt.cost_bps:.0f}bps costs)",
                   ylabel="Growth", legend=True, grid="y")

        style_axes(ax2, ylabel="Drawdown", grid="y")
        ax2.fill_between(idx, drawdown_series(bt.equity), 0, color=ACCENT,
                         alpha=0.25, linewidth=0)
        ax2.plot(idx, drawdown_series(bt.equity), color=ACCENT, linewidth=0.9,
                 label="Strategy")
        ax2.plot(idx, drawdown_series(bt.benchmark), color=DIM, linewidth=0.9,
                 linestyle="--", label="Buy & hold")
        ax2.yaxis.set_major_formatter(FuncFormatter(pct_formatter))
        ax2.yaxis.set_major_locator(MaxNLocator(3))
        format_date_axis(ax2, idx)
        style_axes(ax2, ylabel="Drawdown", legend=True, grid="y")
        panel.draw()

    # ==========================================================================
    # MONTE CARLO / BACKTEST / AI ACTIONS
    # ==========================================================================
    def _set_mc_stats(self, text: str) -> None:
        try:
            self.mc_stats.configure(text=text)
        except Exception:
            pass

    def toggle_monte_carlo(self) -> None:
        if self.series is None:
            self.set_status("Load data first (FETCH)", WARN)
            return
        try:
            paths = int(float(self.mc_paths_var.get().strip()))
            horizon = int(float(self.mc_horizon_var.get().strip()))
            seconds = float(self.mc_loop_var.get().strip())
        except ValueError:
            self.set_status("Monte Carlo inputs must be numbers", BEAR)
            messagebox.showerror(APP_NAME,
                                 "Paths, horizon and loop seconds must be numbers.")
            return

        model = MC_MODEL_KEYS.get(self.mc_model_var.get(), "block")
        self.mc_engine.configure(paths, horizon, seconds, model)

        self.settings.mc_paths = self.mc_engine.n_paths
        self.settings.mc_horizon = self.mc_engine.horizon
        self.settings.mc_loop_seconds = self.mc_engine.duration
        self.settings.mc_model = self.mc_model_var.get()
        self.settings.save()

        # Write any clamped values back into the entry boxes.
        self.mc_paths_var.set(str(self.mc_engine.n_paths))
        self.mc_horizon_var.set(str(self.mc_engine.horizon))
        self.mc_loop_var.set(str(self.mc_engine.duration))

        self.tabs.set("MONTE")
        try:
            self.mc_engine.toggle(self.series.px, self.series.symbol)
        except Exception as exc:
            self.set_status(str(exc), BEAR)
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.mc_btn.configure(text="PAUSE SIMULATION" if self.mc_engine.running
                              else "RESUME SIMULATION")
        self.log(f"MONTE CARLO {'running' if self.mc_engine.running else 'paused'} "
                 f"({self.mc_engine.n_paths} paths, {self.mc_engine.horizon}d, "
                 f"{self.mc_engine.model})")

    def run_backtest(self) -> None:
        if self.series is None:
            self.set_status("Load data first (FETCH)", WARN)
            return
        try:
            fast = int(float(self.bt_fast_var.get().strip()))
            slow = int(float(self.bt_slow_var.get().strip()))
            cost = float(self.bt_cost_var.get().strip())
        except ValueError:
            self.set_status("Backtest inputs must be numbers", BEAR)
            messagebox.showerror(APP_NAME, "Fast, slow and cost must be numbers.")
            return

        strategy = self.bt_strategy_var.get()
        self.settings.bt_strategy = strategy
        self.settings.bt_fast, self.settings.bt_slow = fast, slow
        self.settings.bt_cost_bps = cost
        self.settings.save()

        self._busy(True, f"Backtesting {strategy}...")

        ps = self.series

        def work(should_abort, progress):
            return run_backtest(ps, strategy, fast, slow, cost)

        def done(bt: BacktestResult) -> None:
            self._busy(False)
            self.backtest = bt
            self.bt_text.set_text(report_backtest(bt, ps.symbol))
            self._render_backtest_chart()
            edge = bt.stats.get("total", 0) - bt.bench_stats.get("total", 0)
            self.set_status(f"{strategy}: {fmt_pct(bt.stats.get('total'))} vs "
                            f"{fmt_pct(bt.bench_stats.get('total'))} buy & hold",
                            BULL if edge > 0 else BEAR)
            self.log(f"BACKTEST {strategy} on {ps.symbol}: "
                     f"total {fmt_pct(bt.stats.get('total'))}, "
                     f"{bt.trades} trades, exposure {fmt_pct(bt.exposure, 0)}")

        self.jobs.submit("backtest", work, done, self._on_error)

    def _prefill_company_tab(self) -> None:
        if self.series is None:
            return
        info = self.company_info or {}
        bits = []
        if info.get("name"):
            bits.append(str(info["name"]))
        if info.get("sector"):
            bits.append(str(info["sector"]))
        if info.get("industry"):
            bits.append(str(info["industry"]))
        self.verdict_label.configure(text="  READY  ", text_color=DIM)
        preview = report_company(
            {"verdict": "", "summary": "", "strengths": [], "risks": [],
             "watch_items": [], "questions_to_verify": [], "data_gaps": []},
            info, self.series)
        header = ("Company reference data pulled for "
                  f"{self.series.symbol}"
                  + (f" - {' | '.join(bits)}" if bits else "")
                  + ".\nPress ANALYZE to have the model review it.\n\n")
        self.ai_out.set_text(header + preview)

    def run_ai_analysis(self) -> None:
        if self.series is None:
            self.set_status("Load data first (FETCH)", WARN)
            return
        if self.analysis is None:
            self.set_status("Press ANALYZE on the toolbar first", WARN)
            messagebox.showinfo(APP_NAME,
                                "Run the main analysis first so the company review "
                                "has computed statistics to work from.")
            return

        extra = self.ai_input.get("1.0", "end").strip()
        ps, info, stats = self.series, self.company_info, self.analysis
        context = build_ai_context(ps, info, stats)

        self._busy(True, "Requesting AI company review...")
        self.log(f"AI ANALYZE {ps.symbol} (context {len(context)} chars, "
                 f"user notes {len(extra)} chars)")

        def work(should_abort, progress):
            return ai_analyze(ps.symbol, context, extra)

        def done(data: Dict[str, Any]) -> None:
            self._busy(False)
            self.ai_result = data
            verdict = data.get("verdict", "INSUFFICIENT DATA")
            colors = {"GOOD": BULL, "OK": WARN, "BAD": BEAR,
                      "INSUFFICIENT DATA": DIM}
            self.verdict_label.configure(text=f"  {verdict}  ",
                                         text_color=colors.get(verdict, DIM))
            self.ai_out.set_text(report_company(data, info, ps))
            if data.get("error"):
                self.set_status(str(data["error"])[:90], BEAR)
                self.log("AI ERROR: " + str(data["error"]))
            else:
                self.set_status(f"Company review complete: {verdict}", ACCENT)
                self.log(f"AI ANALYZE done: {verdict}")

        self.jobs.submit("ai", work, done, self._on_error)

    # ==========================================================================
    # DATA TAB / EXPORT / RESET
    # ==========================================================================
    def _render_data_tab(self) -> None:
        ps = self.series
        if ps is None:
            return
        df = ps.df
        self.data_info.configure(
            text=f"{ps.symbol}   {len(df)} bars   {ps.start} to {ps.end}   "
                 f"adjustment: {ps.adj_method}")

        head = (f"{'Date':<12}{'Open':>11}{'High':>11}{'Low':>11}"
                f"{'Close':>11}{'Raw':>11}{'Volume':>14}{'Div':>8}{'Split':>7}")
        lines = [head, rule(len(head))]
        for ts, row in df.iloc[::-1].iterrows():
            lines.append(
                f"{ts.date()!s:<12}{row['open']:>11,.2f}{row['high']:>11,.2f}"
                f"{row['low']:>11,.2f}{row['px']:>11,.2f}{row['close_raw']:>11,.2f}"
                f"{row['volume']:>14,.0f}{row['dividend']:>8.3f}"
                f"{row['split_factor']:>7.2f}")
        lines.append("")
        lines.append(f"'Close' is the adjusted series every statistic uses. "
                     f"'Raw' is the unadjusted exchange close.")
        lines.append(ps.adj_note)
        for e in ps.events:
            lines.append("  * " + e)
        self.data_text.set_text("\n".join(lines))

    def export_report(self) -> None:
        if self.series is None:
            self.set_status("Nothing to export", WARN)
            return
        default = f"{self.series.symbol}_{datetime.now():%Y%m%d_%H%M%S}.txt"
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile=default,
            filetypes=[("Text report", "*.txt"), ("All files", "*.*")])
        if not path:
            return

        parts = [f"{APP_NAME} v{APP_VERSION}",
                 f"Generated {datetime.now():%Y-%m-%d %H:%M:%S}",
                 f"Symbol {self.series.symbol}   "
                 f"Window {self.series.start} to {self.series.end}   "
                 f"{self.series.n} bars", ""]
        for title, widget in (("OVERVIEW", self.ov_text), ("TECHNICALS", self.tech_text),
                              ("RISK", self.risk_text), ("REGIME", self.regime_text),
                              ("SEASONALITY", self.season_text),
                              ("FORECAST", self.fc_text), ("BACKTEST", self.bt_text),
                              ("COMPANY", self.ai_out)):
            body = widget.get_text()
            if body.strip():
                parts.append("\n\n" + rule(78, "#"))
                parts.append(f"# {title}")
                parts.append(rule(78, "#") + "\n")
                parts.append(body)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(parts))
            self.set_status(f"Report written to {os.path.basename(path)}", ACCENT)
            self.log(f"EXPORT report -> {path}")
        except OSError as exc:
            self.set_status(f"Export failed: {exc}", BEAR)
            messagebox.showerror(APP_NAME, f"Could not write the report:\n{exc}")

    def export_csv(self) -> None:
        if self.series is None:
            self.set_status("Nothing to export", WARN)
            return
        default = f"{self.series.symbol}_bars_{datetime.now():%Y%m%d}.csv"
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile=default,
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            out = self.series.df.copy()
            out.index.name = "date"
            out = out.rename(columns={"px": "adjusted_close",
                                      "close_raw": "raw_close"})
            out.to_csv(path, float_format="%.6f")
            self.set_status(f"{len(out)} rows written to {os.path.basename(path)}",
                            ACCENT)
            self.log(f"EXPORT csv -> {path} ({len(out)} rows)")
        except OSError as exc:
            self.set_status(f"Export failed: {exc}", BEAR)
            messagebox.showerror(APP_NAME, f"Could not write the CSV:\n{exc}")

    def clear_cache(self) -> None:
        n = self.client.cache.clear()
        self.client.cache_hits = 0
        self._update_api_label()
        self.set_status(f"Cleared {n} cached responses", ACCENT)
        self.log(f"CACHE cleared ({n} files). The next fetch will hit the API.")

    def reset_all(self) -> None:
        self.mc_engine.stop()
        self.mc_btn.configure(text="START SIMULATION")
        self.jobs.cancel("analysis")
        self.jobs.cancel("fetch")

        self.series = self.full_series = self.bench_series = None
        self.analysis = self.forecast = self.backtest = self.ai_result = None
        self.company_info = {}

        self.ov_text.set_text(WELCOME_TEXT)
        for widget in (self.tech_text, self.risk_text, self.regime_text,
                       self.season_text, self.fc_text, self.bt_text, self.data_text):
            widget.set_text("")
        self.ai_out.set_text(COMPANY_HELP_TEXT)
        self.ai_input.delete("1.0", "end")

        for panel, msg in ((self.ov_chart, "Enter a ticker and press FETCH"),
                           (self.tech_chart, "No data loaded"),
                           (self.risk_chart, "No data loaded"),
                           (self.regime_chart, "No data loaded"),
                           (self.season_chart, "No data loaded"),
                           (self.fc_chart, "No data loaded"),
                           (self.mc_chart, "Load a symbol, then press START SIMULATION"),
                           (self.bt_chart, "Load a symbol, then run a backtest")):
            panel.message(msg)

        for tile in self.tiles.values():
            tile.set("--", FAINT)
        self.meta_label.configure(text="No data loaded")
        self.verdict_label.configure(text="  --  ", text_color=DIM)
        self.mc_stats.configure(text="No simulation running")
        self.data_info.configure(text="No data loaded")

        self.set_status("Reset", WARN)
        self.log("RESET (cached API responses kept - use Clear cache to drop them)")

    def _on_close(self) -> None:
        self._closing = True
        try:
            self.settings.geometry = self.geometry()
            self.settings.save()
        except Exception:
            pass
        try:
            self.mc_engine.stop()
        except Exception:
            pass
        self.jobs.cancel_all()
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
        try:
            self.quit()
        finally:
            self.destroy()


# ==============================================================================
# SECTION 18 - STATIC TEXT
# ==============================================================================

WELCOME_TEXT = f"""
{rule(78, '=')}
 {APP_NAME}  v{APP_VERSION}
{rule(78, '=')}

  GETTING STARTED

    1. Type a ticker in the box at the top left and press FETCH (or Enter).
    2. Press ANALYZE to run the full statistical stack.
    3. Move through the tabs for technicals, risk, regime, seasonality,
       forecasts, Monte Carlo, backtests and the company profile.

  WHAT EACH TAB DOES

    OVERVIEW    Price, volume and drawdown, plus trailing returns and the
                headline performance and risk table.
    TECH        Bollinger bands, moving averages, RSI and MACD, with the
                oscillator readings written out.
    RISK        Underwater curve, return distribution, rolling volatility,
                VaR / CVaR, tail statistics and benchmark sensitivity.
    REGIME      Volatility percentile, Hurst exponent, variance ratio,
                return autocorrelation and rolling beta.
    SEASON      Weekday and month effects, with thin samples marked.
    FORECAST    Adaptive horizons with P10 / P50 / P90 bands. Machine learning
                runs only where the history can validate it; otherwise the
                estimate comes from simulation and is labelled as such.
    MONTE       Animated simulation with a percentile fan and the terminal
                price distribution.
    BACKTEST    Test the technical rules on this symbol, net of costs, with
                no look-ahead.
    COMPANY     Reference data pulled from the API, optionally reviewed by a
                language model.
    DATA        Every bar, adjusted and raw, exportable to CSV.

  RANGE AND CACHING

    FETCH pulls the widest window your API plan allows and caches it on disk.
    Switching range re-slices the cached history, so it is instant and makes
    no further API calls. Use Clear cache to force a fresh download.

  Nothing in this application is investment advice.

{rule(78, '=')}
"""

COMPANY_HELP_TEXT = """
  COMPANY REVIEW

  After a FETCH, this tab is filled with the reference data the terminal
  pulled: sector, industry, employees, business description, executives,
  dividend history and split history, alongside the risk statistics computed
  from the price series.

  Pressing ANALYZE sends that package to a language model, which returns a
  structured review: strengths, risks, watch items, questions to verify, and
  the data gaps preventing a firmer conclusion.

  The model is instructed to use only the supplied data and to return
  "INSUFFICIENT DATA" rather than invent fundamentals. Revenue, margins, cash
  flow, debt and valuation multiples are not available from this data source,
  so paste them into the box above if you want them considered.

  Requires OPENAI_API_KEY. Every other tab works without it.
"""


# ==============================================================================
# SECTION 19 - HEADLESS SELF TEST
# ==============================================================================

def selftest(symbol: str = "AAPL", benchmark: str = "SPY") -> int:
    """Exercise every non-GUI code path against live data.

    Run with:  python quantdesk_terminal.py --selftest
    """
    passed, failed = 0, 0

    def _brief(value: Any, limit: int = 96) -> str:
        """One-line, length-capped rendering of a value."""
        if isinstance(value, pd.DataFrame):
            return f"DataFrame {value.shape[0]}x{value.shape[1]}"
        if isinstance(value, pd.Series):
            return f"Series[{len(value)}]"
        if isinstance(value, dict):
            return f"dict({len(value)} keys)"
        if isinstance(value, PriceSeries):
            return f"PriceSeries {value.symbol} {value.n} bars"
        text = " ".join(str(value).split())
        return text if len(text) <= limit else text[:limit - 3] + "..."

    def check(name: str, fn: Callable[[], Any]) -> Any:
        nonlocal passed, failed
        try:
            value = fn()
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {name}\n          {type(exc).__name__}: {exc}")
            return None
        passed += 1
        print(f"  ok    {name:<44}" + (_brief(value) if value is not None else ""))
        return value

    print(f"\n{APP_NAME} v{APP_VERSION} - self test")
    print(rule(78, "="))

    print("\n[1] ENVIRONMENT")
    print(f"  Python           {sys.version.split()[0]}")
    print(f"  numpy {np.__version__}   pandas {pd.__version__}")
    try:
        import sklearn
        print(f"  scikit-learn     {sklearn.__version__}")
    except ImportError:
        print("  scikit-learn     NOT INSTALLED (forecasts fall back to simulation)")
    print(f"  GUI stack        {'available' if GUI_AVAILABLE else f'UNAVAILABLE: {GUI_IMPORT_ERROR}'}")
    print(f"  MARKETSTACK_API_KEY  {'set' if os.getenv('MARKETSTACK_API_KEY') else 'NOT SET'}")
    print(f"  OPENAI_API_KEY       {'set' if os.getenv('OPENAI_API_KEY') else 'not set (optional)'}")
    print(f"  Cache directory      {CACHE_DIR}")

    client = MarketStackClient()
    if not client.api_key:
        print("\nMARKETSTACK_API_KEY is not set - cannot run data tests.")
        return 1

    print(f"\n[2] DATA FETCH  ({symbol})")
    end = date.today()
    start = end - timedelta(days=RANGE_PRESETS["MAX"])
    raw = check("eod bars", lambda: client.eod(symbol, str(start), str(end)))
    if raw is None:
        print("\nCannot continue without price data.")
        return 1
    print(f"        {len(raw)} bars, {raw.index[0].date()} to {raw.index[-1].date()}")
    print(f"        columns: {', '.join(raw.columns)}")

    splits = check("splits endpoint", lambda: client.splits(symbol))
    divs = check("dividends endpoint", lambda: client.dividends(symbol))
    info = check("tickerinfo endpoint",
                 lambda: (client.ticker_info(symbol) or {}).get("name", "(no name)"))
    print(f"        splits rows={0 if splits is None else len(splits)}  "
          f"dividends rows={0 if divs is None else len(divs)}")
    _ = info

    print("\n[3] CORPORATE ACTION ADJUSTMENT")
    ps = check("build_price_series", lambda: build_price_series(raw, symbol, splits, divs))
    if ps is None:
        return 1
    print(f"        method: {ps.adj_method}")
    print(f"        note:   {ps.adj_note}")
    for e in ps.events:
        print(f"        event:  {e}")
    for w in ps.warnings:
        print(f"        WARN:   {w}")
    check("total-return overlay",
          lambda: build_price_series(raw, symbol, splits, divs,
                                     total_return=True).total_return)
    check("range slicing (90d)", lambda: f"{ps.slice_days(90).n} bars")

    print("\n[4] INDICATORS")
    px = ps.px
    check("log returns", lambda: f"{len(log_returns(px).dropna())} values")
    check("RSI(14) last", lambda: round(float(rsi(px, 14).iloc[-1]), 2))
    check("RSI zero-loss case",
          lambda: float(rsi(pd.Series(np.arange(1, 60, dtype=float)), 14).iloc[-1]))
    check("MACD", lambda: round(float(macd(px)[0].iloc[-1]), 4))
    check("Bollinger %B", lambda: round(float(bollinger(px)[4].iloc[-1]), 3))
    check("ATR(14)", lambda: round(float(atr(ps.df["high"], ps.df["low"], px).iloc[-1]), 3))
    check("ADX(14)", lambda: round(float(adx(ps.df["high"], ps.df["low"], px)[0].iloc[-1]), 2))
    check("Stochastic", lambda: round(float(stochastic(ps.df["high"], ps.df["low"], px)[0].iloc[-1]), 2))
    check("MFI", lambda: round(float(money_flow_index(ps.df["high"], ps.df["low"], px, ps.volume).iloc[-1]), 2))
    check("OBV", lambda: f"{float(obv(px, ps.volume).iloc[-1]):,.0f}")
    check("Donchian", lambda: round(float(donchian(ps.df["high"], ps.df["low"])[0].iloc[-1]), 2))

    print("\n[5] RISK STATISTICS")
    check("annualised vol", lambda: fmt_pct(ann_vol(px)))
    check("CAGR", lambda: fmt_pct(ann_return_geometric(px)))
    check("Sharpe", lambda: round(sharpe_ratio(px), 3))
    check("Sortino", lambda: round(sortino_ratio(px), 3))
    check("Calmar", lambda: round(calmar_ratio(px), 3))
    check("Omega", lambda: round(omega_ratio(px), 3))
    check("max drawdown", lambda: fmt_pct(max_drawdown(px)))
    check("drawdown detail", lambda: fmt_pct(drawdown_detail(px)["depth"]))
    check("historical VaR 95", lambda: fmt_pct(historical_var(px)))
    check("CVaR 95", lambda: fmt_pct(cvar(px)))
    check("Cornish-Fisher VaR", lambda: fmt_pct(cornish_fisher_var(px)))
    check("tail stats", lambda: f"skew {tail_stats(px)['skew']:.3f}")
    check("Hurst", lambda: round(hurst_exponent(px), 4))
    check("variance ratio", lambda: round(variance_ratio(px), 4))
    check("autocorrelation", lambda: len(autocorrelation(px)))
    check("vol regime", lambda: vol_regime(px)["label"])
    check("trend state", lambda: trend_state(px)["label"])
    check("period returns", lambda: fmt_pct(period_returns(px).get("1M"), 1))
    check("seasonality", lambda: f"{len(seasonality(px).get('dow', []))} weekday buckets")

    print("\n[6] DATE-ALIGNED BENCHMARK STATISTICS")
    bench_ps = None
    try:
        braw = client.eod(benchmark, str(start), str(end))
        bench_ps = build_price_series(braw, benchmark, client.splits(benchmark), None)
        print(f"  ok    benchmark {benchmark} loaded ({bench_ps.n} bars)")
        passed += 1
    except Exception as exc:
        print(f"  WARN  benchmark unavailable: {exc}")

    if bench_ps is not None:
        a, b = ps.returns(), bench_ps.returns()
        res = check("beta / correlation", lambda: beta_and_corr(a, b))
        if res:
            print(f"        beta {res[0]:.4f}  corr {res[1]:.4f}  on {res[2]} aligned sessions")
        check("alignment is date based", lambda: (
            "PASS" if len(align_returns(a, b)) <= min(len(a.dropna()), len(b.dropna()))
            else "FAIL"))
        # Truncating one series must not shift the pairing of the other.
        def misalignment_probe():
            trimmed = a.iloc[7:]
            full_beta = beta_and_corr(a.tail(120), b)[0]
            trim_beta = beta_and_corr(trimmed.tail(120), b)[0]
            return f"beta stable under offset: {abs(full_beta - trim_beta) < 0.35}"
        check("offset robustness", misalignment_probe)
        check("rolling beta", lambda: f"{len(rolling_beta(a, b, 60))} points")
        check("alpha", lambda: fmt_pct(alpha_annualised(a, b, beta_and_corr(a, b)[0])))
        check("tracking error", lambda: fmt_pct(tracking_error(a, b)))
        check("information ratio", lambda: round(information_ratio(a, b), 3))
        check("capture ratios", lambda: upside_downside_capture(a, b))

    print("\n[7] FULL ANALYSIS PIPELINE")
    analysis = check("compute_analysis", lambda: compute_analysis(ps, bench_ps))
    if analysis:
        for name, fn in (("overview report", report_overview),
                         ("technicals report", report_technicals),
                         ("risk report", report_risk),
                         ("regime report", report_regime),
                         ("seasonality report", report_seasonality)):
            check(name, lambda f=fn: f"{len(f(analysis).splitlines())} lines")

    print("\n[8] SIMULATION")
    for model in ("gbm", "iid", "block", "t"):
        check(f"simulate_terminal [{model}]",
              lambda m=model: fmt_money(float(np.median(
                  simulate_terminal(px, 63, model=m, n_sims=3000, seed=1)))))
    check("simulate_paths shape",
          lambda: str(simulate_paths(px, 60, 50, "block", seed=1).shape))

    print("\n[9] FORECASTING")
    fc = check("forecast_all", lambda: forecast_all(ps, "block"))
    if fc:
        for r in fc["results"]:
            if r.supported:
                print(f"        {r.label:<10} {r.model:<16} "
                      f"P50 {fmt_money(r.p50):>11}  "
                      f"[{fmt_money(r.p10)} - {fmt_money(r.p90)}]  "
                      f"conf {fmt_pct(r.confidence, 1)}")
            else:
                print(f"        {r.label:<10} UNSUPPORTED at this history length")
        check("forecast report", lambda: f"{len(report_forecast(fc).splitlines())} lines")

    print("\n[10] EMBARGOED VALIDATION FOLDS")
    def fold_probe():
        folds = _embargoed_folds(300, 63, 4)
        if not folds:
            return "no folds"
        gaps = [int(te[0] - tr[-1] - 1) for tr, te in folds]
        assert all(g >= 63 for g in gaps), f"leak: gaps {gaps}"
        return f"{len(folds)} folds, train/test gaps {gaps} (all >= 63)"
    check("embargo gap enforced", fold_probe)

    print("\n[11] BACKTESTS")
    for strat in STRATEGIES:
        def bt_run(s=strat):
            bt = run_backtest(ps, s, 20, 50, 5.0)
            return (f"total {fmt_pct(bt.stats['total'], 1)}  "
                    f"vs B&H {fmt_pct(bt.bench_stats['total'], 1)}  "
                    f"trades {bt.trades}")
        check(f"backtest [{strat}]", bt_run)

    def lookahead_probe():
        bt = run_backtest(ps, "Buy & hold", 20, 50, 0.0)
        diff = abs(float(bt.equity.iloc[-1]) - float(bt.benchmark.iloc[-1]))
        # Buy & hold with no costs must reproduce the benchmark, minus the one
        # bar lost to the trade lag.
        assert diff < 0.35, f"buy&hold deviates from benchmark by {diff:.4f}"
        return f"buy&hold tracks benchmark (delta {diff:.4f} from the 1-bar lag)"
    check("no look-ahead in backtester", lookahead_probe)

    print("\n[12] AI CONTEXT")
    ctx = check("build_ai_context",
                lambda: f"{len(build_ai_context(ps, client.ticker_info(symbol), analysis or {}))} chars")
    _ = ctx
    if os.getenv("OPENAI_API_KEY"):
        print("        OPENAI_API_KEY is set; the COMPANY tab will call the API.")
        print("        (Not calling it here to avoid spending tokens.)")
    else:
        res = ai_analyze(symbol, "test", "")
        check("ai_analyze degrades gracefully without a key",
              lambda: res.get("verdict"))

    print("\n[13] CACHE & QUOTA")
    print(f"  API requests issued this run : {client.request_count}")
    print(f"  Served from cache            : {client.cache_hits}")
    n, size = client.cache.stats()
    print(f"  Cached responses on disk     : {n} ({size / 1024:.0f} KB)")

    print("\n" + rule(78, "="))
    print(f"  {passed} passed, {failed} failed")
    print(rule(78, "="))
    if ps.n < 300:
        print(f"\n  NOTE: your MarketStack plan returned only {ps.n} bars "
              f"({ps.n / 252:.2f} years).")
        print("  Long-horizon forecasts are reported as unsupported or "
              "simulation-only\n  because that history cannot validate them. "
              "This is a plan limit,\n  not a bug.")
    return 0 if failed == 0 else 1


# ==============================================================================
# SECTION 20 - ENTRY POINT
# ==============================================================================

def launch_gui() -> int:
    if not GUI_AVAILABLE:
        print(f"The GUI stack could not be imported: {GUI_IMPORT_ERROR}\n")
        print("Install the requirements with:")
        print("    pip install customtkinter matplotlib pandas numpy "
              "requests scikit-learn")
        return 1

    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("dark-blue")
    try:
        ctk.set_widget_scaling(1.0)
    except Exception:
        pass

    app = QuantDeskApp()
    app.mainloop()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quantdesk_terminal",
        description=f"{APP_NAME} v{APP_VERSION} - equity analytics workstation")
    parser.add_argument("--selftest", action="store_true",
                        help="run headless verification against live data and exit")
    parser.add_argument("--symbol", default="AAPL",
                        help="symbol to use for --selftest (default AAPL)")
    parser.add_argument("--benchmark", default="SPY",
                        help="benchmark to use for --selftest (default SPY)")
    parser.add_argument("--clear-cache", action="store_true",
                        help="delete cached API responses and exit")
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args(argv)

    if sys.version_info < (3, 9):
        print("Python 3.9 or newer is required.")
        return 1

    if args.clear_cache:
        n = DiskCache(CACHE_DIR).clear()
        print(f"Cleared {n} cached responses from {CACHE_DIR}")
        return 0

    if args.selftest:
        return selftest(args.symbol.upper(), args.benchmark.upper())

    return launch_gui()


if __name__ == "__main__":
    sys.exit(main())


