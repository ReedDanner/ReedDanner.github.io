"""
Market-data providers behind one swappable interface.

:class:`DataProvider` is the contract.  :class:`YahooProvider` is the default
and talks to Yahoo's JSON endpoints directly; :class:`YFinanceProvider` wraps
the ``yfinance`` package as a fallback; :class:`SyntheticProvider` generates
deterministic offline fixtures.  Adding an API-key provider means implementing
three methods -- nothing above this layer knows where the bars came from.

Why the direct provider exists
------------------------------
Yahoo returns **HTTP 429 "Too Many Requests" to any request without a browser
User-Agent**, regardless of how few requests you have made.  It is an identity
check reported as a rate limit, and it is why the old yfinance-only path
appeared permanently throttled.  Two further wrinkles:

* ``/v8/finance/chart`` needs only the User-Agent.
* ``/v7/finance/quote`` and ``/v7/finance/options`` additionally need Yahoo's
  cookie + "crumb" handshake, or they answer 401 Unauthorized.

:class:`YahooProvider` does all three: browser headers, a lazily fetched crumb
that is refreshed automatically on 401, and exponential backoff with jitter on
genuine 429/5xx responses.

Every public call returns a result object carrying a :class:`DataStatus`
instead of raising, because the UI needs to *show* a degraded state, not crash
on one.  The status drives the status LED in the top bar.
"""

from __future__ import annotations

import hashlib
import io
import random
import threading
import time
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .cache import BarCache, Coverage

__all__ = [
    "Health", "DataStatus", "Quote", "HistoryResult", "ChainResult",
    "DataProvider", "YahooProvider", "YFinanceProvider", "SyntheticProvider",
    "ChainedProvider", "MarketData", "PERIODS", "INTERVALS", "interval_to_dt",
    "BROWSER_HEADERS",
]

#: Selectable lookback periods, mapped to an approximate number of days.
#: The keys are also valid Yahoo ``range`` values.
PERIODS: Dict[str, Optional[int]] = {
    "1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731,
    "5y": 1827, "10y": 3653, "max": None,
}

#: Selectable bar intervals, mapped to the year fraction of one bar.
INTERVALS: Dict[str, float] = {
    "1d": 1.0 / 252.0,
    "1wk": 1.0 / 52.0,
    "1mo": 1.0 / 12.0,
    "1h": 1.0 / (252.0 * 6.5),
    "30m": 1.0 / (252.0 * 13.0),
    "15m": 1.0 / (252.0 * 26.0),
}

#: Yahoo caps how far back intraday bars go.  Requesting more returns an error,
#: so the period is clamped to these maxima per interval.
_INTRADAY_MAX_DAYS: Dict[str, int] = {"1h": 720, "30m": 59, "15m": 59}

#: Yahoo rejects anything that does not look like a browser.  This is the whole
#: fix for the "rate limited" 429s -- see the module docstring.
BROWSER_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


def interval_to_dt(interval: str) -> float:
    """Year fraction of one bar at ``interval`` (defaults to one trading day)."""
    return INTERVALS.get(interval, 1.0 / 252.0)


class Health(Enum):
    """Status-LED states for the data source."""

    LIVE = "live"            # green: fresh data straight from the provider
    CACHED = "cached"        # amber: served from the local cache
    STALE = "stale"          # amber: cache used because the provider failed
    SYNTHETIC = "synthetic"  # blue: generated data, no provider involved
    ERROR = "error"          # red: nothing usable


@dataclass
class DataStatus:
    """Outcome of a data request, including why it degraded."""

    health: Health
    message: str = ""
    source: str = ""
    age_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.health in (Health.LIVE, Health.CACHED, Health.SYNTHETIC)

    @property
    def is_real(self) -> bool:
        """True when the numbers came from a real market-data feed."""
        return self.health in (Health.LIVE, Health.CACHED, Health.STALE)


@dataclass
class Quote:
    """Latest price snapshot."""

    ticker: str
    price: float = float("nan")
    prev_close: float = float("nan")
    currency: str = "USD"
    name: str = ""
    status: DataStatus = field(
        default_factory=lambda: DataStatus(Health.ERROR, "no quote")
    )

    @property
    def change(self) -> float:
        if not (np.isfinite(self.price) and np.isfinite(self.prev_close)):
            return float("nan")
        return self.price - self.prev_close

    @property
    def change_pct(self) -> float:
        if not (np.isfinite(self.price) and np.isfinite(self.prev_close)) \
                or self.prev_close == 0:
            return float("nan")
        return (self.price / self.prev_close - 1.0) * 100.0


@dataclass
class HistoryResult:
    """OHLCV history plus the status of how it was obtained."""

    ticker: str
    interval: str
    frame: pd.DataFrame
    status: DataStatus

    @property
    def empty(self) -> bool:
        return self.frame is None or len(self.frame) == 0

    @property
    def close(self) -> np.ndarray:
        if self.empty:
            return np.array([], dtype=float)
        col = "close" if "close" in self.frame.columns else self.frame.columns[-2]
        return self.frame[col].to_numpy(dtype=float)

    @property
    def spot(self) -> float:
        c = self.close
        return float(c[-1]) if c.size else float("nan")


@dataclass
class ChainResult:
    """Option chain plus status.  ``frame`` may be empty for names without options."""

    ticker: str
    frame: pd.DataFrame
    spot: float
    status: DataStatus


