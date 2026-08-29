"""
Multi-asset correlation analysis and correlated Monte Carlo.

Covers the basket workflow: align several price series, estimate the
correlation/covariance structure, repair it if the estimate is not positive
semi-definite, and simulate a correlated basket with a Cholesky factor.

MODELLING TOOL, NOT INVESTMENT ADVICE.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

TRADING_DAYS = 252.0
DEFAULT_DT = 1.0 / TRADING_DAYS

__all__ = [
    "align_returns",
    "correlation_matrix",
    "covariance_matrix",
    "nearest_psd",
    "cholesky_factor",
    "BasketResult",
    "simulate_correlated_gbm",
    "diversification_ratio",
]


def align_returns(price_frame) -> Tuple[np.ndarray, List[str]]:
    """Log returns of every column of a price DataFrame, on common dates.

    Rows with any missing value are dropped so the correlation is estimated on
    a single contiguous panel -- pairwise-complete estimation would give a
    matrix that is not necessarily positive semi-definite, which then breaks
    the Cholesky factor.  Returns ``(matrix (n_obs, n_assets), column_names)``.
    """
    import pandas as pd

    if price_frame is None or len(price_frame) < 3:
        return np.empty((0, 0)), []
    df = price_frame.copy()
    df = df.replace([np.inf, -np.inf], np.nan).dropna(how="all", axis=1)
    df = df[[c for c in df.columns if (df[c].dropna() > 0).all()]]
    if df.shape[1] == 0:
        return np.empty((0, 0)), []
    rets = np.log(df).diff().dropna(how="any")
    return rets.to_numpy(dtype=float), [str(c) for c in rets.columns]


def correlation_matrix(returns: np.ndarray) -> np.ndarray:
    """Pearson correlation of the return columns.

    Linear correlation only.  Two caveats that matter for risk work: it is not
    robust to outliers (one crash day can dominate a short sample), and it is
    exactly the wrong statistic in the tails, where equity correlations rise
    toward 1 precisely when diversification is needed most.
    """
    r = np.asarray(returns, dtype=float)
    if r.ndim != 2 or r.shape[0] < 3 or r.shape[1] < 1:
        return np.eye(max(r.shape[1] if r.ndim == 2 else 1, 1))
    with np.errstate(invalid="ignore", divide="ignore"):
        c = np.corrcoef(r, rowvar=False)
    c = np.atleast_2d(c)
    return np.nan_to_num(c, nan=0.0) + np.eye(c.shape[0]) * 0.0


def covariance_matrix(
    returns: np.ndarray, dt: float = DEFAULT_DT, annualize: bool = True
) -> np.ndarray:
    """Sample covariance of the return columns, annualised by default.

    Annualising divides by ``dt`` (equivalently multiplies daily covariance by
    252), which assumes serially uncorrelated returns.
    """
    r = np.asarray(returns, dtype=float)
    if r.ndim != 2 or r.shape[0] < 3:
        n = r.shape[1] if r.ndim == 2 else 1
        return np.zeros((n, n))
    cov = np.cov(r, rowvar=False, ddof=1)
    cov = np.atleast_2d(cov)
    return cov / dt if annualize else cov


def nearest_psd(matrix: np.ndarray, epsilon: float = 1e-10) -> np.ndarray:
    """Nearest positive semi-definite matrix by eigenvalue clipping.

    Math
    ----
    Symmetrise, take the eigendecomposition ``A = Q L Q'``, clip the
    eigenvalues at ``epsilon``, rebuild, then rescale the diagonal back to 1 if
    the input was a correlation matrix.

    Why it is needed: a sample correlation matrix estimated from fewer
    observations than assets is rank-deficient, and any hand-edited matrix can
    easily be inconsistent (correlations must obey a triangle-like constraint).
    Either case makes ``numpy.linalg.cholesky`` raise, which would kill the
    basket simulation.  Clipping is the cheap standard repair; Higham's
    alternating-projection algorithm is more accurate but rarely worth it here.
    """
    a = np.asarray(matrix, dtype=float)
    if a.size == 0:
        return a
    a = 0.5 * (a + a.T)
    vals, vecs = np.linalg.eigh(a)
    if np.all(vals > epsilon):
        return a
    vals = np.maximum(vals, epsilon)
    out = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(out))
    is_corr = np.allclose(np.diag(a), 1.0, atol=1e-6)
    if is_corr and np.all(d > 0):
        out = out / np.outer(d, d)
        np.fill_diagonal(out, 1.0)
    return 0.5 * (out + out.T)


def cholesky_factor(corr: np.ndarray) -> np.ndarray:
    """Lower-triangular Cholesky factor ``L`` with ``L L' = corr``.

    Math
    ----
    If ``Z`` is a vector of independent standard normals then ``L Z`` has
    covariance ``L L' = corr``: one matrix multiply turns independent shocks
    into correlated ones.  This is the standard way to inject a correlation
    structure into a Monte Carlo, and it is exact for Gaussian marginals.

    Falls back to :func:`nearest_psd` when the input is not positive definite
    (a rank-deficient sample estimate or an inconsistent hand-entered matrix),
    and then to escalating diagonal jitter.  Eigenvalue clipping followed by a
    diagonal rescale can leave the smallest eigenvalue at exactly zero, which
    is semi-definite but not definite -- Cholesky needs strictly positive, so
    the jitter loop is not redundant.
    """
    c = np.asarray(corr, dtype=float)
    try:
        return np.linalg.cholesky(c)
    except np.linalg.LinAlgError:
        pass
    repaired = nearest_psd(c)
    for jitter in (0.0, 1e-10, 1e-8, 1e-6, 1e-4, 1e-2):
        try:
            return np.linalg.cholesky(repaired + jitter * np.eye(repaired.shape[0]))
        except np.linalg.LinAlgError:
            continue
    return np.eye(c.shape[0])  # last resort: treat the assets as independent


@dataclass
class BasketResult:
    """Output of a correlated multi-asset simulation."""

    portfolio_paths: np.ndarray
    """``(n_paths, n_steps + 1)`` portfolio value, normalised to start at 1.0."""
    asset_terminal: np.ndarray
    """``(n_paths, n_assets)`` terminal price of each asset."""
    tickers: List[str]
    weights: np.ndarray
    realised_corr: np.ndarray
    """Correlation of the *simulated* asset log returns -- a check that the
    Cholesky injection reproduced the target."""


def simulate_correlated_gbm(
    s0: Sequence[float],
    mu: Sequence[float],
    sigma: Sequence[float],
    corr: np.ndarray,
    n_steps: int,
    n_paths: int,
    weights: Optional[Sequence[float]] = None,
    dt: float = DEFAULT_DT,
    rng: Optional[np.random.Generator] = None,
    tickers: Optional[Sequence[str]] = None,
) -> BasketResult:
    """Correlated multi-asset GBM via Cholesky decomposition.

    Math
    ----
    For each step, draw ``Z ~ N(0, I_k)`` and set ``W = L Z`` with ``L`` the
    Cholesky factor of the correlation matrix.  Asset ``i`` then evolves as

        ``log S_i += (mu_i - sigma_i^2 / 2) dt + sigma_i sqrt(dt) W_i``

    so each asset keeps its own marginal GBM dynamics while the cross-sectional
    dependence matches ``corr``.

    The portfolio is **rebalanced continuously to fixed weights** -- its value
    is tracked as ``V_{t+1} = V_t * (1 + sum_i w_i * simple_return_i)``, which
    is the constant-weight (rebalanced) portfolio, not buy-and-hold.  The two
    differ materially over long horizons: buy-and-hold drifts toward whichever
    asset wins, while rebalancing harvests the volatility of the spread.

    Assumptions
    -----------
    Gaussian dependence: correlation is constant through time and there is no
    tail dependence, so simultaneous crashes are underrepresented relative to
    real markets.  Weights are normalised to sum to 1 and no transaction cost
    or borrowing constraint is applied.

    Memory note: this materialises ``(n_paths, n_assets)`` state, not the full
    per-asset path tensor, so it scales to large path counts.
    """
    rng = rng if rng is not None else np.random.default_rng()
    s0 = np.asarray(s0, dtype=float).ravel()
    mu = np.asarray(mu, dtype=float).ravel()
    sigma = np.asarray(sigma, dtype=float).ravel()
    k = s0.size
    if not (mu.size == sigma.size == k) or k == 0:
        raise ValueError("s0, mu and sigma must be non-empty and the same length")
    corr = np.asarray(corr, dtype=float)
    if corr.shape != (k, k):
        raise ValueError(f"corr must be {k}x{k}, got {corr.shape}")
    L = cholesky_factor(corr)

    if weights is None:
        w = np.full(k, 1.0 / k)
    else:
        w = np.asarray(weights, dtype=float).ravel()
        if w.size != k:
            raise ValueError("weights length must match the number of assets")
        total = w.sum()
        w = w / total if abs(total) > 1e-12 else np.full(k, 1.0 / k)

    n_steps = int(max(1, n_steps))
    n_paths = int(max(2, n_paths))
    sqrt_dt = np.sqrt(dt)
    drift = (mu - 0.5 * sigma**2) * dt

    log_s = np.tile(np.log(s0), (n_paths, 1))          # (n_paths, k)
    port = np.empty((n_paths, n_steps + 1))
    port[:, 0] = 1.0
    ret_sum = np.zeros((n_steps, k))
    ret_sq = np.zeros((n_steps, k))
    step_returns = np.empty((n_steps, n_paths, k)) if n_paths * n_steps * k <= 4_000_000 else None

    for t in range(n_steps):
        z = rng.standard_normal((n_paths, k))
        shocks = z @ L.T                                # correlated normals
        step = drift + sigma * sqrt_dt * shocks
        simple = np.expm1(step)                         # per-asset simple return
        port[:, t + 1] = port[:, t] * (1.0 + simple @ w)
        log_s += step
        if step_returns is not None:
            step_returns[t] = step

    asset_terminal = np.exp(log_s)
    if step_returns is not None:
        flat = step_returns.reshape(-1, k)
        realised = correlation_matrix(flat)
    else:
        realised = np.asarray(corr, dtype=float)

    return BasketResult(
        portfolio_paths=port,
        asset_terminal=asset_terminal,
        tickers=list(tickers) if tickers else [f"A{i+1}" for i in range(k)],
        weights=w,
        realised_corr=realised,
    )


def diversification_ratio(
    weights: Sequence[float], sigma: Sequence[float], corr: np.ndarray
) -> float:
    """Weighted average volatility divided by portfolio volatility.

    Math
    ----
    ``DR = (w' sigma) / sqrt(w' Sigma w)`` where ``Sigma = D corr D`` and
    ``D = diag(sigma)``.  A ratio of 1 means the basket behaves as one asset
    (perfect correlation); higher is more diversified, and the theoretical
    maximum with ``k`` uncorrelated equal-weighted assets is ``sqrt(k)``.
    """
    w = np.asarray(weights, dtype=float).ravel()
    s = np.asarray(sigma, dtype=float).ravel()
    c = np.asarray(corr, dtype=float)
    if w.size != s.size or c.shape != (w.size, w.size):
        return float("nan")
    total = w.sum()
    if abs(total) > 1e-12:
        w = w / total
    cov = np.outer(s, s) * c
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return float("nan")
    return float((w @ s) / np.sqrt(port_var))
