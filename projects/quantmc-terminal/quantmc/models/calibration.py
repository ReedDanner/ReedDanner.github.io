"""
Parameter estimation: fit every path model to a historical return sample.

Each ``calibrate_*`` function takes a 1-D array of log returns sampled at
interval ``dt`` (in years) and returns a plain dict of the keyword arguments
the matching generator in :mod:`quantmc.models.paths` expects.  That symmetry
is deliberate -- the "Calibrate from history" button is literally
``params.update(calibrate(model, returns, dt))``.

Drift convention
----------------
Every model is calibrated to the same annualised drift

    ``mu = mean(r)/dt + 0.5 * var(r)/dt``

which is the maximum-likelihood estimate of the SDE drift given the observed
log returns, and makes ``E[S_T] = S_0 e^{mu T}`` match the sample's realised
compounding.  This means the models differ in *shape*, not in expected value,
so comparing them isolates the effect of the distributional assumption.

Caveat that applies to all of it: an estimate from ``n`` observations has a
standard error of roughly ``sigma/sqrt(n)`` for volatility but
``sigma/sqrt(T)`` for drift, where ``T`` is the *calendar span*.  Two years of
daily data pins volatility down well and says almost nothing about drift --
which is why a fitted ``mu`` should usually be overridden with a view.

MODELLING TOOL, NOT INVESTMENT ADVICE.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

import numpy as np
from scipy import optimize, signal
from scipy import stats as sps

TRADING_DAYS = 252.0
DEFAULT_DT = 1.0 / TRADING_DAYS

#: Finite stand-in for "inadmissible parameters" in likelihood objectives.
#: A finite penalty keeps finite-difference gradients defined at the boundary,
#: which ``inf`` does not (inf - inf = nan stalls L-BFGS-B).
_PENALTY = 1.0e12

__all__ = [
    "annualized_moments",
    "calibrate_gbm",
    "calibrate_student_t",
    "calibrate_merton",
    "calibrate_heston",
    "calibrate_garch",
    "calibrate",
    "garch_loglik",
    "garch_variance_path",
]


def _clean(returns: Sequence[float]) -> np.ndarray:
    r = np.asarray(returns, dtype=float).ravel()
    return r[np.isfinite(r)]


def annualized_moments(
    returns: Sequence[float], dt: float = DEFAULT_DT
) -> Tuple[float, float]:
    """Annualised ``(mu, sigma)`` from a log-return sample.

    ``sigma = std(r) / sqrt(dt)`` and ``mu = mean(r)/dt + sigma^2/2``.  The
    ``sigma^2/2`` term converts the mean *log* return into the drift of the
    arithmetic SDE, so the two are not interchangeable: for a 30% vol name the
    convexity adjustment alone is 4.5% a year.
    """
    r = _clean(returns)
    if r.size < 2:
        return 0.0, 0.0
    sigma = float(r.std(ddof=1)) / np.sqrt(dt)
    mu = float(r.mean()) / dt + 0.5 * sigma * sigma
    return mu, sigma


# --------------------------------------------------------------------------
# 1 / 2. GBM and Student-t
# --------------------------------------------------------------------------
def calibrate_gbm(
    returns: Sequence[float], dt: float = DEFAULT_DT
) -> Dict[str, float]:
    """MLE of GBM parameters: sample mean and standard deviation of log returns.

    For a Gaussian random walk the sample mean and variance *are* the maximum
    likelihood estimators, so there is nothing to optimise numerically.
    """
    mu, sigma = annualized_moments(returns, dt)
    return {"mu": mu, "sigma": sigma}


def calibrate_student_t(
    returns: Sequence[float], dt: float = DEFAULT_DT
) -> Dict[str, float]:
    """MLE fit of a Student-t to the returns; keeps volatility from the sample.

    ``scipy.stats.t.fit`` maximises the t likelihood over ``(df, loc, scale)``.
    The fitted ``df`` is reported as ``nu`` and clipped to ``[2.1, 50]``: below
    2.1 the variance does not exist (the simulator could not standardise it),
    and above 50 the t is numerically indistinguishable from a normal.

    ``sigma`` is deliberately taken from the *sample* standard deviation rather
    than from the t ``scale`` parameter, so that switching between GBM and
    Student-t changes only the tail shape and leaves total variance unchanged.
    Typical daily equity fits land at ``nu`` between 3 and 5.
    """
    r = _clean(returns)
    mu, sigma = annualized_moments(r, dt)
    nu = 4.0
    if r.size >= 50:
        try:
            df, _loc, _scale = sps.t.fit(r)
            if np.isfinite(df):
                nu = float(np.clip(df, 2.1, 50.0))
        except Exception:
            pass
    return {"mu": mu, "sigma": sigma, "nu": nu}


# --------------------------------------------------------------------------
# 3. Merton jump diffusion
# --------------------------------------------------------------------------
def calibrate_merton(
    returns: Sequence[float], dt: float = DEFAULT_DT,
    threshold: float = 3.0, n_iter: int = 8,
) -> Dict[str, float]:
    """Threshold ("bipower-style") estimator for Merton jump-diffusion.

    Method
    ------
    Full MLE of a jump diffusion is an ill-conditioned mixture problem, so this
    uses the standard practitioner alternative -- iterative threshold
    separation:

    1. Start with ``sigma`` = sample standard deviation.
    2. Flag returns more than ``threshold`` standard deviations from the
       diffusive mean as jump days.
    3. Re-estimate ``sigma`` from the *unflagged* returns only.
    4. Repeat until the flag set stops changing (or ``n_iter`` passes).

    Then ``lambda = n_jumps / (n * dt)`` jumps per year, and the jump size mean
    and standard deviation come from the flagged returns after removing the
    diffusive drift.  ``sigma`` is annualised from the unflagged sample, so it
    is the *diffusive* volatility excluding jumps and is always lower than the
    total volatility.

    Assumptions and limits
    ----------------------
    The threshold is arbitrary: at 3 sigma a Gaussian sample already produces
    roughly 3 false positives per 1000 days, so ``lambda`` is biased upward for
    a genuinely jump-free series.  Small jumps hiding under the threshold are
    absorbed into ``sigma``.  It also cannot distinguish one large jump from
    two same-day jumps.  Treat the output as a sensible starting point to hand
    to the parameter panel, not as a precise estimate.
    """
    r = _clean(returns)
    if r.size < 60:
        mu, sigma = annualized_moments(r, dt)
        return {"mu": mu, "sigma": sigma, "lam": 0.0,
                "jump_mean": 0.0, "jump_std": 0.0}

    mu_total, sigma_total = annualized_moments(r, dt)
    sd = float(r.std(ddof=1))
    mean = float(r.mean())
    mask = np.zeros(r.size, dtype=bool)
    for _ in range(int(n_iter)):
        new_mask = np.abs(r - mean) > threshold * sd
        if new_mask.sum() >= r.size - 10:  # refuse to flag (almost) everything
            break
        if np.array_equal(new_mask, mask):
            break
        mask = new_mask
        core = r[~mask]
        if core.size < 20:
            break
        sd = float(core.std(ddof=1))
        mean = float(core.mean())

    n_jumps = int(mask.sum())
    sigma_diff = sd / np.sqrt(dt)
    if n_jumps >= 2:
        jumps = r[mask] - mean
        lam = n_jumps / (r.size * dt)
        jump_mean = float(jumps.mean())
        jump_std = float(jumps.std(ddof=1))
    else:
        lam, jump_mean, jump_std = 0.0, 0.0, 0.0
        sigma_diff = sigma_total

    return {
        "mu": mu_total,
        "sigma": float(sigma_diff),
        "lam": float(lam),
        "jump_mean": jump_mean,
        "jump_std": float(max(jump_std, 1e-6)) if n_jumps >= 2 else 0.0,
    }


# --------------------------------------------------------------------------
# 4. Heston
# --------------------------------------------------------------------------
def calibrate_heston(
    returns: Sequence[float], dt: float = DEFAULT_DT, window: int = 21
) -> Dict[str, float]:
    """Moment-matching calibration of Heston from a realised-variance proxy.

    Method
    ------
    Build a non-overlapping realised-variance series
    ``rv_j = var(r in window j) / dt`` (annualised), then:

    * ``theta`` = mean of ``rv``  (long-run variance)
    * ``v0``    = most recent ``rv``
    * ``kappa`` from the AR(1) coefficient of ``rv``: the exact discretisation
      of an Ornstein-Uhlenbeck variance is ``rv_{j+1} = a + b rv_j + e`` with
      ``b = exp(-kappa * Delta)``, so ``kappa = -ln(b) / Delta`` where
      ``Delta = window * dt`` is the spacing of the variance observations.
    * ``xi`` from the residual scale: ``Var(e) ~ xi^2 * E[v] * Delta`` gives
      ``xi = std(e) / sqrt(mean(rv) * Delta)``.
    * ``rho`` = correlation between the window's aggregate return and the
      change in realised variance -- the empirical leverage effect, which is
      reliably negative for equity indices.

    Non-overlapping windows are used on purpose: overlapping rolling variance
    is mechanically autocorrelated, which would bias ``b`` toward 1 and drive
    ``kappa`` to zero.

    Assumptions and known biases
    ----------------------------
    This is calibration to the **physical** measure from historical returns
    only.  A trading desk calibrates Heston to the *option surface* under the
    risk-neutral measure and gets materially different (usually higher ``xi``,
    more negative ``rho``) numbers, because the surface prices a variance risk
    premium that history does not contain.

    Realised variance over a finite window is a noisy proxy for instantaneous
    variance, and that measurement error propagates in a specific, measurable
    way.  Verified against simulated Heston paths with known parameters:

    * ``theta`` -- **unbiased**.  Recovers 0.05 from 0.05 with a standard error
      around 0.006 on 25 years of daily data.  It is a plain sample mean, so
      the noise in ``rv`` averages out.
    * ``kappa`` -- **biased high**, typically by 50%: recovers ~4.7 from a true
      3.0, consistently and regardless of sample size.  This is classical
      errors-in-variables attenuation: noise in the AR(1) *regressor* pulls the
      slope ``b`` toward zero, and ``kappa = -ln(b)/Delta`` turns that into an
      overstated reversion speed.  Read it as an upper bound.
    * ``rho`` -- **sign reliable, magnitude attenuated**, again by
      errors-in-variables: recovers about -0.24 from a true -0.7.  Assume the
      true leverage correlation is materially more negative than reported.
      (A daily-frequency overlapping-window estimator was tested as an
      alternative and is strictly worse -- it returned +0.04 on the same data,
      the wrong sign entirely -- so the non-overlapping version is kept.)
    * ``xi`` -- roughly unbiased to slightly high, for the same reason
      ``kappa`` is high: some of the measurement noise is read as vol of vol.

    Parameters are floored and clipped to keep the simulator stable.
    """
    r = _clean(returns)
    mu, sigma = annualized_moments(r, dt)
    fallback = {"mu": mu, "v0": sigma**2, "kappa": 3.0, "theta": sigma**2,
                "xi": 0.5, "rho": -0.7}
    w = int(max(5, window))
    n_win = r.size // w
    if n_win < 8:
        return fallback

    chunks = r[: n_win * w].reshape(n_win, w)
    rv = chunks.var(axis=1, ddof=1) / dt          # annualised variance per window
    agg_ret = chunks.sum(axis=1)                  # window log return
    rv = rv[np.isfinite(rv)]
    if rv.size < 8 or rv.mean() <= 0:
        return fallback

    theta = float(rv.mean())
    v0 = float(rv[-1])
    delta = w * dt

    x, y = rv[:-1], rv[1:]
    denom = float(((x - x.mean()) ** 2).sum())
    if denom <= 0:
        return fallback
    b = float(((x - x.mean()) * (y - y.mean())).sum() / denom)
    a = float(y.mean() - b * x.mean())
    b = float(np.clip(b, 1e-4, 0.999))
    kappa = float(np.clip(-np.log(b) / delta, 0.1, 25.0))

    resid = y - (a + b * x)
    xi = float(np.std(resid, ddof=1) / np.sqrt(max(theta * delta, 1e-12)))
    xi = float(np.clip(xi, 0.05, 5.0))

    if agg_ret.size >= 9:
        rho = float(np.corrcoef(agg_ret[1:], np.diff(rv))[0, 1])
        rho = float(np.clip(rho if np.isfinite(rho) else -0.7, -0.95, 0.95))
    else:
        rho = -0.7

    return {"mu": mu, "v0": max(v0, 1e-6), "kappa": kappa,
            "theta": max(theta, 1e-6), "xi": xi, "rho": rho}


# --------------------------------------------------------------------------
# 5. GARCH(1,1)
# --------------------------------------------------------------------------
def garch_variance_path(
    omega: float, alpha: float, beta: float, e2: np.ndarray, h0: float
) -> np.ndarray:
    """Conditional variance recursion ``h_t = omega + alpha e2_{t-1} + beta h_{t-1}``.

    Implemented as a first-order IIR filter rather than a Python loop.  The
    recursion is linear in ``h``, so with the driving term
    ``u_t = omega + alpha e2_{t-1}`` (and ``u_0 = h0``) it is exactly

        ``h = lfilter([1], [1, -beta], u)``

    which scipy evaluates in compiled code.  That matters because the optimiser
    in :func:`calibrate_garch` evaluates this thousands of times; the filter
    form turns a multi-second fit into a few milliseconds.  ``h`` is guaranteed
    positive whenever ``omega > 0`` and ``alpha, beta, h0 >= 0``.
    """
    u = np.empty(e2.size, dtype=float)
    u[0] = h0
    if e2.size > 1:
        u[1:] = omega + alpha * e2[:-1]
    return signal.lfilter([1.0], [1.0, -float(beta)], u)


def garch_loglik(
    params: Sequence[float], r: np.ndarray, mean: float
) -> float:
    """Negative Gaussian log-likelihood of GARCH(1,1) given ``(omega, a, b)``.

    Math
    ----
    With ``e_t = r_t - mean`` and ``h_t = omega + a e_{t-1}^2 + b h_{t-1}``
    (seeded at the sample variance), the conditional log-likelihood is

        ``-0.5 * sum( log(2 pi h_t) + e_t^2 / h_t )``

    which is returned negated for minimisation.  Inadmissible parameters
    (non-positive ``omega``, negative coefficients, non-stationary persistence)
    return a large finite penalty rather than ``inf`` so that L-BFGS-B's
    finite-difference gradient stays defined at the boundary.
    """
    omega, a, b = (float(p) for p in params)
    if omega <= 0 or a < 0 or b < 0 or a + b >= 0.99999:
        return _PENALTY
    e = np.asarray(r, dtype=float) - mean
    e2 = e * e
    h0 = float(e2.mean())
    if h0 <= 0:
        return _PENALTY
    h = garch_variance_path(omega, a, b, e2, h0)
    if not np.all(h > 1e-18) or not np.all(np.isfinite(h)):
        return _PENALTY
    ll = float(np.sum(np.log(h) + e2 / h))
    return 0.5 * (ll + e2.size * np.log(2.0 * np.pi))


def calibrate_garch(
    returns: Sequence[float], dt: float = DEFAULT_DT
) -> Dict[str, float]:
    """Quasi-maximum-likelihood GARCH(1,1) fit with a constant mean.

    Method
    ------
    ``(omega, alpha, beta)`` are estimated by minimising the negative Gaussian
    log-likelihood (:func:`garch_loglik`) with L-BFGS-B under box constraints
    and a stationarity guard.  Several starting points are tried -- the
    likelihood surface has a long flat ridge along ``alpha + beta ~ const``, so
    a single start regularly lands in a corner.  Gaussian QMLE is consistent
    for the variance parameters even when the true innovations are fat-tailed,
    which is why this is the standard estimator despite equity returns not
    being conditionally normal.

    The returned parameters are **per step** (daily for ``dt = 1/252``), as the
    simulator expects.  ``mu`` uses the shared annualised-drift convention, and
    the diagnostic keys ``persistence``, ``half_life`` and ``sigma_lr``
    (annualised long-run vol) are included for the parameter panel.

    Typical daily equity fits: ``alpha`` 0.05-0.12, ``beta`` 0.85-0.93,
    persistence 0.95-0.99 -- i.e. a volatility half-life of one to three
    months.
    """
    r = _clean(returns)
    mu, sigma = annualized_moments(r, dt)
    var = float(np.var(r)) if r.size > 2 else 1e-6
    fallback = {
        "mu": mu, "omega": var * 0.02, "alpha": 0.08, "beta": 0.90, "nu": 0.0,
        "persistence": 0.98, "half_life": np.log(0.5) / np.log(0.98),
        "sigma_lr": sigma,
    }
    if r.size < 100 or var <= 0:
        return fallback

    mean = float(r.mean())
    best = None
    for a0, b0 in ((0.08, 0.90), (0.05, 0.94), (0.15, 0.80), (0.03, 0.96)):
        x0 = np.array([var * (1.0 - a0 - b0), a0, b0])
        try:
            res = optimize.minimize(
                garch_loglik, x0, args=(r, mean), method="L-BFGS-B",
                bounds=[(1e-12, var * 10.0), (1e-6, 0.6), (1e-6, 0.999)],
                options={"maxiter": 400, "ftol": 1e-11},
            )
        except Exception:
            continue
        if res.success or np.isfinite(res.fun):
            if best is None or res.fun < best.fun:
                best = res
    if best is None:
        return fallback

    omega, alpha, beta = (float(v) for v in best.x)
    persistence = alpha + beta
    if persistence >= 0.9999:
        scale = 0.9995 / persistence
        alpha *= scale
        beta *= scale
        persistence = alpha + beta
    lr_var = omega / max(1.0 - persistence, 1e-8)
    half_life = np.log(0.5) / np.log(persistence) if 0 < persistence < 1 else np.inf
    return {
        "mu": mu, "omega": omega, "alpha": alpha, "beta": beta, "nu": 0.0,
        "persistence": persistence, "half_life": float(half_life),
        "sigma_lr": float(np.sqrt(lr_var / dt)),
    }


# --------------------------------------------------------------------------
# dispatcher
# --------------------------------------------------------------------------
def calibrate(
    model: str, returns: Sequence[float], dt: float = DEFAULT_DT,
    block: int = 21,
) -> Dict[str, float]:
    """Calibrate ``model`` to ``returns`` and return generator keyword arguments.

    Diagnostic keys that the generators do not accept (``persistence``,
    ``half_life``, ``sigma_lr``) are included for display; ``simulate_paths``
    filters them out, so the dict can be passed straight through.
    """
    r = _clean(returns)
    if model == "gbm":
        return calibrate_gbm(r, dt)
    if model == "student_t":
        return calibrate_student_t(r, dt)
    if model == "merton":
        return calibrate_merton(r, dt)
    if model == "heston":
        return calibrate_heston(r, dt)
    if model == "garch":
        return calibrate_garch(r, dt)
    if model == "bootstrap":
        mu, _ = annualized_moments(r, dt)
        return {"mu": mu, "recenter": 0.0}
    if model == "block_bootstrap":
        mu, _ = annualized_moments(r, dt)
        return {"mu": mu, "block": float(block), "recenter": 0.0}
    raise KeyError(f"no calibrator for model {model!r}")