# --------------------------------------------------------------------------
# the interface
# --------------------------------------------------------------------------
class DataProvider(ABC):
    """Contract every market-data source must satisfy.

    Implementations must **never raise** for ordinary failure (bad ticker,
    timeout, rate limit, empty response).  They return an empty frame with an
    ``ERROR`` status and let the caller decide what to do -- normally fall back
    to the cache.  Only programming errors should propagate.
    """

    #: Short label shown in the UI.
    name: str = "abstract"

    @abstractmethod
    def get_history(
        self, ticker: str, period: str = "2y", interval: str = "1d"
    ) -> HistoryResult:
        """Fetch OHLCV bars."""

    @abstractmethod
    def get_quote(self, ticker: str) -> Quote:
        """Fetch the latest price and previous close."""

    @abstractmethod
    def get_option_chain(self, ticker: str, max_expiries: int = 8) -> ChainResult:
        """Fetch an option chain, or an empty frame when none is available."""


# --------------------------------------------------------------------------
# Yahoo, spoken directly
# --------------------------------------------------------------------------
class YahooProvider(DataProvider):
    """Default provider: Yahoo Finance JSON endpoints over plain ``requests``.

    Talking to the endpoints directly rather than through ``yfinance`` buys
    three things that matter here: the browser headers that stop the spurious
    429s, an explicit cookie/crumb handshake that can be refreshed mid-session,
    and retry/backoff we control.

    Endpoints used
    --------------
    ``/v8/finance/chart/{sym}``     OHLCV + adjusted close + a live price in
                                    ``meta``.  Needs only the User-Agent.
    ``/v7/finance/quote``           batch quotes.  Needs the crumb.
    ``/v7/finance/options/{sym}``   option chain per expiry.  Needs the crumb.

    Adjustment
    ----------
    Yahoo returns raw OHLC plus a separate ``adjclose``.  Every OHLC column is
    scaled by ``adjclose/close`` so the whole bar is consistent -- the same
    thing ``yfinance``'s ``auto_adjust=True`` does.  The result is a total
    return series, correct for volatility and return estimation but *not* the
    traded price, which matters when comparing against option strikes.

    Threading
    ---------
    One :class:`requests.Session` guarded by a lock.  Requests are serialised,
    which is fine at this volume and has the side benefit of never bursting
    Yahoo with parallel calls from the basket loader.
    """

    name = "yahoo"

    _CHART = "https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
    _QUOTE = "https://query2.finance.yahoo.com/v7/finance/quote"
    _OPTIONS = "https://query2.finance.yahoo.com/v7/finance/options/{sym}"
    _CRUMB = "https://query2.finance.yahoo.com/v1/test/getcrumb"
    _COOKIE_SEEDS = ("https://fc.yahoo.com",
                     "https://finance.yahoo.com/quote/SPY")

    def __init__(self, timeout: int = 20, max_retries: int = 3,
                 crumb_ttl: float = 1800.0) -> None:
        self.timeout = int(timeout)
        self.max_retries = int(max_retries)
        self.crumb_ttl = float(crumb_ttl)
        self._session = None
        self._crumb: Optional[str] = None
        self._crumb_at: float = 0.0
        self._lock = threading.RLock()

    # -- session / crumb -------------------------------------------------
    def _get_session(self):
        import requests

        if self._session is None:
            s = requests.Session()
            s.headers.update(BROWSER_HEADERS)
            self._session = s
        return self._session

    def _ensure_crumb(self, force: bool = False) -> Optional[str]:
        """Fetch (or refresh) Yahoo's cookie + crumb pair.

        The crumb is a short opaque token tied to the session cookie.  Without
        it the ``/v7`` endpoints answer 401.  It is cached for ``crumb_ttl``
        seconds and refreshed on demand when a call comes back 401.
        """
        with self._lock:
            fresh = (self._crumb and not force
                     and (time.time() - self._crumb_at) < self.crumb_ttl)
            if fresh:
                return self._crumb
            session = self._get_session()
            if force:
                session.cookies.clear()
            try:
                for seed in self._COOKIE_SEEDS:
                    try:
                        session.get(seed, timeout=self.timeout,
                                    allow_redirects=True)
                    except Exception:
                        continue
                    if len(session.cookies):
                        break
                resp = session.get(self._CRUMB, timeout=self.timeout)
                token = (resp.text or "").strip()
                # a valid crumb is a short opaque string, never HTML
                if resp.status_code == 200 and 0 < len(token) < 32 \
                        and "<" not in token:
                    self._crumb = token
                    self._crumb_at = time.time()
                    return token
            except Exception:
                pass
            self._crumb = None
            return None

    def _request(self, url: str, params: Optional[Dict] = None,
                 need_crumb: bool = False):
        """GET with crumb injection, 401 crumb-refresh and 429/5xx backoff.

        Returns the ``requests.Response`` or raises the last exception.  Backoff
        is exponential with jitter, because a genuine 429 from Yahoo clears in
        seconds but hammering it extends the block.
        """
        import requests

        session = self._get_session()
        params = dict(params or {})
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries):
            if need_crumb:
                crumb = self._ensure_crumb(force=attempt > 0)
                if crumb:
                    params["crumb"] = crumb
            try:
                with self._lock:
                    resp = session.get(url, params=params, timeout=self.timeout)
            except Exception as exc:
                last_exc = exc
                time.sleep(_backoff(attempt))
                continue

            if resp.status_code == 200:
                return resp
            if resp.status_code in (401, 403) and need_crumb:
                self._ensure_crumb(force=True)   # crumb expired -> retry
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(_backoff(attempt))
                continue
            return resp  # 404 and friends: report as-is, retrying will not help

        if last_exc is not None:
            raise last_exc
        return resp

    # -- history ---------------------------------------------------------
    def get_history(
        self, ticker: str, period: str = "2y", interval: str = "1d"
    ) -> HistoryResult:
        t = str(ticker).upper().strip()
        empty = pd.DataFrame()
        if not t:
            return HistoryResult(t, interval, empty,
                                 DataStatus(Health.ERROR, "empty ticker"))
        rng = _clamp_range(period, interval)
        try:
            resp = self._request(
                self._CHART.format(sym=t),
                {"range": rng, "interval": interval, "events": "div,split",
                 "includeAdjustedClose": "true"},
            )
        except Exception as exc:
            return HistoryResult(t, interval, empty, DataStatus(
                Health.ERROR, f"{type(exc).__name__}: {exc}"[:200],
                source=self.name))

        if resp.status_code != 200:
            return HistoryResult(t, interval, empty, DataStatus(
                Health.ERROR, _http_message(resp, t), source=self.name))
        try:
            payload = resp.json()
        except ValueError:
            return HistoryResult(t, interval, empty, DataStatus(
                Health.ERROR, "malformed response from Yahoo", source=self.name))

        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            desc = chart["error"].get("description") or chart["error"].get("code")
            return HistoryResult(t, interval, empty, DataStatus(
                Health.ERROR, f"{t}: {desc}", source=self.name))
        results = chart.get("result") or []
        if not results:
            return HistoryResult(t, interval, empty, DataStatus(
                Health.ERROR, f"no data returned for {t}", source=self.name))

        frame = _chart_to_frame(results[0])
        if frame.empty:
            return HistoryResult(t, interval, empty, DataStatus(
                Health.ERROR, f"no usable bars for {t}", source=self.name))
        meta = results[0].get("meta") or {}
        currency = str(meta.get("currency") or "USD")
        return HistoryResult(t, interval, frame, DataStatus(
            Health.LIVE, f"{len(frame)} bars ({currency}) from Yahoo",
            source=self.name))

    # -- quote -----------------------------------------------------------
    def get_quote(self, ticker: str) -> Quote:
        t = str(ticker).upper().strip()
        if not t:
            return Quote(t, status=DataStatus(Health.ERROR, "empty ticker"))
        try:
            resp = self._request(self._QUOTE, {"symbols": t}, need_crumb=True)
            if resp.status_code == 200:
                rows = ((resp.json() or {}).get("quoteResponse") or {}).get("result") or []
                if rows:
                    row = rows[0]
                    price = _first_finite(row.get("regularMarketPrice"),
                                          row.get("postMarketPrice"))
                    prev = _first_finite(row.get("regularMarketPreviousClose"),
                                         row.get("previousClose"))
                    if np.isfinite(price):
                        return Quote(
                            ticker=t, price=float(price),
                            prev_close=float(prev) if np.isfinite(prev) else float(price),
                            currency=str(row.get("currency") or "USD"),
                            name=str(row.get("shortName") or row.get("longName") or ""),
                            status=DataStatus(Health.LIVE, "quote ok",
                                              source=self.name),
                        )
        except Exception:
            pass  # fall through to the chart-meta route

        # The chart endpoint needs no crumb and carries a live price in its
        # metadata, so it is a reliable second route when /v7/quote is blocked.
        try:
            resp = self._request(self._CHART.format(sym=t),
                                 {"range": "5d", "interval": "1d"})
            if resp.status_code == 200:
                results = (((resp.json() or {}).get("chart") or {}).get("result") or [])
                if results:
                    meta = results[0].get("meta") or {}
                    price = _first_finite(meta.get("regularMarketPrice"))
                    prev = _first_finite(meta.get("previousClose"),
                                         meta.get("chartPreviousClose"))
                    if not np.isfinite(prev):
                        closes = _chart_to_frame(results[0])["close"].to_numpy(float)
                        prev = closes[-2] if closes.size > 1 else price
                    if np.isfinite(price):
                        return Quote(
                            ticker=t, price=float(price),
                            prev_close=float(prev) if np.isfinite(prev) else float(price),
                            currency=str(meta.get("currency") or "USD"),
                            name=str(meta.get("longName") or meta.get("shortName") or ""),
                            status=DataStatus(Health.LIVE, "quote via chart meta",
                                              source=self.name),
                        )
        except Exception as exc:
            return Quote(t, status=DataStatus(
                Health.ERROR, f"{type(exc).__name__}: {exc}"[:200],
                source=self.name))
        return Quote(t, status=DataStatus(Health.ERROR, f"no quote for {t}",
                                          source=self.name))

    # -- option chain ----------------------------------------------------
    def get_option_chain(self, ticker: str, max_expiries: int = 8) -> ChainResult:
        """Flatten the first ``max_expiries`` expiries into one tidy frame.

        The first call returns both the nearest expiry's contracts and the full
        list of expiration dates; subsequent expiries are fetched by passing
        ``date=<epoch>``.  ``mid`` is the bid-ask midpoint where both sides are
        present and positive, falling back to ``lastPrice`` -- last trades on
        illiquid strikes can be hours stale, so a two-sided market always wins.
        """
        t = str(ticker).upper().strip()
        empty = pd.DataFrame()
        if not t:
            return ChainResult(t, empty, float("nan"),
                               DataStatus(Health.ERROR, "empty ticker"))
        try:
            resp = self._request(self._OPTIONS.format(sym=t), need_crumb=True)
        except Exception as exc:
            return ChainResult(t, empty, float("nan"), DataStatus(
                Health.ERROR, f"{type(exc).__name__}: {exc}"[:200],
                source=self.name))
        if resp.status_code != 200:
            return ChainResult(t, empty, float("nan"), DataStatus(
                Health.ERROR, _http_message(resp, t), source=self.name))
        try:
            payload = (resp.json() or {}).get("optionChain") or {}
        except ValueError:
            return ChainResult(t, empty, float("nan"), DataStatus(
                Health.ERROR, "malformed option response", source=self.name))
        if payload.get("error"):
            return ChainResult(t, empty, float("nan"), DataStatus(
                Health.ERROR, str(payload["error"])[:160], source=self.name))
        results = payload.get("result") or []
        if not results:
            return ChainResult(t, empty, float("nan"), DataStatus(
                Health.ERROR, f"no listed options for {t}", source=self.name))

        root = results[0]
        spot = _first_finite((root.get("quote") or {}).get("regularMarketPrice"))
        expiries = list(root.get("expirationDates") or [])
        blocks = list(root.get("options") or [])

        for epoch in expiries[1:int(max(1, max_expiries))]:
            try:
                r = self._request(self._OPTIONS.format(sym=t),
                                  {"date": int(epoch)}, need_crumb=True)
                if r.status_code != 200:
                    continue
                more = (((r.json() or {}).get("optionChain") or {}).get("result") or [])
                if more:
                    blocks.extend(more[0].get("options") or [])
            except Exception:
                continue  # one bad expiry must not lose the whole chain

        rows: List[Dict] = []
        for block in blocks:
            exp = block.get("expirationDate")
            for kind in ("calls", "puts"):
                for c in block.get(kind) or []:
                    rows.append({
                        "strike": c.get("strike"),
                        "bid": c.get("bid"), "ask": c.get("ask"),
                        "lastPrice": c.get("lastPrice"),
                        "volume": c.get("volume"),
                        "openInterest": c.get("openInterest"),
                        "impliedVolatility": c.get("impliedVolatility"),
                        "kind": kind[:-1],
                        "expiry": pd.to_datetime(exp, unit="s") if exp else pd.NaT,
                        "inTheMoney": c.get("inTheMoney"),
                    })
        if not rows:
            return ChainResult(t, empty, spot, DataStatus(
                Health.ERROR, "chain returned no contracts", source=self.name))

        now = pd.Timestamp.utcnow().tz_localize(None).normalize()
        df = _tidy_chain(pd.DataFrame(rows), now)
        n_exp = int(df["expiry"].nunique()) if len(df) else 0
        return ChainResult(t, df, spot, DataStatus(
            Health.LIVE, f"{len(df)} contracts / {n_exp} expiries",
            source=self.name))


