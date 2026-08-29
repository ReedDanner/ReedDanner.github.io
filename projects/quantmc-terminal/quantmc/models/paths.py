"""
Path-generating stochastic models for the Monte Carlo engine.

Every generator in this module is a pure function of numpy arrays and a
``numpy.random.Generator``.  Nothing here imports the UI, the data layer, or
anything else with side effects, so each model can be called headlessly::

    from quantmc.models.paths import simulate_gbm
    paths = simulate_gbm(100.0, 252, 10_000, 1/252, np.random.default_rng(0),
                         mu=0.08, sigma=0.25)

Conventions used throughout
---------------------------
* ``s0``      : scalar spot price at t=0.
* ``n_steps`` : number of time steps to simulate (horizon = n_steps * dt).
* ``n_paths`` : number of independent sample paths.
* ``dt``      : length of one step in *years* (1/252 for daily trading steps).
* Returned array has shape ``(n_paths, n_steps + 1)``; column 0 equals ``s0``.
* ``mu``      : annualised drift of the *arithmetic* return, i.e. the SDE is
  ``dS/S = mu dt + sigma dW`` so that ``E[S_T] = s0 * exp(mu * T)`` for every
  model that is drift-compensated (GBM, Student-t, Merton, Heston).
* ``sigma``   : annualised volatility (standard deviation of log returns).

MODELLING TOOL, NOT INVESTMENT ADVICE.  Every distribution produced here is
conditional on the assumptions of the chosen model; none of them is a forecast.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

TRADING_DAYS: float = 252.0
DEFAULT_DT: float = 1.0 / TRADING_DAYS

__all__ = [
    "TRADING_DAYS",
    "DEFAULT_DT",
    "MODEL_REGISTRY",
    "MODEL_LABELS",
    "MODEL_PARAM_SPECS",
    "HISTORY_MODELS",
    "draw_normals",
    "simulate_gbm",
    "simulate_student_t",
    "simulate_merton",
    "simulate_heston",
    "simulate_garch",
    "simulate_bootstrap",
    "simulate_block_bootstrap",
    "simulate_paths",
    "default_params",
]


# --------------------------------------------------------------------------
# random number helpers
# --------------------------------------------------------------------------
def draw_normals(
    rng: np.random.Generator,
    n_paths: int,
    n_steps: int,
    antithetic: bool = False,
) -> np.ndarray:
    """Draw an ``(n_paths, n_steps)`` block of standard normals.

    With ``antithetic=True`` the second half of the block is the negation of
    the first half.  Antithetic sampling leaves the marginal distribution
    unchanged (Z and -Z are both N(0,1)) but induces negative correlation
    between path pairs, which reduces the variance of the Monte Carlo estimate
    of any monotone functional of the paths.  If ``n_paths`` is odd the extra
    path is drawn independently.
    """
    if n_steps <= 0:
        return np.empty((n_paths, 0), dtype=float)
    if antithetic and n_paths >= 2:
        half = n_paths // 2
        z = rng.standard_normal((half, n_steps))
        out = np.empty((n_paths, n_steps), dtype=float)
        out[:half] = z
        out[half : 2 * half] = -z
        if n_paths % 2:
            out[2 * half :] = rng.standard_normal((1, n_steps))
        return out
    return rng.standard_normal((n_paths, n_steps))


def _step_normals(
    rng: np.random.Generator, n_paths: int, antithetic: bool
) -> np.ndarray:
    """One time-step worth of normals, mirrored across the path axis if asked.

    Used by the models that must be advanced step by step (Heston, GARCH) so
    that peak memory stays O(n_paths) instead of O(n_paths * n_steps).
    """
    if antithetic and n_paths >= 2:
        half = n_paths // 2
        z = rng.standard_normal(half)
        out = np.empty(n_paths, dtype=float)
        out[:half] = z
        out[half : 2 * half] = -z
        if n_paths % 2:
            out[2 * half :] = rng.standard_normal(1)
        return out
    return rng.standard_normal(n_paths)


def _prices_from_log_increments(s0: float, increments: np.ndarray) -> np.ndarray:
    """Turn ``(n_paths, n_steps)`` log increments into a price path matrix.

    Returns ``(n_paths, n_steps + 1)`` with the spot price in column 0.
    """
    n_paths, n_steps = increments.shape
    out = np.empty((n_paths, n_steps + 1), dtype=float)
    out[:, 0] = 0.0
    np.cumsum(increments, axis=1, out=out[:, 1:])
    np.exp(out, out=out)
    out *= float(s0)
    return out


# --------------------------------------------------------------------------
# 1. Geometric Brownian motion
# --------------------------------------------------------------------------
def simulate_gbm(
    s0: float,
    n_steps: int,
    n_paths: int,
    dt: float,
    rng: np.random.Generator,
    mu: float = 0.08,
    sigma: float = 0.20,
    antithetic: bool = False,
) -> np.ndarray:
    """Geometric Brownian motion, the Black-Scholes baseline.

    Math
    ----
    ``dS_t = mu S_t dt + sigma S_t dW_t`` integrates exactly to

        ``log S_{t+dt} - log S_t = (mu - sigma^2/2) dt + sigma sqrt(dt) Z``

    with ``Z ~ N(0,1)``.  The scheme is therefore *exact* at the step dates --
    there is no discretisation bias, only sampling error.

    Assumptions
    -----------
    Constant drift and volatility, continuous paths (no jumps), independent
    Gaussian log returns (no autocorrelation, no volatility clustering, thin
    tails).  Real equity returns violate the tail and clustering assumptions;
    GBM is the reference case, not the realistic one.
    """
    if n_steps <= 0:
        return np.full((n_paths, 1), float(s0))
    z = draw_normals(rng, n_paths, n_steps, antithetic)
    z *= sigma * np.sqrt(dt)
    z += (mu - 0.5 * sigma * sigma) * dt
    return _prices_from_log_increments(s0, z)


# --------------------------------------------------------------------------
# 2. Student-t (fat-tailed) GBM
# --------------------------------------------------------------------------
def simulate_student_t(
    s0: float,
    n_steps: int,
    n_paths: int,
    dt: float,
    rng: np.random.Generator,
    mu: float = 0.08,
    sigma: float = 0.20,
    nu: float = 4.0,
    antithetic: bool = False,
) -> np.ndarray:
    """GBM driven by standardised Student-t shocks instead of normals.

    Math
    ----
    Let ``T_nu`` be Student-t with ``nu`` degrees of freedom and
    ``eps = T_nu / sqrt(nu / (nu - 2))`` its unit-variance standardisation
    (finite only for ``nu > 2``).  The log increment is

        ``(mu - sigma^2/2) dt + sigma sqrt(dt) eps``

    so the per-step variance matches GBM exactly while the excess kurtosis is
    ``6/(nu - 4)`` for ``nu > 4`` (infinite for ``nu <= 4``).

    Assumptions
    -----------
    IID heavy-tailed shocks: fat tails are present at every step but there is
    still no volatility clustering, and the sum of many steps drifts back
    toward normality by the CLT, so a 1-year terminal distribution is far less
    fat-tailed than the daily one.
    """
    if n_steps <= 0:
        return np.full((n_paths, 1), float(s0))
    nu = float(max(nu, 2.05))
    if antithetic and n_paths >= 2:
        half = n_paths // 2
        t = rng.standard_t(nu, size=(half, n_steps))
        eps = np.empty((n_paths, n_steps), dtype=float)
        eps[:half] = t
        eps[half : 2 * half] = -t
        if n_paths % 2:
            eps[2 * half :] = rng.standard_t(nu, size=(1, n_steps))
    else:
        eps = rng.standard_t(nu, size=(n_paths, n_steps))
    eps /= np.sqrt(nu / (nu - 2.0))
    eps *= sigma * np.sqrt(dt)
    eps += (mu - 0.5 * sigma * sigma) * dt
    return _prices_from_log_increments(s0, eps)


# --------------------------------------------------------------------------
# 3. Merton jump diffusion
# --------------------------------------------------------------------------
def simulate_merton(
    s0: float,
    n_steps: int,
    n_paths: int,
    dt: float,
    rng: np.random.Generator,
    mu: float = 0.08,
    sigma: float = 0.18,
    lam: float = 1.0,
    jump_mean: float = -0.02,
    jump_std: float = 0.06,
    antithetic: bool = False,
) -> np.ndarray:
    """Merton (1976) jump diffusion: diffusion plus compound Poisson jumps.

    Math
    ----
    ``dS/S = (mu - lam*kbar) dt + sigma dW + (e^Y - 1) dN`` with
    ``N_t ~ Poisson(lam t)``, log jump sizes ``Y ~ N(m, s^2)`` and compensator
    ``kbar = E[e^Y] - 1 = exp(m + s^2/2) - 1``.  One log increment is

        ``(mu - lam*kbar - sigma^2/2) dt + sigma sqrt(dt) Z + sum_{i<=N} Y_i``

    and the jump sum is drawn in closed form as ``N*m + sqrt(N)*s*Z2`` because
    a sum of ``N`` iid normals is ``N(N m, N s^2)``.  The compensator keeps
    ``E[S_T] = s0 exp(mu T)``, so ``mu`` stays comparable across models.

    Assumptions
    -----------
    Jump arrivals are independent of the diffusion and of each other, jump
    sizes are lognormal and iid, and the intensity is constant.  Crash
    clustering (jumps arriving in bursts) is not captured.
    """
    if n_steps <= 0:
        return np.full((n_paths, 1), float(s0))
    lam = float(max(lam, 0.0))
    kbar = np.exp(jump_mean + 0.5 * jump_std * jump_std) - 1.0
    inc = draw_normals(rng, n_paths, n_steps, antithetic)
    inc *= sigma * np.sqrt(dt)
    inc += (mu - lam * kbar - 0.5 * sigma * sigma) * dt
    if lam > 0.0:
        counts = rng.poisson(lam * dt, size=(n_paths, n_steps)).astype(float)
        z2 = rng.standard_normal((n_paths, n_steps))
        inc += counts * jump_mean + np.sqrt(counts) * jump_std * z2
    return _prices_from_log_increments(s0, inc)


# --------------------------------------------------------------------------
# 4. Heston stochastic volatility
# --------------------------------------------------------------------------
def simulate_heston(
    s0: float,
    n_steps: int,
    n_paths: int,
    dt: float,
    rng: np.random.Generator,
    mu: float = 0.08,
    v0: float = 0.04,
    kappa: float = 3.0,
    theta: float = 0.04,
    xi: float = 0.5,
    rho: float = -0.7,
    antithetic: bool = False,
) -> np.ndarray:
    """Heston (1993) stochastic volatility, full-truncation Euler scheme.

    Math
    ----
    ``dS/S = mu dt + sqrt(v) dW1``,
    ``dv = kappa (theta - v) dt + xi sqrt(v) dW2``, ``corr(dW1, dW2) = rho``.

    Discretised with the Lord et al. full-truncation fix, which replaces ``v``
    by ``max(v, 0)`` everywhere it is used but lets the state itself go
    negative -- the smallest discretisation bias among the simple schemes::

        v_next     = v + kappa (theta - v+) dt + xi sqrt(v+ dt) Z2
        log S_next = log S + (mu - v+/2) dt + sqrt(v+ dt) Z1

    ``rho < 0`` reproduces the equity leverage effect (vol up when price down)
    and produces a negatively skewed terminal distribution and a vol smirk.
    The Feller condition ``2 kappa theta > xi^2`` keeps the continuous-time
    variance strictly positive; it is reported to the user but not enforced.

    Assumptions
    -----------
    Variance is mean-reverting, square-root, and driven by a single Brownian
    factor correlated with the price.  Euler stepping adds O(dt) bias: small at
    daily steps, visible at weekly or coarser.
    """
    if n_steps <= 0:
        return np.full((n_paths, 1), float(s0))
    sqrt_dt = np.sqrt(dt)
    rho = float(np.clip(rho, -0.999, 0.999))
    rho_c = np.sqrt(1.0 - rho * rho)

    logs = np.empty((n_paths, n_steps + 1), dtype=float)
    logs[:, 0] = np.log(float(s0))
    v = np.full(n_paths, float(max(v0, 0.0)))
    cur = logs[:, 0].copy()
    for i in range(n_steps):
        z1 = _step_normals(rng, n_paths, antithetic)
        z2 = rho * z1 + rho_c * _step_normals(rng, n_paths, antithetic)
        vp = np.maximum(v, 0.0)
        sv = np.sqrt(vp)
        cur = cur + (mu - 0.5 * vp) * dt + sv * sqrt_dt * z1
        logs[:, i + 1] = cur
        v = v + kappa * (theta - vp) * dt + xi * sv * sqrt_dt * z2
    return np.exp(logs)


# --------------------------------------------------------------------------
# 5. GARCH(1,1)
# --------------------------------------------------------------------------
def simulate_garch(
    s0: float,
    n_steps: int,
    n_paths: int,
    dt: float,
    rng: np.random.Generator,
    mu: float = 0.08,
    omega: float = 2.0e-6,
    alpha: float = 0.08,
    beta: float = 0.90,
    h0: Optional[float] = None,
    nu: float = 0.0,
    antithetic: bool = False,
) -> np.ndarray:
    """GARCH(1,1) conditional-variance simulation of log returns.

    Math
    ----
    ``r_t = m + sqrt(h_t) z_t``,
    ``h_t = omega + alpha (r_{t-1} - m)^2 + beta h_{t-1}``,
    with ``z_t`` standard normal (``nu <= 2``) or standardised Student-t.
    ``omega, alpha, beta`` are *per step* (daily when ``dt = 1/252``).
    Stationarity requires ``alpha + beta < 1``, in which case the long-run
    variance is ``omega / (1 - alpha - beta)`` and the annualised long-run vol
    is ``sqrt(that / dt)``.  The per-step mean is set to
    ``(mu - sigma_lr^2 / 2) * dt`` so the drift is comparable with the other
    models.  Persistence at or above 1 is rescaled to 0.9999 to keep the
    recursion from exploding.

    Assumptions
    -----------
    Volatility clusters and mean-reverts, but responds symmetrically to
    positive and negative shocks (no leverage term -- use GJR/EGARCH for that),
    and the parameters are constant over the horizon.
    """
    if n_steps <= 0:
        return np.full((n_paths, 1), float(s0))
    alpha = float(max(alpha, 0.0))
    beta = float(max(beta, 0.0))
    omega = float(max(omega, 1e-14))
    persistence = alpha + beta
    if persistence >= 0.9999:
        scale = 0.9999 / persistence
        alpha *= scale
        beta *= scale
        persistence = alpha + beta
    lr_var = omega / max(1.0 - persistence, 1e-8)
    sigma_lr = np.sqrt(lr_var / dt)
    m = (mu - 0.5 * sigma_lr * sigma_lr) * dt

    h = np.full(n_paths, float(h0) if h0 and h0 > 0 else lr_var)
    logs = np.empty((n_paths, n_steps + 1), dtype=float)
    logs[:, 0] = np.log(float(s0))
    cur = logs[:, 0].copy()
    use_t = nu is not None and nu > 2.0
    t_scale = np.sqrt(nu / (nu - 2.0)) if use_t else 1.0
    for i in range(n_steps):
        if use_t:
            z = rng.standard_t(nu, size=n_paths) / t_scale
        else:
            z = _step_normals(rng, n_paths, antithetic)
        r = m + np.sqrt(h) * z
        cur = cur + r
        logs[:, i + 1] = cur
        h = omega + alpha * (r - m) ** 2 + beta * h
    return np.exp(logs)


# --------------------------------------------------------------------------
# 6a. IID historical bootstrap
# --------------------------------------------------------------------------
def simulate_bootstrap(
    s0: float,
    n_steps: int,
    n_paths: int,
    dt: float,
    rng: np.random.Generator,
    returns: Optional[np.ndarray] = None,
    mu: Optional[float] = None,
    recenter: bool = False,
    antithetic: bool = False,
) -> np.ndarray:
    """IID resampling (with replacement) of realised historical log returns.

    Math
    ----
    Draw ``n_steps`` indices uniformly with replacement from the empirical log
    return sample and cumulate them.  This is the empirical distribution
    convolved with itself ``n_steps`` times: mean, variance, skew and kurtosis
    of *single-step* returns are reproduced exactly in expectation, with no
    parametric form assumed.

    If ``recenter`` is true the sample is demeaned and the annualised drift
    ``mu`` is imposed instead, letting the user keep the historical shape while
    overriding a drift they do not believe.

    Assumptions
    -----------
    Returns are iid: autocorrelation, volatility clustering and momentum in the
    history are destroyed by the shuffle (use the block bootstrap to keep
    them).  Nothing outside the historical sample can ever be drawn, so the
    worst simulated day is the worst day that already happened.
    """
    if n_steps <= 0:
        return np.full((n_paths, 1), float(s0))
    r = _prepare_returns(returns, mu, recenter, dt)
    idx = rng.integers(0, r.size, size=(n_paths, n_steps))
    return _prices_from_log_increments(s0, r[idx])


# --------------------------------------------------------------------------
# 6b. Circular block bootstrap
# --------------------------------------------------------------------------
def simulate_block_bootstrap(
    s0: float,
    n_steps: int,
    n_paths: int,
    dt: float,
    rng: np.random.Generator,
    returns: Optional[np.ndarray] = None,
    block: int = 21,
    mu: Optional[float] = None,
    recenter: bool = False,
    antithetic: bool = False,
) -> np.ndarray:
    """Circular block bootstrap: resample contiguous blocks of history.

    Math
    ----
    Draw ``ceil(n_steps / block)`` random start indices and concatenate the
    contiguous runs ``r[i : i+block]``, wrapping around the end of the sample
    (this is what makes it *circular*, and it keeps every observation equally
    likely to be drawn).  Because whole runs stay intact, autocorrelation and
    volatility clustering up to lag ``block`` survive the resampling; structure
    at longer lags does not.

    Assumptions
    -----------
    The series is stationary and its dependence decays within ``block`` steps.
    Rule of thumb for daily equity data: 10-40 days.  ``block = 1`` degenerates
    to the iid bootstrap.
    """
    if n_steps <= 0:
        return np.full((n_paths, 1), float(s0))
    r = _prepare_returns(returns, mu, recenter, dt)
    n = r.size
    block = int(max(1, min(block, n)))
    n_blocks = int(np.ceil(n_steps / block))
    starts = rng.integers(0, n, size=(n_paths, n_blocks))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]) % n
    idx = idx.reshape(n_paths, n_blocks * block)[:, :n_steps]
    return _prices_from_log_increments(s0, r[idx])


def _prepare_returns(
    returns: Optional[np.ndarray],
    mu: Optional[float],
    recenter: bool,
    dt: float,
) -> np.ndarray:
    """Validate a historical log-return sample and optionally re-drift it."""
    if returns is None:
        raise ValueError("bootstrap models require a historical return sample")
    r = np.asarray(returns, dtype=float).ravel()
    r = r[np.isfinite(r)]
    if r.size < 30:
        raise ValueError(f"bootstrap needs >= 30 finite returns, got {r.size}")
    if recenter and mu is not None:
        var = float(np.var(r))
        target_step_mean = (mu - 0.5 * var / dt) * dt
        r = r - r.mean() + target_step_mean
    return r


# --------------------------------------------------------------------------
# registry / dispatch
# --------------------------------------------------------------------------
MODEL_REGISTRY: Dict[str, Callable[..., np.ndarray]] = {
    "gbm": simulate_gbm,
    "student_t": simulate_student_t,
    "merton": simulate_merton,
    "heston": simulate_heston,
    "garch": simulate_garch,
    "bootstrap": simulate_bootstrap,
    "block_bootstrap": simulate_block_bootstrap,
}

MODEL_LABELS: Dict[str, str] = {
    "gbm": "Geometric Brownian Motion",
    "student_t": "Student-t GBM (fat tails)",
    "merton": "Merton Jump Diffusion",
    "heston": "Heston Stochastic Vol",
    "garch": "GARCH(1,1)",
    "bootstrap": "Historical Bootstrap (IID)",
    "block_bootstrap": "Block Bootstrap",
}

#: (name, default, tooltip) for every editable parameter, in display order.
MODEL_PARAM_SPECS: Dict[str, Tuple[Tuple[str, float, str], ...]] = {
    "gbm": (
        ("mu", 0.08, "Annualised drift of dS/S"),
        ("sigma", 0.20, "Annualised volatility"),
    ),
    "student_t": (
        ("mu", 0.08, "Annualised drift of dS/S"),
        ("sigma", 0.20, "Annualised volatility"),
        ("nu", 4.0, "Degrees of freedom (must exceed 2)"),
    ),
    "merton": (
        ("mu", 0.08, "Annualised drift of dS/S"),
        ("sigma", 0.18, "Diffusive volatility (ex-jumps)"),
        ("lam", 1.0, "Jump intensity, jumps per year"),
        ("jump_mean", -0.02, "Mean log jump size"),
        ("jump_std", 0.06, "Std dev of log jump size"),
    ),
    "heston": (
        ("mu", 0.08, "Annualised drift of dS/S"),
        ("v0", 0.04, "Initial variance (vol^2)"),
        ("kappa", 3.0, "Mean-reversion speed of variance"),
        ("theta", 0.04, "Long-run variance"),
        ("xi", 0.5, "Vol of vol"),
        ("rho", -0.7, "Correlation of price and variance shocks"),
    ),
    "garch": (
        ("mu", 0.08, "Annualised drift of dS/S"),
        ("omega", 2.0e-6, "Variance intercept, per step"),
        ("alpha", 0.08, "ARCH coefficient (shock loading)"),
        ("beta", 0.90, "GARCH coefficient (persistence)"),
        ("nu", 0.0, "Student-t d.o.f. for shocks (0 = normal)"),
    ),
    "bootstrap": (
        ("mu", 0.08, "Drift override, used only when recentring"),
        ("recenter", 0.0, "1 = impose the drift above, 0 = keep historical"),
    ),
    "block_bootstrap": (
        ("mu", 0.08, "Drift override, used only when recentring"),
        ("block", 21.0, "Block length in steps"),
        ("recenter", 0.0, "1 = impose the drift above, 0 = keep historical"),
    ),
}

#: Models whose parameters are per-step rather than annualised.
PER_STEP_PARAM_MODELS = frozenset({"garch"})

#: Models that need a historical return sample injected before they can run.
HISTORY_MODELS = frozenset({"bootstrap", "block_bootstrap"})


def default_params(model: str) -> Dict[str, float]:
    """Return a fresh dict of default parameters for ``model``."""
    return {name: value for name, value, _ in MODEL_PARAM_SPECS.get(model, ())}


def simulate_paths(
    model: str,
    s0: float,
    n_steps: int,
    n_paths: int,
    dt: float = DEFAULT_DT,
    rng: Optional[np.random.Generator] = None,
    params: Optional[Dict[str, Any]] = None,
    antithetic: bool = False,
) -> np.ndarray:
    """Dispatch to a path generator by name.

    Parameters the target model does not accept are dropped rather than raising
    so a parameter dict carried over from another model cannot break a run.
    """
    if model not in MODEL_REGISTRY:
        raise KeyError(f"unknown model {model!r}; known: {sorted(MODEL_REGISTRY)}")
    fn = MODEL_REGISTRY[model]
    rng = rng if rng is not None else np.random.default_rng()
    code = fn.__code__
    allowed = set(code.co_varnames[: code.co_argcount])
    kwargs: Dict[str, Any] = {
        k: v for k, v in dict(params or {}).items() if k in allowed
    }
    if "recenter" in kwargs:
        kwargs["recenter"] = bool(kwargs["recenter"])
    if "block" in kwargs:
        kwargs["block"] = int(kwargs["block"])
    return fn(s0, int(n_steps), int(n_paths), float(dt), rng,
              antithetic=antithetic, **kwargs)
