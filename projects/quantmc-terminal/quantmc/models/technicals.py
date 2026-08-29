"""
Technical indicators and the realised-volatility cone.

All functions take and return 1-D numpy arrays aligned with the input series
(leading values are ``nan`` until the indicator has enough history), so they
drop straight onto a price axis without index bookkeeping.

MODELLING TOOL, NOT INVESTMENT ADVICE.  Indicators are descriptive summaries of
past prices; none of them carries predictive content on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

TRADING_DAYS = 252.0

__all__ = [
    "sma", "ema", "bollinger_bands", "rsi", "macd", "atr",
    "true_range", "vol_cone",
]


def _as1d(x: Sequence[float]) -> np.ndarray:
    return np.asarray(x, dtype=float).ravel()


def sma(x: Sequence[float], window: int = 20) -> np.ndarray:
    """Simple moving average over ``window`` observations.

    Computed from a cumulative sum, so it is O(n) rather than O(n*window).
    Equal weight on every observation in the window means an old value leaves
    the average abruptly -- the "ghost feature" that EMA avoids.
    """
    v = _as1d(x)
    w = int(max(1, window))
    out = np.full(v.size, np.nan)
    if v.size < w:
        return out
    c = np.concatenate([[0.0], np.cumsum(v)])
    out[w - 1 :] = (c[w:] - c[:-w]) / w
    return out


def ema(x: Sequence[float], span: int = 20) -> np.ndarray:
    """Exponential moving average with pandas-compatible ``span`` smoothing.

    Math
    ----
    ``alpha = 2 / (span + 1)`` and ``e_t = alpha x_t + (1 - alpha) e_{t-1}``,
    seeded with ``e_0 = x_0``.  Weights decay geometrically, so the average
    responds faster than an SMA of the same nominal length while never fully
    discarding old data.
    """
    v = _as1d(x)
    n = v.size
    out = np.full(n, np.nan)
    if n == 0:
        return out
    alpha = 2.0 / (float(max(1, span)) + 1.0)
    acc = v[0]
    out[0] = acc
    for i in range(1, n):
        acc = alpha * v[i] + (1.0 - alpha) * acc
        out[i] = acc
    return out


def bollinger_bands(
    x: Sequence[float], window: int = 20, n_std: float = 2.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands: an SMA with +/- ``n_std`` rolling standard deviations.

    Returns ``(upper, middle, lower)``.  The band width is a crude realised-vol
    proxy: it widens mechanically after large moves, which is why "the bands
    are tight" is a statement about recent volatility, not about the future.
    """
    v = _as1d(x)
    w = int(max(2, window))
    mid = sma(v, w)
    std = np.full(v.size, np.nan)
    if v.size >= w:
        c1 = np.concatenate([[0.0], np.cumsum(v)])
        c2 = np.concatenate([[0.0], np.cumsum(v * v)])
        s1 = c1[w:] - c1[:-w]
        s2 = c2[w:] - c2[:-w]
        var = np.maximum((s2 - s1 * s1 / w) / (w - 1), 0.0)
        std[w - 1 :] = np.sqrt(var)
    return mid + n_std * std, mid, mid - n_std * std