def _backoff(attempt: int, base: float = 0.6, cap: float = 6.0) -> float:
    """Exponential backoff with jitter, in seconds."""
    return min(cap, base * (2 ** attempt)) * (0.5 + random.random())


def _http_message(resp, ticker: str) -> str:
    """Human-readable explanation of a non-200 response."""
    code = resp.status_code
    if code == 404:
        return f"{ticker} not found (404) -- check the symbol"
    if code == 429:
        return ("Yahoo returned 429 after retries -- genuinely throttled; "
                "try again shortly")
    if code in (401, 403):
        return f"Yahoo refused the request ({code}) -- session token rejected"
    return f"Yahoo HTTP {code}"


def _chart_to_frame(result: Dict) -> pd.DataFrame:
    """Turn one ``/v8/finance/chart`` result block into an OHLCV frame.

    Applies the ``adjclose/close`` ratio to every OHLC column so the bar stays
    internally consistent, and drops rows Yahoo returns as null (holidays and
    halted sessions come back as nulls inside the arrays).
    """
    stamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quotes = (indicators.get("quote") or [{}])[0]
    if not stamps or not quotes:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame({
        "open": quotes.get("open"), "high": quotes.get("high"),
        "low": quotes.get("low"), "close": quotes.get("close"),
        "volume": quotes.get("volume"),
    }, index=pd.to_datetime(stamps, unit="s"))

    adj_block = indicators.get("adjclose") or []
    if adj_block and adj_block[0].get("adjclose"):
        adj = pd.Series(adj_block[0]["adjclose"], index=df.index, dtype="float64")
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = (adj / df["close"]).replace([np.inf, -np.inf], np.nan)
        ratio = ratio.fillna(1.0)
        for col in ("open", "high", "low", "close"):
            df[col] = df[col] * ratio

    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    df.index.name = "date"
    return df[~df.index.duplicated(keep="last")].sort_index()


