"""
Local SQLite cache for price bars, quotes and option chains.

The cache is what makes the terminal usable offline and immune to provider rate
limits: every download is written here keyed by ``(ticker, interval, timestamp)``
and every read prefers local data.  SQLite is used rather than parquet files
because bar-level upserts are the dominant write pattern (re-fetching an
overlapping window must not duplicate rows), and ``INSERT OR REPLACE`` on a
composite primary key handles that in one statement.

The database lives in the user's app data directory by default (see
:mod:`quantmc.config`) and is safe to delete at any time.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = ["Coverage", "BarCache"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    ticker    TEXT    NOT NULL,
    interval  TEXT    NOT NULL,
    ts        INTEGER NOT NULL,
    open      REAL,
    high      REAL,
    low       REAL,
    close     REAL,
    volume    REAL,
    PRIMARY KEY (ticker, interval, ts)
);
CREATE INDEX IF NOT EXISTS ix_bars_lookup ON bars (ticker, interval, ts);

CREATE TABLE IF NOT EXISTS meta (
    ticker     TEXT NOT NULL,
    interval   TEXT NOT NULL,
    fetched_at INTEGER,
    source     TEXT,
    PRIMARY KEY (ticker, interval)
);

CREATE TABLE IF NOT EXISTS chains (
    ticker     TEXT PRIMARY KEY,
    fetched_at INTEGER,
    payload    TEXT
);

CREATE TABLE IF NOT EXISTS quotes (
    ticker     TEXT PRIMARY KEY,
    fetched_at INTEGER,
    price      REAL,
    prev_close REAL,
    currency   TEXT,
    name       TEXT
);
"""

_BAR_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass
class Coverage:
    """What the cache holds for one ``(ticker, interval)`` pair."""

    ticker: str
    interval: str
    rows: int
    first: Optional[pd.Timestamp]
    last: Optional[pd.Timestamp]
    fetched_at: Optional[float]
    source: str = ""

    @property
    def age_seconds(self) -> float:
        """Seconds since this series was last refreshed from a provider."""
        if not self.fetched_at:
            return float("inf")
        return max(0.0, time.time() - float(self.fetched_at))