def rsi(x: Sequence[float], period: int = 14) -> np.ndarray:
    """Wilder's Relative Strength Index.

    Math
    ----
    Split the price changes into gains and losses, smooth each with Wilder's
    recursive average (``avg_t = (avg_{t-1}(p-1) + new) / p``, equivalent to an
    EMA of span ``2p-1``), then

        ``RS = avg_gain / avg_loss``,  ``RSI = 100 - 100 / (1 + RS)``.

    Bounded in [0, 100].  The first ``period`` values are seeded with a simple
    average, matching the standard charting-package convention.  RSI is a
    normalised momentum oscillator, and in a trending market it can sit above
    70 (or below 30) for a long time -- an extreme reading is not a signal.
    """
    v = _as1d(x)
    n = v.size
    out = np.full(n, np.nan)
    p = int(max(2, period))
    if n < p + 1:
        return out
    delta = np.diff(v)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_g = gain[:p].mean()
    avg_l = loss[:p].mean()
    for i in range(p, n):
        if i > p:
            avg_g = (avg_g * (p - 1) + gain[i - 1]) / p
            avg_l = (avg_l * (p - 1) + loss[i - 1]) / p
        if avg_l <= 0:
            out[i] = 100.0
        else:
            rs = avg_g / avg_l
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def macd(
    x: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD line, signal line and histogram.

    Math
    ----
    ``MACD = EMA_fast - EMA_slow``, ``signal = EMA_signal(MACD)``,
    ``hist = MACD - signal``.  The difference of two EMAs is a band-pass filter
    on the price series; the histogram is its rate of change.  Being a
    difference of *unnormalised* prices, MACD levels are not comparable across
    tickers or across large price changes in one ticker.
    """
    v = _as1d(x)
    line = ema(v, fast) - ema(v, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def true_range(
    high: Sequence[float], low: Sequence[float], close: Sequence[float]
) -> np.ndarray:
    """Wilder's true range: ``max(H-L, |H-C_prev|, |L-C_prev|)`` per bar.

    Taking the previous close into account is what makes it *true* range -- it
    counts an overnight gap that a plain high-minus-low would miss entirely.
    """
    h, l, c = _as1d(high), _as1d(low), _as1d(close)
    n = min(h.size, l.size, c.size)
    out = np.full(n, np.nan)
    if n == 0:
        return out
    out[0] = h[0] - l[0]
    prev = c[: n - 1]
    out[1:] = np.maximum.reduce([
        h[1:n] - l[1:n], np.abs(h[1:n] - prev), np.abs(l[1:n] - prev)
    ])
    return out


def atr(
    high: Sequence[float], low: Sequence[float], close: Sequence[float],
    period: int = 14,
) -> np.ndarray:
    """Average True Range, Wilder-smoothed.

    A volatility measure in **price units**, not percent, which is what makes
    it convenient for stop placement and position sizing (risk per unit =
    stop distance in ATRs).  Divide by price to compare across tickers.
    """
    tr = true_range(high, low, close)
    n = tr.size
    out = np.full(n, np.nan)
    p = int(max(2, period))
    if n < p:
        return out
    acc = float(np.nanmean(tr[:p]))
    out[p - 1] = acc
    for i in range(p, n):
        acc = (acc * (p - 1) + tr[i]) / p
        out[i] = acc
    return out


@dataclass
class VolConeRow:
    """One horizon of the realised-volatility cone."""

    window: int
    current: float
    p_min: float
    p10: float
    p25: float
    median: float
    p75: float
    p90: float
    p_max: float
    percentile_rank: float
    """Where today's realised vol sits inside its own historical distribution."""


def vol_cone(
    returns: Sequence[float],
    windows: Sequence[int] = (5, 10, 21, 42, 63, 126, 252),
) -> list:
    """Realised-volatility cone: the distribution of realised vol per horizon.

    Math
    ----
    For each window ``w``, compute the rolling annualised realised volatility
    ``std(r_{t-w+1..t}) sqrt(252)`` over the whole sample and report its
    min/10/25/50/75/90/max percentiles alongside the most recent value.
    Plotted with horizon on the x-axis the percentiles form the characteristic
    cone: short windows have a wide dispersion, long windows a narrow one,
    because averaging more days shrinks the sampling error of the estimate.

    The cone is the standard reference for "is implied vol cheap?": compare the
    option's implied vol at a given tenor against the realised cone at the
    matching horizon.  Note the rolling windows overlap heavily, so the
    percentiles are *not* independent observations and the tails of the cone
    are less informative than the sample size suggests.
    """
    from .stats import rolling_realized_vol  # local import avoids a cycle

    r = _as1d(returns)
    rows = []
    for w in windows:
        w = int(w)
        if r.size < w + 5:
            continue
        series = rolling_realized_vol(r, w)
        finite = series[np.isfinite(series)]
        if finite.size < 5:
            continue
        cur = float(finite[-1])
        rows.append(
            VolConeRow(
                window=w, current=cur,
                p_min=float(finite.min()),
                p10=float(np.percentile(finite, 10)),
                p25=float(np.percentile(finite, 25)),
                median=float(np.percentile(finite, 50)),
                p75=float(np.percentile(finite, 75)),
                p90=float(np.percentile(finite, 90)),
                p_max=float(finite.max()),
                percentile_rank=float((finite <= cur).mean() * 100.0),
            )
        )
    return rows