def _clamp_range(period: str, interval: str) -> str:
    """Clamp the requested range to what Yahoo serves for that interval.

    Intraday history is limited (about 60 days for sub-hourly bars, 2 years for
    hourly).  Asking for more returns an error rather than a truncated series,
    so the request is shortened instead.
    """
    if period not in PERIODS:
        period = "2y"
    limit = _INTRADAY_MAX_DAYS.get(interval)
    if limit is None:
        return period
    wanted = PERIODS.get(period)
    if wanted is None or wanted > limit:
        for candidate in ("1mo", "3mo", "6mo", "1y", "2y"):
            if (PERIODS[candidate] or 10**9) <= limit:
                period = candidate
            else:
                break
    return period


# --------------------------------------------------------------------------
# yfinance (fallback)
# --------------------------------------------------------------------------
class YFinanceProvider(DataProvider):
    """Fallback provider wrapping the ``yfinance`` package.

    Kept as a second opinion: if Yahoo changes its endpoints, the library is
    usually patched before this file is.  It is *not* the default because the
    installed version does not send browser headers, so it draws the spurious
    429s described in the module docstring.  Its session is patched with those
    headers here, which fixes it for most versions.
    """

    name = "yfinance"

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = int(timeout)
        self._yf = None
        self._session = None

    def _lib(self):
        if self._yf is None:
            import requests
            import yfinance as yf
            session = requests.Session()
            session.headers.update(BROWSER_HEADERS)
            self._session = session
            self._yf = yf
        return self._yf

    def _ticker(self, symbol: str):
        yf = self._lib()
        try:
            return yf.Ticker(symbol, session=self._session)
        except TypeError:
            return yf.Ticker(symbol)  # older signatures reject `session`

    def get_history(
        self, ticker: str, period: str = "2y", interval: str = "1d"
    ) -> HistoryResult:
        t = str(ticker).upper().strip()
        empty = pd.DataFrame()
        if not t:
            return HistoryResult(t, interval, empty,
                                 DataStatus(Health.ERROR, "empty ticker"))
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                frame = self._ticker(t).history(
                    period=_clamp_range(period, interval), interval=interval,
                    auto_adjust=True, timeout=self.timeout,
                )
        except Exception as exc:
            return HistoryResult(t, interval, empty, DataStatus(
                Health.ERROR, f"{type(exc).__name__}: {exc}"[:200],
                source=self.name))
        if frame is None or len(frame) == 0:
            return HistoryResult(t, interval, empty, DataStatus(
                Health.ERROR, f"no data returned for {t}", source=self.name))
        return HistoryResult(t, interval, frame, DataStatus(
            Health.LIVE, f"{len(frame)} bars", source=self.name))

    def get_quote(self, ticker: str) -> Quote:
        t = str(ticker).upper().strip()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tk = self._ticker(t)
                info: Dict = {}
                try:
                    info = tk.fast_info or {}
                except Exception:
                    info = {}
                price = _first_finite(info.get("last_price"),
                                      info.get("lastPrice"),
                                      info.get("regularMarketPrice"))
                prev = _first_finite(info.get("previous_close"),
                                     info.get("previousClose"),
                                     info.get("regularMarketPreviousClose"))
                if not np.isfinite(price):
                    hist = tk.history(period="5d", interval="1d",
                                      auto_adjust=True, timeout=self.timeout)
                    if hist is not None and len(hist):
                        closes = hist["Close"].to_numpy(dtype=float)
                        price = float(closes[-1])
                        prev = float(closes[-2]) if closes.size > 1 else price
        except Exception as exc:
            return Quote(t, status=DataStatus(
                Health.ERROR, f"{type(exc).__name__}: {exc}"[:200],
                source=self.name))
        if not np.isfinite(price):
            return Quote(t, status=DataStatus(
                Health.ERROR, f"no quote for {t}", source=self.name))
        return Quote(ticker=t, price=float(price),
                     prev_close=float(prev) if np.isfinite(prev) else float(price),
                     status=DataStatus(Health.LIVE, "quote ok", source=self.name))

    def get_option_chain(self, ticker: str, max_expiries: int = 8) -> ChainResult:
        t = str(ticker).upper().strip()
        empty = pd.DataFrame()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tk = self._ticker(t)
                expiries = list(tk.options or [])[: int(max_expiries)]
                if not expiries:
                    return ChainResult(t, empty, float("nan"), DataStatus(
                        Health.ERROR, f"no listed options for {t}",
                        source=self.name))
                spot = float("nan")
                try:
                    spot = float(tk.fast_info.get("last_price", float("nan")))
                except Exception:
                    pass
                now = pd.Timestamp.utcnow().tz_localize(None).normalize()
                parts: List[pd.DataFrame] = []
                for exp in expiries:
                    try:
                        oc = tk.option_chain(exp)
                    except Exception:
                        continue
                    for kind, side in (("call", oc.calls), ("put", oc.puts)):
                        if side is None or len(side) == 0:
                            continue
                        d = side.copy()
                        d["kind"] = kind
                        d["expiry"] = pd.Timestamp(exp)
                        parts.append(d)
                if not parts:
                    return ChainResult(t, empty, spot, DataStatus(
                        Health.ERROR, "chain fetch returned nothing",
                        source=self.name))
                df = pd.concat(parts, ignore_index=True)
        except Exception as exc:
            return ChainResult(t, empty, float("nan"), DataStatus(
                Health.ERROR, f"{type(exc).__name__}: {exc}"[:200],
                source=self.name))
        df = _tidy_chain(df, now)
        return ChainResult(t, df, spot, DataStatus(
            Health.LIVE, f"{len(df)} contracts / {len(expiries)} expiries",
            source=self.name))