class BarCache:
    """Thread-safe SQLite store for OHLCV bars, quotes and option chains.

    One connection is shared behind a lock rather than opened per call: the GUI
    thread and the simulation worker both touch the cache, and SQLite
    connections are not safe to share across threads without either a lock or
    ``check_same_thread=False`` plus serialisation.  Both are used here.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # -- lifecycle -------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "BarCache":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- bars ------------------------------------------------------------
    def write_bars(
        self, ticker: str, interval: str, frame: pd.DataFrame,
        source: str = "",
    ) -> int:
        """Upsert an OHLCV frame.  Returns the number of rows written.

        ``frame`` must be indexed by timestamp and carry (case-insensitively)
        Open/High/Low/Close/Volume columns.  Rows whose close is missing or
        non-positive are dropped -- they are always feed artefacts, and letting
        one through would produce ``inf`` in the log-return series.
        """
        df = _normalise_frame(frame)
        if df.empty:
            return 0
        ticker = ticker.upper().strip()
        rows = [
            (ticker, interval, int(ts.value // 10**9),
             _f(r.open), _f(r.high), _f(r.low), _f(r.close), _f(r.volume))
            for ts, r in df.iterrows()
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO bars "
                "(ticker, interval, ts, open, high, low, close, volume) "
                "VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (ticker, interval, fetched_at, source) "
                "VALUES (?,?,?,?)",
                (ticker, interval, int(time.time()), source),
            )
            self._conn.commit()
        return len(rows)

    def read_bars(
        self, ticker: str, interval: str,
        start: Optional[pd.Timestamp] = None,
        end: Optional[pd.Timestamp] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """Read cached bars as a timestamp-indexed OHLCV frame (may be empty)."""
        ticker = ticker.upper().strip()
        sql = ("SELECT ts, open, high, low, close, volume FROM bars "
               "WHERE ticker = ? AND interval = ?")
        args: List[object] = [ticker, interval]
        if start is not None:
            sql += " AND ts >= ?"
            args.append(int(pd.Timestamp(start).value // 10**9))
        if end is not None:
            sql += " AND ts <= ?"
            args.append(int(pd.Timestamp(end).value // 10**9))
        # With a limit we want the *most recent* N bars, so sort descending in
        # SQL and flip back to chronological order in pandas.
        if limit:
            sql += f" ORDER BY ts DESC LIMIT {int(limit)}"
        else:
            sql += " ORDER BY ts ASC"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        if not rows:
            return pd.DataFrame(columns=list(_BAR_COLUMNS))
        if limit:
            rows = rows[::-1]
        df = pd.DataFrame(rows, columns=["ts", *_BAR_COLUMNS])
        df.index = pd.to_datetime(df.pop("ts"), unit="s")
        df.index.name = "date"
        return df

    def coverage(self, ticker: str, interval: str) -> Coverage:
        """Row count, date span and last refresh time for one series."""
        ticker = ticker.upper().strip()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), MIN(ts), MAX(ts) FROM bars "
                "WHERE ticker = ? AND interval = ?", (ticker, interval)
            ).fetchone()
            meta = self._conn.execute(
                "SELECT fetched_at, source FROM meta WHERE ticker = ? AND interval = ?",
                (ticker, interval),
            ).fetchone()
        count = int(row[0]) if row else 0
        first = pd.to_datetime(row[1], unit="s") if row and row[1] else None
        last = pd.to_datetime(row[2], unit="s") if row and row[2] else None
        return Coverage(
            ticker=ticker, interval=interval, rows=count, first=first, last=last,
            fetched_at=float(meta[0]) if meta and meta[0] else None,
            source=str(meta[1]) if meta and meta[1] else "",
        )

    def list_cached(self) -> List[Coverage]:
        """Every ``(ticker, interval)`` series present in the cache."""
        with self._lock:
            keys = self._conn.execute(
                "SELECT DISTINCT ticker, interval FROM bars ORDER BY ticker"
            ).fetchall()
        return [self.coverage(t, i) for t, i in keys]

    # -- quotes ----------------------------------------------------------
    def write_quote(
        self, ticker: str, price: float, prev_close: float,
        currency: str = "USD", name: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO quotes "
                "(ticker, fetched_at, price, prev_close, currency, name) "
                "VALUES (?,?,?,?,?,?)",
                (ticker.upper().strip(), int(time.time()), _f(price),
                 _f(prev_close), currency, name),
            )
            self._conn.commit()

    def read_quote(self, ticker: str) -> Optional[Dict[str, object]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT fetched_at, price, prev_close, currency, name "
                "FROM quotes WHERE ticker = ?", (ticker.upper().strip(),)
            ).fetchone()
        if not row:
            return None
        return {"fetched_at": float(row[0]), "price": row[1],
                "prev_close": row[2], "currency": row[3], "name": row[4]}

    # -- option chains ---------------------------------------------------
    def write_chain(self, ticker: str, frame: pd.DataFrame) -> None:
        """Store an option chain as a JSON blob keyed by ticker.

        Chains are stored whole rather than row-per-contract: they are read
        whole, they change shape between expiries, and a chain is small enough
        (a few hundred KB of JSON) that normalising it would buy nothing.
        """
        payload = frame.to_json(orient="split", date_format="iso") if frame is not None else "{}"
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO chains (ticker, fetched_at, payload) VALUES (?,?,?)",
                (ticker.upper().strip(), int(time.time()), payload),
            )
            self._conn.commit()

    def read_chain(
        self, ticker: str, max_age_seconds: Optional[float] = None
    ) -> Tuple[Optional[pd.DataFrame], float]:
        """Read a cached chain.  Returns ``(frame_or_None, age_seconds)``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT fetched_at, payload FROM chains WHERE ticker = ?",
                (ticker.upper().strip(),),
            ).fetchone()
        if not row:
            return None, float("inf")
        age = max(0.0, time.time() - float(row[0]))
        if max_age_seconds is not None and age > max_age_seconds:
            return None, age
        try:
            import io
            df = pd.read_json(io.StringIO(row[1]), orient="split")
            return df, age
        except Exception:
            return None, age

    # -- maintenance -----------------------------------------------------
    def clear(self, ticker: Optional[str] = None) -> None:
        """Delete one ticker's cached data, or everything when ``ticker`` is None."""
        with self._lock:
            if ticker:
                t = ticker.upper().strip()
                for table in ("bars", "meta", "chains", "quotes"):
                    self._conn.execute(f"DELETE FROM {table} WHERE ticker = ?", (t,))
            else:
                for table in ("bars", "meta", "chains", "quotes"):
                    self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()

    def size_bytes(self) -> int:
        try:
            return os.path.getsize(self.db_path)
        except OSError:
            return 0


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _f(value) -> Optional[float]:
    """Coerce to a finite float or ``None`` (SQLite NULL)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Lower-case the OHLCV columns, coerce the index to UTC-naive timestamps.

    yfinance returns capitalised columns, sometimes a MultiIndex (when several
    tickers are requested) and a timezone-aware index.  Everything downstream
    assumes lower-case columns and a naive index, so the normalisation happens
    once, here, at the cache boundary.
    """
    if frame is None or len(frame) == 0:
        return pd.DataFrame(columns=list(_BAR_COLUMNS))
    df = frame.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]) for c in df.columns]
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    if "adj_close" in df.columns and "close" not in df.columns:
        df["close"] = df["adj_close"]
    for col in _BAR_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[list(_BAR_COLUMNS)]
    try:
        idx = pd.to_datetime(df.index, utc=True).tz_localize(None)
    except (TypeError, ValueError):
        idx = pd.to_datetime(df.index, errors="coerce")
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
    df.index = idx
    df = df[~df.index.isna()]
    df = df[np.isfinite(df["close"].astype(float)) & (df["close"].astype(float) > 0)]
    return df[~df.index.duplicated(keep="last")].sort_index()
