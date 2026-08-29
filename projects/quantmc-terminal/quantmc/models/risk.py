"""
Risk statistics computed from simulated price paths.

Everything here takes plain numpy arrays and returns plain numbers or dicts, so
the whole module is importable and testable without a GUI.  Two shapes recur:

* ``paths``    : ``(n_paths, n_steps + 1)`` price matrix, column 0 = spot.
* ``terminal`` : ``(n_paths,)`` vector of terminal prices.

Sign convention: VaR and CVaR are reported as **positive loss numbers** (a 95%
VaR of 0.18 means "a 5%-probability loss of 18% or worse"), which is the desk
convention.  Drawdowns are reported as **negative fractions** (-0.32 = -32%).

MODELLING TOOL, NOT INVESTMENT ADVICE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
from scipy import stats as sps

TRADING_DAYS = 252.0

DEFAULT_PERCENTILES: Tuple[float, ...] = (1, 5, 10, 25, 50, 75, 90, 95, 99)
DEFAULT_BANDS: Tuple[float, ...] = (5, 25, 50, 75, 95)
DEFAULT_VAR_LEVELS: Tuple[float, ...] = (0.90, 0.95, 0.99)

__all__ = [
    "PathBatchStats",
    "batch_stats",
    "max_drawdown_paths",
    "percentile_bands",
    "var_cvar",
    "sharpe_sortino",
    "probability_above",
    "probability_touch",
    "convergence_curve",
    "kelly_fraction",
    "terminal_summary",
]


# --------------------------------------------------------------------------
# per-batch reduction
# --------------------------------------------------------------------------
@dataclass
class PathBatchStats:
    """Per-path scalars extracted from one batch of simulated paths.

    Reducing each batch to four ``(n_paths,)`` vectors is what lets the engine
    run an unbounded number of paths in bounded memory: the full
    ``(n_paths, n_steps+1)`` matrix is discarded after this reduction, and only
    a small reservoir of whole paths is retained for the fan chart.
    """

    terminal: np.ndarray
    """Terminal price of each path."""
    path_max: np.ndarray
    """Running maximum over the whole path (used for up-barrier touches)."""
    path_min: np.ndarray
    """Running minimum over the whole path (down-barriers, ruin)."""
    max_drawdown: np.ndarray
    """Worst peak-to-trough move per path, as a negative fraction."""

    def __len__(self) -> int:
        return int(self.terminal.size)


def max_drawdown_paths(paths: np.ndarray) -> np.ndarray:
    """Worst peak-to-trough decline of each path, as a negative fraction.

    Math
    ----
    ``MDD_i = min_t ( S_{i,t} / max_{u<=t} S_{i,u} - 1 )``.  The running peak is
    computed with ``np.maximum.accumulate`` along the time axis, so the whole
    thing is one vectorised pass with no Python loop over paths.

    Assumptions
    -----------
    Drawdown is measured on the simulated step grid only.  Intra-step extremes
    are invisible, so a daily grid understates the true continuous-time
    drawdown (the same discrete-monitoring bias that affects barrier options).
    """
    peaks = np.maximum.accumulate(paths, axis=1)
    return (paths / peaks - 1.0).min(axis=1)


def batch_stats(paths: np.ndarray) -> PathBatchStats:
    """Reduce a batch of paths to the per-path scalars the engine accumulates."""
    return PathBatchStats(
        terminal=paths[:, -1].copy(),
        path_max=paths.max(axis=1),
        path_min=paths.min(axis=1),
        max_drawdown=max_drawdown_paths(paths),
    )


def percentile_bands(
    paths: np.ndarray, bands: Sequence[float] = DEFAULT_BANDS
) -> Dict[float, np.ndarray]:
    """Cross-sectional percentiles of the price at every time step.

    Returns ``{percentile: (n_steps + 1,) array}`` -- the shaded ribbons of the
    fan chart.  Note these are *pointwise* quantiles: the 95th-percentile curve
    is not the path of any single simulation, and the region between the 5th
    and 95th curves is not a 90% confidence band for whole paths (the
    probability that a path stays inside it for the entire horizon is far
    lower than 90%).
    """
    qs = np.asarray(bands, dtype=float)
    out = np.percentile(paths, qs, axis=0)
    return {float(q): out[i] for i, q in enumerate(qs)}


# --------------------------------------------------------------------------
# tail risk
# --------------------------------------------------------------------------
def var_cvar(
    terminal: np.ndarray,
    s0: float,
    levels: Sequence[float] = DEFAULT_VAR_LEVELS,
) -> Dict[float, Tuple[float, float]]:
    """Historical-simulation VaR and CVaR of the horizon return.

    Math
    ----
    With ``R_i = S_T,i / S_0 - 1`` the horizon simple return and confidence
    ``c``, ``VaR_c = -Quantile_{1-c}(R)`` and
    ``CVaR_c = -E[R | R <= Quantile_{1-c}(R)]`` (also called expected
    shortfall).  Both are returned as positive fractions of notional.

    This is the empirical quantile of the *simulated* distribution -- no
    normality assumption is made -- but it inherits every assumption of the
    path model that generated it, and the accuracy of the 99% number is
    governed by how many paths land in the worst 1%.

    Returns ``{level: (var, cvar)}``.
    """
    r = np.asarray(terminal, dtype=float) / float(s0) - 1.0
    r = r[np.isfinite(r)]
    out: Dict[float, Tuple[float, float]] = {}
    if r.size == 0:
        return {float(c): (float("nan"), float("nan")) for c in levels}
    for c in levels:
        q = float(np.quantile(r, 1.0 - c))
        tail = r[r <= q]
        cvar = float(tail.mean()) if tail.size else q
        out[float(c)] = (-q, -cvar)
    return out


def sharpe_sortino(
    terminal: np.ndarray,
    s0: float,
    horizon_years: float,
    rf: float = 0.0,
) -> Tuple[float, float]:
    """Annualised Sharpe and Sortino ratios across the simulated paths.

    Math
    ----
    Using per-path log growth ``g_i = log(S_T,i / S_0)`` over ``T`` years, the
    annualised mean is ``mean(g)/T`` and the annualised volatility is
    ``std(g)/sqrt(T)`` (variance of a random walk scales with time).  Then

        ``Sharpe  = (mean_ann - rf) / vol_ann``
        ``Sortino = (mean_ann - rf) / downside_dev_ann``

    where the downside deviation uses only paths with ``g_i < rf * T``,
    i.e. only shortfalls against the risk-free hurdle are penalised.

    Note this is a *cross-sectional* ratio over terminal outcomes, not a
    time-series ratio of periodic returns; the two coincide only for iid
    returns.  Sortino is ``+inf`` when no path underperforms the hurdle.
    """
    g = np.log(np.asarray(terminal, dtype=float) / float(s0))
    g = g[np.isfinite(g)]
    T = max(float(horizon_years), 1e-9)
    if g.size < 2:
        return float("nan"), float("nan")
    mean_ann = float(g.mean()) / T
    vol_ann = float(g.std(ddof=1)) / np.sqrt(T)
    sharpe = (mean_ann - rf) / vol_ann if vol_ann > 0 else float("nan")
    downside = g[g < rf * T] - rf * T
    if downside.size == 0:
        sortino = float("inf")
    else:
        dd = float(np.sqrt((downside**2).mean())) / np.sqrt(T)
        sortino = (mean_ann - rf) / dd if dd > 0 else float("nan")
    return sharpe, sortino


def probability_above(terminal: np.ndarray, target: float) -> float:
    """P(S_T > target): the simple frequency of paths finishing above target."""
    t = np.asarray(terminal, dtype=float)
    t = t[np.isfinite(t)]
    return float((t > float(target)).mean()) if t.size else float("nan")


def probability_touch(
    path_max: np.ndarray,
    path_min: np.ndarray,
    barrier: float,
    direction: str = "up",
) -> float:
    """P(the path touches ``barrier`` at any monitored step).

    ``direction='up'`` uses the running maximum, ``'down'`` the running
    minimum.  This is a *discretely monitored* probability: a path that crosses
    the barrier between two step dates and comes back is not counted, so the
    result is biased low relative to continuous monitoring.  The bias shrinks
    like ``O(sqrt(dt))`` -- meaningful for weekly steps, small for daily.
    """
    if direction == "up":
        arr = np.asarray(path_max, dtype=float)
        hit = arr >= float(barrier)
    else:
        arr = np.asarray(path_min, dtype=float)
        hit = arr <= float(barrier)
    return float(hit.mean()) if arr.size else float("nan")


def probability_of_ruin(path_min: np.ndarray, ruin_level: float) -> float:
    """P(the path ever trades at or below ``ruin_level``) on the step grid."""
    return probability_touch(path_min, path_min, ruin_level, direction="down")


# --------------------------------------------------------------------------
# convergence diagnostics
# --------------------------------------------------------------------------
def convergence_curve(
    terminal: np.ndarray, n_points: int = 120
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Running mean and standard error of the terminal price vs path count.

    Math
    ----
    At ``n`` paths the estimator is ``xbar_n = (1/n) sum x_i`` with standard
    error ``s_n / sqrt(n)``.  Because paths are iid, the SE decays like
    ``1/sqrt(n)``: quartering the error costs sixteen times the paths.  When
    the running mean has settled inside its own +/-2 SE envelope and the
    envelope is narrow relative to the quantity of interest, the simulation has
    converged *for the mean* -- tail quantiles converge much more slowly.

    Returns ``(counts, running_mean, standard_error)`` sampled at ``n_points``
    log-spaced path counts.
    """
    x = np.asarray(terminal, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return np.array([]), np.array([]), np.array([])
    counts = np.unique(
        np.geomspace(max(2, n // 500), n, num=min(n_points, n)).astype(int)
    )
    csum = np.cumsum(x)
    csum2 = np.cumsum(x * x)
    idx = counts - 1
    means = csum[idx] / counts
    # population -> sample variance correction
    var = np.maximum(csum2[idx] / counts - means**2, 0.0) * counts / np.maximum(counts - 1, 1)
    se = np.sqrt(var / counts)
    return counts, means, se


# --------------------------------------------------------------------------
# position sizing
# --------------------------------------------------------------------------
def kelly_fraction(
    terminal: np.ndarray,
    s0: float,
    horizon_years: float,
    rf: float = 0.0,
    f_max: float = 5.0,
) -> Dict[str, float]:
    """Kelly position size implied by the simulated return distribution.

    Math
    ----
    Two estimates are returned.

    *Continuous / Gaussian approximation*: for a lognormal wealth process the
    growth-optimal leverage is ``f* = (mu - rf) / sigma^2`` where ``mu`` and
    ``sigma`` are the annualised arithmetic drift and volatility.  Fast, but it
    assumes the return is Gaussian and so ignores the fat left tail that
    matters most for sizing.

    *Empirical (exact for the simulated sample)*: maximise expected log growth
    of the levered portfolio over ``f`` on a dense grid,

        ``W(f) = (1 + rf_T) + f (R - rf_T)``,  ``rf_T = e^{rf T} - 1``

    i.e. fraction ``f`` in the asset and ``1 - f`` earning the risk-free rate
    over the horizon (``f > 1`` is borrowing at ``rf``).  This uses the actual
    simulated distribution -- jumps, skew, fat tails and all.  ``f`` is capped
    at ``min(f_max, 1/max_loss)`` because leverage beyond ``1/max_loss``
    guarantees ruin on the worst simulated path.

    **The two numbers are not meant to be equal, and the gap is informative.**
    The Gaussian formula is the *continuous-rebalancing* limit; the empirical
    one is the optimum for holding the position over this horizon without
    rebalancing.  They agree closely at short horizons and diverge as the
    horizon lengthens, because a buy-and-hold position accumulates the full
    compounding drag of its own variance.  For a 12%-drift, 20%-vol asset at
    ``rf = 2%``: both give ~2.5 at a one-week horizon, but the one-year hold
    optimum is ~1.8.  If the empirical number sits far *below* the Gaussian
    one, the horizon is long or the left tail is fat -- either way, size to
    the empirical figure.

    Also returns half-Kelly and quarter-Kelly, which is what most practitioners
    actually size to: full Kelly maximises long-run growth but has brutal
    drawdowns (an expected worst drawdown near 50%) and is extremely sensitive
    to estimation error in ``mu``, which is the least well-estimated input in
    the whole model.

    Assumptions
    -----------
    One repeated bet with the same distribution each period, full
    reinvestment, unlimited borrowing at ``rf``, no transaction costs, and --
    most importantly -- that the simulated distribution is the true one.
    """
    r = np.asarray(terminal, dtype=float) / float(s0) - 1.0
    r = r[np.isfinite(r)]
    T = max(float(horizon_years), 1e-9)
    out = {
        "kelly_gaussian": float("nan"),
        "kelly_empirical": float("nan"),
        "half_kelly": float("nan"),
        "quarter_kelly": float("nan"),
        "growth_rate": float("nan"),
    }
    if r.size < 2:
        return out

    g = np.log1p(r)
    mu_ann = float(g.mean()) / T + 0.5 * (float(g.std(ddof=1)) ** 2) / T
    var_ann = (float(g.std(ddof=1)) ** 2) / T
    if var_ann > 0:
        out["kelly_gaussian"] = (mu_ann - rf) / var_ann

    rf_t = float(np.expm1(rf * T))
    excess = r - rf_t
    worst = float(excess.min())
    cap = f_max if worst >= 0 else min(f_max, (1.0 + rf_t) * 0.999 / abs(worst))
    if cap <= 0:
        return out

    grid = np.linspace(0.0, cap, 800)
    with np.errstate(divide="ignore", invalid="ignore"):
        wealth = (1.0 + rf_t) + np.outer(grid, excess)
        logs = np.where(wealth > 1e-12, np.log(np.maximum(wealth, 1e-12)), -1e9)
        growth = logs.mean(axis=1)
    best = int(np.argmax(growth))
    out["kelly_empirical"] = float(grid[best])
    out["half_kelly"] = float(grid[best]) * 0.5
    out["quarter_kelly"] = float(grid[best]) * 0.25
    out["growth_rate"] = float(growth[best]) / T
    return out


# --------------------------------------------------------------------------
# headline summary
# --------------------------------------------------------------------------
def terminal_summary(
    terminal: np.ndarray,
    s0: float,
    percentiles: Sequence[float] = DEFAULT_PERCENTILES,
) -> Dict[str, float]:
    """Moments and the percentile ladder of the terminal-price distribution.

    Skew and kurtosis are the Fisher (excess) definitions, so a normal
    distribution scores 0 for both.  ``prob_up`` is the fraction of paths
    finishing above spot.
    """
    t = np.asarray(terminal, dtype=float)
    t = t[np.isfinite(t)]
    if t.size == 0:
        return {}
    out: Dict[str, float] = {
        "n_paths": float(t.size),
        "mean": float(t.mean()),
        "median": float(np.median(t)),
        "std": float(t.std(ddof=1)) if t.size > 1 else 0.0,
        "skew": float(sps.skew(t)),
        "kurtosis": float(sps.kurtosis(t)),
        "min": float(t.min()),
        "max": float(t.max()),
        "prob_up": float((t > float(s0)).mean()),
        "mean_return": float(t.mean() / float(s0) - 1.0),
        "median_return": float(np.median(t) / float(s0) - 1.0),
        "stderr": float(t.std(ddof=1) / np.sqrt(t.size)) if t.size > 1 else 0.0,
    }
    for p in percentiles:
        out[f"p{p:g}"] = float(np.percentile(t, p))
    return out