# --------------------------------------------------------------------------
# provider chain
# --------------------------------------------------------------------------
class ChainedProvider(DataProvider):
    """Tries several real providers in order and returns the first success.

    Real market data is worth a second attempt from a different route before
    the app degrades to cache or fixtures, so the default stack is
    ``YahooProvider`` then ``YFinanceProvider``.  The failure messages of every
    provider are concatenated, so the banner explains what each one said rather
    than only reporting the last.
    """

    name = "chained"

    def __init__(self, providers: Sequence[DataProvider]) -> None:
        self.providers: List[DataProvider] = [p for p in providers if p is not None]
        self.name = "+".join(p.name for p in self.providers) or "chained"

    def get_history(self, ticker: str, period: str = "2y",
                    interval: str = "1d") -> HistoryResult:
        notes: List[str] = []
        for provider in self.providers:
            res = provider.get_history(ticker, period, interval)
            if not res.empty:
                return res
            notes.append(f"{provider.name}: {res.status.message}")
        return HistoryResult(str(ticker).upper(), interval, pd.DataFrame(),
                             DataStatus(Health.ERROR, "; ".join(notes) or "no providers",
                                        source=self.name))

    def get_quote(self, ticker: str) -> Quote:
        notes: List[str] = []
        for provider in self.providers:
            q = provider.get_quote(ticker)
            if q.status.ok and np.isfinite(q.price):
                return q
            notes.append(f"{provider.name}: {q.status.message}")
        return Quote(str(ticker).upper(),
                     status=DataStatus(Health.ERROR, "; ".join(notes),
                                       source=self.name))

    def get_option_chain(self, ticker: str, max_expiries: int = 8) -> ChainResult:
        notes: List[str] = []
        for provider in self.providers:
            res = provider.get_option_chain(ticker, max_expiries)
            if res.status.ok and len(res.frame):
                return res
            notes.append(f"{provider.name}: {res.status.message}")
        return ChainResult(str(ticker).upper(), pd.DataFrame(), float("nan"),
                           DataStatus(Health.ERROR, "; ".join(notes),
                                      source=self.name))


def default_provider(timeout: int = 20) -> DataProvider:
    """The stack the app uses: direct Yahoo first, ``yfinance`` as backup."""
    providers: List[DataProvider] = [YahooProvider(timeout=timeout)]
    try:
        import yfinance  # noqa: F401
        providers.append(YFinanceProvider(timeout=timeout))
    except Exception:
        pass
    return ChainedProvider(providers)


# --------------------------------------------------------------------------
# synthetic (offline fixtures)
# --------------------------------------------------------------------------
class SyntheticProvider(DataProvider):
    """Deterministic offline generator, used by ``--selftest`` and demos.

    Produces a Merton-style jump diffusion with a slow volatility cycle, seeded
    from a stable digest of the ticker so the same symbol always yields the
    same series.  That determinism is what makes it usable in the self-test.

    **This is a fixture, not market data.**  It is never used silently: the app
    only falls back to it when explicitly allowed, and every surface that shows
    it is labelled ``SYNTHETIC`` with a red banner.  No conclusion about a real
    ticker follows from it.
    """

    name = "synthetic"

    def __init__(self, n_bars: int = 1260, base_price: float = 100.0) -> None:
        self.n_bars = int(n_bars)
        self.base_price = float(base_price)

    def _rng(self, ticker: str) -> np.random.Generator:
        """Deterministic per-ticker RNG.

        Uses a stable digest rather than the builtin ``hash()``: string hashing
        is salted per interpreter process (PYTHONHASHSEED), so ``hash()`` would
        silently give a different series on every launch and break both the
        offline-reproducibility promise and the self-test assertions.
        """
        digest = hashlib.blake2b(
            f"quantmc:{str(ticker).upper()}".encode("utf-8"), digest_size=8
        ).digest()
        return np.random.default_rng(int.from_bytes(digest, "big") % (2**32))

    def _series(self, ticker: str, n: int) -> pd.DataFrame:
        rng = self._rng(ticker)
        t = np.arange(n)
        vol = 0.011 * (1.0 + 0.45 * np.sin(2 * np.pi * t / 260.0))
        shocks = rng.standard_normal(n) * vol
        jumps = rng.poisson(0.02, n) * rng.normal(-0.03, 0.05, n)
        r = 0.00035 + shocks + jumps
        close = self.base_price * np.exp(np.cumsum(r))
        intraday = np.abs(rng.normal(0, 0.006, n)) + 0.002
        high = close * np.exp(intraday)
        low = close * np.exp(-intraday)
        open_ = close * np.exp(rng.normal(0, 0.004, n))
        volume = rng.lognormal(15.0, 0.4, n)
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
        return pd.DataFrame(
            {"open": open_, "high": np.maximum(high, np.maximum(open_, close)),
             "low": np.minimum(low, np.minimum(open_, close)),
             "close": close, "volume": volume},
            index=idx,
        )

    def get_history(
        self, ticker: str, period: str = "2y", interval: str = "1d"
    ) -> HistoryResult:
        days = PERIODS.get(period) or self.n_bars
        n = int(min(self.n_bars, max(60, days * 252 // 365)))
        frame = self._series(ticker, n)
        return HistoryResult(
            str(ticker).upper(), interval, frame,
            DataStatus(Health.SYNTHETIC, f"SYNTHETIC fixture, {n} bars -- not "
                                         f"market data", source=self.name),
        )

    def get_quote(self, ticker: str) -> Quote:
        frame = self._series(ticker, 20)
        closes = frame["close"].to_numpy(dtype=float)
        return Quote(
            ticker=str(ticker).upper(), price=float(closes[-1]),
            prev_close=float(closes[-2]),
            status=DataStatus(Health.SYNTHETIC, "SYNTHETIC quote",
                              source=self.name),
        )

    def get_option_chain(self, ticker: str, max_expiries: int = 8) -> ChainResult:
        """Synthesise a chain with a realistic downward-sloping smirk.

        Implied vol is built as ``base + skew*(1 - m) + smile*(1 - m)^2`` in
        moneyness ``m = K/S``, then options are priced with Black-Scholes at
        that vol.  Round-tripping those prices back through the implied-vol
        solver must recover the input surface, which the self-test asserts.
        """
        from ..models.pricing import bsm_price

        quote = self.get_quote(ticker)
        spot = quote.price
        rng = self._rng(ticker)
        rows = []
        today = pd.Timestamp.today().normalize()
        for days in (7, 30, 60, 90, 180, 365)[: max(1, int(max_expiries))]:
            T = days / 365.0
            base = 0.24 + 0.05 * np.exp(-days / 60.0)
            for m in np.arange(0.70, 1.31, 0.05):
                K = round(spot * m, 2)
                iv = float(np.clip(base + 0.28 * (1.0 - m)
                                   + 0.55 * (1.0 - m) ** 2, 0.06, 2.0))
                for kind in ("call", "put"):
                    px = float(bsm_price(spot, K, T, 0.04, 0.0, iv, kind))
                    spread = max(0.02, 0.02 * px)
                    rows.append({
                        "strike": K, "expiry": today + pd.Timedelta(days=days),
                        "expiry_years": T, "kind": kind,
                        "bid": max(px - spread / 2, 0.01),
                        "ask": px + spread / 2, "mid": px, "lastPrice": px,
                        "volume": float(rng.integers(1, 500)),
                        "openInterest": float(rng.integers(1, 5000)),
                        "impliedVolatility": iv,
                    })
        return ChainResult(
            str(ticker).upper(), pd.DataFrame(rows), spot,
            DataStatus(Health.SYNTHETIC, f"SYNTHETIC chain ({len(rows)} rows)",
                       source=self.name),
        )


# --------------------------------------------------------------------------
# cache-aware facade
# --------------------------------------------------------------------------
class MarketData:
    """Cache-first facade over a :class:`DataProvider`.

    Read policy, in order:

    1. If the cache holds this series and it is younger than ``max_age``,
       serve it (``CACHED``) -- no network call at all.
    2. Otherwise ask the provider.  On success, write through to the cache and
       serve it (``LIVE``).
    3. On provider failure, serve whatever the cache holds, however old
       (``STALE``), with the provider's error text attached.
    4. If the cache is empty too, return ``ERROR`` -- **unless**
       ``fallback_synthetic`` is explicitly enabled, in which case a clearly
       labelled fixture is returned.

    ``fallback_synthetic`` defaults to **False**.  Silently substituting
    generated numbers for a real ticker is worse than an honest error: the
    numbers look plausible, and nothing downstream can tell they are fake.
    """

    def __init__(
        self, provider: Optional[DataProvider] = None,
        cache: Optional[BarCache] = None,
        max_age_seconds: float = 3600.0,
        fallback_synthetic: bool = False,
        offline: bool = False,
    ) -> None:
        self.provider = provider or default_provider()
        self.cache = cache
        self.max_age = float(max_age_seconds)
        self.fallback_synthetic = bool(fallback_synthetic)
        self.offline = bool(offline)
        self._synthetic = SyntheticProvider()

    # -- history ---------------------------------------------------------
    def history(
        self, ticker: str, period: str = "2y", interval: str = "1d",
        force_refresh: bool = False,
    ) -> HistoryResult:
        t = str(ticker).upper().strip()
        if not t:
            return HistoryResult(t, interval, pd.DataFrame(),
                                 DataStatus(Health.ERROR, "no ticker entered"))
        want_bars = _expected_bars(period, interval)

        cached = self._read_cache(t, interval, want_bars)
        if cached is not None and not force_refresh:
            cov = self.cache.coverage(t, interval)
            if self.offline or cov.age_seconds <= self.max_age:
                return HistoryResult(t, interval, cached, DataStatus(
                    Health.CACHED, f"cache: {len(cached)} bars, "
                    f"{_fmt_age(cov.age_seconds)} old",
                    source="cache", age_seconds=cov.age_seconds))

        if not self.offline:
            live = self.provider.get_history(t, period, interval)
            if not live.empty:
                if self.cache is not None:
                    try:
                        self.cache.write_bars(t, interval, live.frame,
                                              source=self.provider.name)
                    except Exception:
                        pass  # a cache write failure must never break a fetch
                frame = self._read_cache(t, interval, want_bars)
                if frame is None or frame.empty:
                    from .cache import _normalise_frame
                    frame = _normalise_frame(live.frame)
                return HistoryResult(t, interval, frame, DataStatus(
                    Health.LIVE, f"{len(frame)} bars from {live.status.source}",
                    source=live.status.source or self.provider.name))
            err = live.status.message
        else:
            err = "offline mode"

        if cached is not None and len(cached):
            cov = self.cache.coverage(t, interval)
            return HistoryResult(t, interval, cached, DataStatus(
                Health.STALE,
                f"live fetch failed ({err}); serving cache "
                f"{_fmt_age(cov.age_seconds)} old",
                source="cache", age_seconds=cov.age_seconds))

        if self.fallback_synthetic:
            syn = self._synthetic.get_history(t, period, interval)
            syn.status.message = (f"NO REAL DATA for {t} ({err}) -- showing a "
                                  f"SYNTHETIC fixture")
            return syn

        return HistoryResult(t, interval, pd.DataFrame(),
                             DataStatus(Health.ERROR, err))

    def _read_cache(
        self, ticker: str, interval: str, limit: Optional[int]
    ) -> Optional[pd.DataFrame]:
        if self.cache is None:
            return None
        try:
            df = self.cache.read_bars(ticker, interval, limit=limit)
        except Exception:
            return None
        return df if len(df) else None

    # -- quote -----------------------------------------------------------
    def quote(self, ticker: str, max_age_seconds: float = 60.0) -> Quote:
        t = str(ticker).upper().strip()
        if self.cache is not None:
            row = self.cache.read_quote(t)
            if row and (time.time() - row["fetched_at"]) <= max_age_seconds:
                age = time.time() - row["fetched_at"]
                return Quote(t, float(row["price"] or np.nan),
                             float(row["prev_close"] or np.nan),
                             str(row["currency"] or "USD"), str(row["name"] or ""),
                             DataStatus(Health.CACHED, f"quote {_fmt_age(age)} old",
                                        source="cache", age_seconds=age))
        if not self.offline:
            q = self.provider.get_quote(t)
            if q.status.ok and self.cache is not None:
                try:
                    self.cache.write_quote(t, q.price, q.prev_close,
                                           q.currency, q.name)
                except Exception:
                    pass
            if q.status.ok:
                return q
        if self.cache is not None:
            row = self.cache.read_quote(t)
            if row:
                age = time.time() - row["fetched_at"]
                return Quote(t, float(row["price"] or np.nan),
                             float(row["prev_close"] or np.nan),
                             str(row["currency"] or "USD"), str(row["name"] or ""),
                             DataStatus(Health.STALE, f"stale quote ({_fmt_age(age)})",
                                        source="cache", age_seconds=age))
        if self.fallback_synthetic:
            return self._synthetic.get_quote(t)
        return Quote(t, status=DataStatus(Health.ERROR, "no quote available"))

    # -- option chain ----------------------------------------------------
    def option_chain(
        self, ticker: str, max_expiries: int = 8,
        max_age_seconds: float = 900.0, force_refresh: bool = False,
    ) -> ChainResult:
        t = str(ticker).upper().strip()
        if self.cache is not None and not force_refresh:
            df, age = self.cache.read_chain(t, max_age_seconds)
            if df is not None and len(df):
                return ChainResult(t, df, float("nan"), DataStatus(
                    Health.CACHED, f"cached chain ({_fmt_age(age)} old)",
                    source="cache", age_seconds=age))
        if not self.offline:
            res = self.provider.get_option_chain(t, max_expiries)
            if res.status.ok and len(res.frame):
                if self.cache is not None:
                    try:
                        self.cache.write_chain(t, res.frame)
                    except Exception:
                        pass
                return res
            err = res.status.message
        else:
            err = "offline mode"
        if self.cache is not None:
            df, age = self.cache.read_chain(t, None)
            if df is not None and len(df):
                return ChainResult(t, df, float("nan"), DataStatus(
                    Health.STALE, f"{err}; stale chain ({_fmt_age(age)})",
                    source="cache", age_seconds=age))
        if self.fallback_synthetic:
            res = self._synthetic.get_option_chain(t, max_expiries)
            res.status.message = f"NO REAL CHAIN ({err}) -- SYNTHETIC fixture"
            return res
        return ChainResult(t, pd.DataFrame(), float("nan"),
                           DataStatus(Health.ERROR, err))

    # -- basket ----------------------------------------------------------
    def basket_history(
        self, tickers: Sequence[str], period: str = "2y", interval: str = "1d"
    ) -> Tuple[pd.DataFrame, Dict[str, DataStatus]]:
        """Close prices for several tickers, aligned on a common index.

        Each symbol goes through the same cache ladder as a single request, so
        a basket with one bad ticker still returns the others.
        """
        closes: Dict[str, pd.Series] = {}
        statuses: Dict[str, DataStatus] = {}
        for tk in tickers:
            res = self.history(tk, period, interval)
            statuses[res.ticker] = res.status
            if not res.empty:
                closes[res.ticker] = res.frame["close"]
        if not closes:
            return pd.DataFrame(), statuses
        return pd.DataFrame(closes).sort_index(), statuses


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _first_finite(*values) -> float:
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if np.isfinite(f) and f > 0:
            return f
    return float("nan")


def _fmt_age(seconds: float) -> str:
    if not np.isfinite(seconds):
        return "unknown age"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds/60:.0f}m"
    if seconds < 172800:
        return f"{seconds/3600:.0f}h"
    return f"{seconds/86400:.0f}d"


def _expected_bars(period: str, interval: str) -> Optional[int]:
    """Roughly how many bars ``period`` at ``interval`` should contain."""
    days = PERIODS.get(period)
    if days is None:
        return None
    per_day = {"1d": 1, "1wk": 1 / 5, "1mo": 1 / 21,
               "1h": 7, "30m": 13, "15m": 26}.get(interval, 1)
    return int(max(30, days * (252 / 365) * per_day)) + 5


def _tidy_chain(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Normalise a raw option chain into the columns the app expects."""
    keep = ["strike", "bid", "ask", "lastPrice", "volume", "openInterest",
            "impliedVolatility", "kind", "expiry"]
    for col in keep:
        if col not in df.columns:
            df[col] = np.nan
    out = df[keep].copy()
    out["strike"] = pd.to_numeric(out["strike"], errors="coerce")
    for col in ("bid", "ask", "lastPrice", "volume", "openInterest",
                "impliedVolatility"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    both_sided = (out["bid"] > 0) & (out["ask"] > 0) & (out["ask"] >= out["bid"])
    out["mid"] = np.where(both_sided, (out["bid"] + out["ask"]) / 2.0,
                          out["lastPrice"])
    exp = pd.to_datetime(out["expiry"], errors="coerce")
    if getattr(exp.dtype, "tz", None) is not None:
        exp = exp.dt.tz_convert("UTC").dt.tz_localize(None)
    out["expiry"] = exp
    out["expiry_years"] = (exp - now).dt.total_seconds() / (365.25 * 24 * 3600)
    out = out[np.isfinite(out["strike"]) & (out["strike"] > 0)]
    out = out[out["expiry_years"] > 1e-4]
    return out.reset_index(drop=True)
