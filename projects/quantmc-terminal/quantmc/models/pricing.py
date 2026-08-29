"""
Option pricing: closed form, lattices, Monte Carlo, exotics and implied vol.

All functions are numpy-vectorised where it is meaningful (``S``, ``K``,
``sigma``, ``T`` may be arrays of a broadcastable shape) and free of UI or I/O
dependencies.

Notation
--------
``S`` spot, ``K`` strike, ``T`` time to expiry in years, ``r`` continuously
compounded risk-free rate, ``q`` continuous dividend yield, ``sigma``
annualised volatility, ``kind`` is ``'call'`` or ``'put'``.

Greek units: delta and gamma are per $1 of spot, vega is per **1.00** of
volatility (divide by 100 for "per vol point"), theta is per **year** (divide
by 252 for per trading day), rho is per 1.00 of rate.  The UI relabels them;
the maths here stays in natural units.

MODELLING TOOL, NOT INVESTMENT ADVICE.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
from scipy import optimize
from scipy import stats as sps

from .paths import draw_normals

__all__ = [
    "Greeks",
    "bsm_price",
    "bsm_greeks",
    "digital_price",
    "binomial_tree_price",
    "trinomial_tree_price",
    "mc_european_price",
    "mc_exotic_price",
    "implied_vol",
    "implied_vol_vector",
    "build_iv_surface",
]

_SQRT2PI = np.sqrt(2.0 * np.pi)


def _norm_pdf(x: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * np.asarray(x) ** 2) / _SQRT2PI


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    return sps.norm.cdf(x)


def _d1_d2(S, K, T, r, q, sigma):
    """Black-Scholes d1/d2 with a floor on ``sigma*sqrt(T)`` to avoid 0/0."""
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.maximum(np.asarray(T, dtype=float), 1e-12)
    sigma = np.maximum(np.asarray(sigma, dtype=float), 1e-12)
    vol_t = np.maximum(sigma * np.sqrt(T), 1e-12)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol_t
    return d1, d1 - vol_t, vol_t


# --------------------------------------------------------------------------
# closed form
# --------------------------------------------------------------------------
def bsm_price(S, K, T, r, q, sigma, kind: str = "call"):
    """Black-Scholes-Merton price of a European option on a dividend payer.

    Math
    ----
    ``C = S e^{-qT} N(d1) - K e^{-rT} N(d2)``,
    ``P = K e^{-rT} N(-d2) - S e^{-qT} N(-d1)``, with
    ``d1 = [ln(S/K) + (r - q + sigma^2/2) T] / (sigma sqrt(T))`` and
    ``d2 = d1 - sigma sqrt(T)``.

    Assumptions
    -----------
    Lognormal terminal price with constant volatility, constant rates,
    continuous frictionless trading, no early exercise, continuous dividend
    yield.  The constant-volatility assumption is the one the market visibly
    rejects -- that rejection is exactly what the implied-vol smile measures.

    Expiry (``T <= 0``) is handled by returning the intrinsic value.
    """
    S_a = np.asarray(S, dtype=float)
    K_a = np.asarray(K, dtype=float)
    T_a = np.asarray(T, dtype=float)
    d1, d2, _ = _d1_d2(S_a, K_a, T_a, r, q, sigma)
    disc_r = np.exp(-r * np.maximum(T_a, 0.0))
    disc_q = np.exp(-q * np.maximum(T_a, 0.0))
    if kind.lower().startswith("c"):
        px = S_a * disc_q * _norm_cdf(d1) - K_a * disc_r * _norm_cdf(d2)
        intrinsic = np.maximum(S_a - K_a, 0.0)
    else:
        px = K_a * disc_r * _norm_cdf(-d2) - S_a * disc_q * _norm_cdf(-d1)
        intrinsic = np.maximum(K_a - S_a, 0.0)
    return np.where(T_a <= 0, intrinsic, px)


@dataclass
class Greeks:
    """Black-Scholes sensitivities in natural units (see module docstring)."""

    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    vanna: float
    volga: float

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


def bsm_greeks(S, K, T, r, q, sigma, kind: str = "call") -> Greeks:
    """Full first- and second-order Black-Scholes Greeks.

    Math
    ----
    ``delta = dV/dS``           call ``e^{-qT} N(d1)``, put ``-e^{-qT} N(-d1)``
    ``gamma = d2V/dS2``         ``e^{-qT} phi(d1) / (S sigma sqrt(T))``
    ``vega  = dV/dsigma``       ``S e^{-qT} phi(d1) sqrt(T)``
    ``theta = dV/dt``           includes carry and discounting terms
    ``rho   = dV/dr``           call ``K T e^{-rT} N(d2)``
    ``vanna = d2V/dS dsigma``   ``-e^{-qT} phi(d1) d2 / sigma``
    ``volga = d2V/dsigma2``     ``vega * d1 d2 / sigma``

    Gamma and vega are identical for calls and puts (put-call parity is linear
    in ``S`` and independent of ``sigma``); vanna and volga likewise.

    Vanna tells you how your delta hedge decays when vol moves -- the reason a
    delta-neutral book bleeds through a vol shock.  Volga is the convexity of
    the position in volatility and is what makes far-OTM options behave like
    long-vol convexity trades.
    """
    S_f = float(np.asarray(S).item()) if np.ndim(S) == 0 else float(np.mean(S))
    K_f = float(np.asarray(K).item()) if np.ndim(K) == 0 else float(np.mean(K))
    T_f = float(T)
    sig = float(sigma)
    is_call = kind.lower().startswith("c")

    if T_f <= 0 or sig <= 0:
        intrinsic = max(S_f - K_f, 0.0) if is_call else max(K_f - S_f, 0.0)
        itm = (S_f > K_f) if is_call else (S_f < K_f)
        return Greeks(
            price=intrinsic,
            delta=(1.0 if is_call else -1.0) if itm else 0.0,
            gamma=0.0, vega=0.0, theta=0.0, rho=0.0, vanna=0.0, volga=0.0,
        )

    d1, d2, vol_t = _d1_d2(S_f, K_f, T_f, r, q, sig)
    d1 = float(d1)
    d2 = float(d2)
    pdf = float(_norm_pdf(d1))
    disc_r = np.exp(-r * T_f)
    disc_q = np.exp(-q * T_f)
    sqrt_t = np.sqrt(T_f)

    price = float(bsm_price(S_f, K_f, T_f, r, q, sig, kind))
    gamma = disc_q * pdf / (S_f * sig * sqrt_t)
    vega = S_f * disc_q * pdf * sqrt_t
    vanna = -disc_q * pdf * d2 / sig
    volga = vega * d1 * d2 / sig
    carry = -S_f * disc_q * pdf * sig / (2.0 * sqrt_t)

    if is_call:
        delta = disc_q * float(_norm_cdf(d1))
        theta = carry - r * K_f * disc_r * float(_norm_cdf(d2)) \
            + q * S_f * disc_q * float(_norm_cdf(d1))
        rho = K_f * T_f * disc_r * float(_norm_cdf(d2))
    else:
        delta = -disc_q * float(_norm_cdf(-d1))
        theta = carry + r * K_f * disc_r * float(_norm_cdf(-d2)) \
            - q * S_f * disc_q * float(_norm_cdf(-d1))
        rho = -K_f * T_f * disc_r * float(_norm_cdf(-d2))

    return Greeks(price=price, delta=float(delta), gamma=float(gamma),
                  vega=float(vega), theta=float(theta), rho=float(rho),
                  vanna=float(vanna), volga=float(volga))


def digital_price(S, K, T, r, q, sigma, kind: str = "call", cash: float = 1.0):
    """Cash-or-nothing digital: pays ``cash`` if it finishes in the money.

    Math
    ----
    ``C_digital = cash * e^{-rT} N(d2)``, ``P_digital = cash * e^{-rT} N(-d2)``.
    ``N(d2)`` is exactly the risk-neutral probability of finishing ITM, so a
    digital is a pure bet on that probability.  Used in the self-test as an
    independent check of the Monte Carlo engine's probability calibration.
    """
    _, d2, _ = _d1_d2(S, K, T, r, q, sigma)
    disc = np.exp(-r * np.maximum(np.asarray(T, dtype=float), 0.0))
    nd = _norm_cdf(d2) if kind.lower().startswith("c") else _norm_cdf(-d2)
    return cash * disc * nd


# --------------------------------------------------------------------------
# lattices (American exercise)
# --------------------------------------------------------------------------
def binomial_tree_price(
    S: float, K: float, T: float, r: float, q: float, sigma: float,
    n_steps: int = 500, kind: str = "call", american: bool = True,
) -> float:
    """Cox-Ross-Rubinstein binomial tree, European or American exercise.

    Math
    ----
    With ``dt = T/n``: ``u = e^{sigma sqrt(dt)}``, ``d = 1/u``, and the
    risk-neutral up-probability ``p = (e^{(r-q)dt} - d) / (u - d)``.  Terminal
    payoffs are rolled back with ``V = e^{-r dt}(p V_up + (1-p) V_dn)``; for an
    American option the continuation value is compared with intrinsic at every
    node and the maximum is taken.

    Convergence is ``O(1/n)`` with a characteristic sawtooth as strikes move
    between nodes; 500-1000 steps is normally enough for 3-4 significant
    figures.  ``p`` outside ``[0,1]`` (possible for huge ``r*dt`` relative to
    ``sigma``) means the lattice is not arbitrage-free -- raise ``n_steps``.

    Assumptions
    -----------
    Same as Black-Scholes plus a discrete exercise grid: an American value from
    an ``n``-step tree can only be exercised at ``n`` dates, so it slightly
    understates the true continuously-exercisable value.
    """
    n = int(max(1, n_steps))
    T = float(max(T, 1e-12))
    dt = T / n
    if sigma <= 0:
        fwd = S * np.exp((r - q) * T)
        intrinsic = max(fwd - K, 0.0) if kind.lower().startswith("c") else max(K - fwd, 0.0)
        return float(np.exp(-r * T) * intrinsic)
    u = np.exp(sigma * np.sqrt(dt))
    d = 1.0 / u
    disc = np.exp(-r * dt)
    p = (np.exp((r - q) * dt) - d) / (u - d)
    p = float(np.clip(p, 0.0, 1.0))

    j = np.arange(n + 1)
    prices = S * (u ** (n - j)) * (d**j)
    if kind.lower().startswith("c"):
        values = np.maximum(prices - K, 0.0)
    else:
        values = np.maximum(K - prices, 0.0)

    for i in range(n - 1, -1, -1):
        values = disc * (p * values[:-1] + (1.0 - p) * values[1:])
        if american:
            j = np.arange(i + 1)
            prices = S * (u ** (i - j)) * (d**j)
            exercise = (prices - K) if kind.lower().startswith("c") else (K - prices)
            values = np.maximum(values, exercise)
    return float(values[0])


def trinomial_tree_price(
    S: float, K: float, T: float, r: float, q: float, sigma: float,
    n_steps: int = 300, kind: str = "call", american: bool = True,
) -> float:
    """Boyle trinomial tree, European or American exercise.

    Math
    ----
    Three branches per node with ``u = e^{sigma sqrt(2 dt)}``, ``m = 1``,
    ``d = 1/u`` and probabilities chosen to match the first two moments::

        a  = e^{(r-q) dt/2},  b = e^{sigma sqrt(dt/2)},  c = e^{-sigma sqrt(dt/2)}
        pu = ((a - c)/(b - c))^2,  pd = ((b - a)/(b - c))^2,  pm = 1 - pu - pd

    The extra branch makes the lattice converge more smoothly than the binomial
    (no sawtooth) for the same node count, so fewer steps are needed for the
    same accuracy on American options.
    """
    n = int(max(1, n_steps))
    T = float(max(T, 1e-12))
    dt = T / n
    if sigma <= 0:
        return binomial_tree_price(S, K, T, r, q, sigma, n, kind, american)
    u = np.exp(sigma * np.sqrt(2.0 * dt))
    d = 1.0 / u
    a = np.exp((r - q) * dt / 2.0)
    b = np.exp(sigma * np.sqrt(dt / 2.0))
    c = np.exp(-sigma * np.sqrt(dt / 2.0))
    pu = ((a - c) / (b - c)) ** 2
    pd = ((b - a) / (b - c)) ** 2
    pm = 1.0 - pu - pd
    pu, pd, pm = float(pu), float(pd), float(max(pm, 0.0))
    disc = np.exp(-r * dt)
    is_call = kind.lower().startswith("c")

    j = np.arange(-n, n + 1)
    prices = S * (u ** np.maximum(j, 0)) * (d ** np.maximum(-j, 0))
    values = np.maximum(prices - K, 0.0) if is_call else np.maximum(K - prices, 0.0)

    for i in range(n - 1, -1, -1):
        values = disc * (pu * values[2:] + pm * values[1:-1] + pd * values[:-2])
        if american:
            j = np.arange(-i, i + 1)
            prices = S * (u ** np.maximum(j, 0)) * (d ** np.maximum(-j, 0))
            exercise = (prices - K) if is_call else (K - prices)
            values = np.maximum(values, exercise)
    return float(values[0])


# --------------------------------------------------------------------------
# Monte Carlo pricing
# --------------------------------------------------------------------------
@dataclass
class MCPriceResult:
    """Monte Carlo price with its error bars and the closed-form benchmark."""

    price: float
    stderr: float
    analytic: Optional[float]
    error: Optional[float]
    n_paths: int
    antithetic: bool
    control_variate: bool
    cv_beta: Optional[float] = None

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


def mc_european_price(
    S: float, K: float, T: float, r: float, q: float, sigma: float,
    n_paths: int = 200_000, kind: str = "call",
    antithetic: bool = True, control_variate: bool = True,
    seed: Optional[int] = None,
) -> MCPriceResult:
    """Monte Carlo European price with antithetic and control variates.

    Math
    ----
    Terminal prices are drawn exactly (one step, no discretisation error):

        ``S_T = S exp((r - q - sigma^2/2) T + sigma sqrt(T) Z)``

    and the estimator is ``e^{-rT} E[payoff]``.

    *Antithetic variates* pair each ``Z`` with ``-Z``.  For a monotone payoff
    the pair is negatively correlated, which cuts variance at no extra cost.

    *Control variate*: ``S_T`` has a known expectation ``S e^{(r-q)T}``, so

        ``Y_cv = Y - beta (S_T - E[S_T])``,  ``beta = Cov(Y, S_T)/Var(S_T)``

    is unbiased and has minimum variance at the optimal ``beta``.  Estimating
    ``beta`` from the same sample introduces an O(1/n) bias that is negligible
    at these path counts.  For a European call the correlation is very high, so
    this typically removes 80-95% of the standard error.

    ``stderr`` is the standard error of the (possibly adjusted) estimator; the
    reported ``error`` is the signed difference against the closed form, which
    is what the self-test asserts on.
    """
    rng = np.random.default_rng(seed)
    n = int(max(2, n_paths))
    T = float(max(T, 1e-12))
    z = draw_normals(rng, n, 1, antithetic).ravel()
    drift = (r - q - 0.5 * sigma * sigma) * T
    ST = S * np.exp(drift + sigma * np.sqrt(T) * z)
    disc = np.exp(-r * T)
    payoff = np.maximum(ST - K, 0.0) if kind.lower().startswith("c") else np.maximum(K - ST, 0.0)
    Y = disc * payoff

    beta = None
    if control_variate:
        expected_ST = S * np.exp((r - q) * T)
        var_st = float(np.var(ST, ddof=1))
        if var_st > 0:
            beta = float(np.cov(Y, ST, ddof=1)[0, 1] / var_st)
            Y = Y - beta * (ST - expected_ST)

    price = float(Y.mean())
    stderr = float(Y.std(ddof=1) / np.sqrt(n))
    analytic = float(bsm_price(S, K, T, r, q, sigma, kind))
    return MCPriceResult(
        price=price, stderr=stderr, analytic=analytic, error=price - analytic,
        n_paths=n, antithetic=antithetic, control_variate=control_variate,
        cv_beta=beta,
    )


#: Payoff styles supported by :func:`mc_exotic_price`.
EXOTIC_STYLES: Tuple[str, ...] = (
    "european", "asian_arithmetic", "asian_geometric",
    "barrier_up_out", "barrier_up_in", "barrier_down_out", "barrier_down_in",
    "lookback_floating", "lookback_fixed", "digital",
)


def mc_exotic_price(
    S: float, K: float, T: float, r: float, q: float, sigma: float,
    style: str = "asian_arithmetic", kind: str = "call",
    n_paths: int = 100_000, n_steps: int = 252,
    barrier: Optional[float] = None, cash: float = 1.0,
    antithetic: bool = True, seed: Optional[int] = None,
) -> MCPriceResult:
    """Monte Carlo price of a path-dependent payoff under risk-neutral GBM.

    Payoffs
    -------
    ``asian_arithmetic``  average of the monitored prices replaces ``S_T``
    ``asian_geometric``   geometric average (has a closed form; useful control)
    ``barrier_*_out``     pays the vanilla payoff unless the barrier is touched
    ``barrier_*_in``      pays only if the barrier is touched
    ``lookback_floating`` call ``S_T - min S``, put ``max S - S_T``
    ``lookback_fixed``    call ``max(max S - K, 0)``, put ``max(K - min S, 0)``
    ``digital``           ``cash`` if ``S_T`` finishes ITM
    ``european``          vanilla, priced on the same grid as a sanity check

    Assumptions
    -----------
    Risk-neutral GBM with constant volatility, and **discrete monitoring on the
    ``n_steps`` grid**.  Barriers and lookbacks are the payoffs most sensitive
    to this: discretely monitored knock-outs are worth more than continuously
    monitored ones because the barrier can be crossed and missed between
    observations, and the gap shrinks only like ``sqrt(dt)``.  Raise
    ``n_steps`` (or apply a Broadie-Glasserman-Kou barrier shift) when the
    barrier is close to spot.

    ``analytic`` is filled in only for the styles with a closed form
    (``european``, ``digital``), and is ``None`` otherwise.
    """
    rng = np.random.default_rng(seed)
    n = int(max(2, n_paths))
    m = int(max(1, n_steps))
    T = float(max(T, 1e-12))
    dt = T / m
    is_call = kind.lower().startswith("c")

    z = draw_normals(rng, n, m, antithetic)
    z *= sigma * np.sqrt(dt)
    z += (r - q - 0.5 * sigma * sigma) * dt
    log_paths = np.cumsum(z, axis=1)
    paths = S * np.exp(log_paths)           # (n, m) -- excludes t=0
    ST = paths[:, -1]
    disc = np.exp(-r * T)

    if style == "european":
        payoff = np.maximum(ST - K, 0.0) if is_call else np.maximum(K - ST, 0.0)
    elif style == "asian_arithmetic":
        avg = paths.mean(axis=1)
        payoff = np.maximum(avg - K, 0.0) if is_call else np.maximum(K - avg, 0.0)
    elif style == "asian_geometric":
        gavg = np.exp(log_paths.mean(axis=1)) * S
        payoff = np.maximum(gavg - K, 0.0) if is_call else np.maximum(K - gavg, 0.0)
    elif style.startswith("barrier"):
        if barrier is None:
            raise ValueError("barrier styles require a barrier level")
        if "up" in style:
            touched = paths.max(axis=1) >= barrier
        else:
            touched = paths.min(axis=1) <= barrier
        vanilla = np.maximum(ST - K, 0.0) if is_call else np.maximum(K - ST, 0.0)
        alive = touched if style.endswith("_in") else ~touched
        payoff = np.where(alive, vanilla, 0.0)
    elif style == "lookback_floating":
        payoff = (ST - paths.min(axis=1)) if is_call else (paths.max(axis=1) - ST)
    elif style == "lookback_fixed":
        if is_call:
            payoff = np.maximum(paths.max(axis=1) - K, 0.0)
        else:
            payoff = np.maximum(K - paths.min(axis=1), 0.0)
    elif style == "digital":
        payoff = np.where(ST > K if is_call else ST < K, cash, 0.0)
    else:
        raise ValueError(f"unknown exotic style {style!r}; known: {EXOTIC_STYLES}")

    Y = disc * payoff
    price = float(Y.mean())
    stderr = float(Y.std(ddof=1) / np.sqrt(n))

    analytic: Optional[float] = None
    if style == "european":
        analytic = float(bsm_price(S, K, T, r, q, sigma, kind))
    elif style == "digital":
        analytic = float(digital_price(S, K, T, r, q, sigma, kind, cash))
    return MCPriceResult(
        price=price, stderr=stderr, analytic=analytic,
        error=None if analytic is None else price - analytic,
        n_paths=n, antithetic=antithetic, control_variate=False,
    )


# --------------------------------------------------------------------------
# implied volatility
# --------------------------------------------------------------------------
#: Below this vega the quote carries no usable volatility information: a full
#: 1-vol-point move would change the price by less than 1e-10, far under any
#: real quote's precision, so the inverse problem is numerically ill-posed.
MIN_IDENTIFIABLE_VEGA = 1e-8


def implied_vol(
    price: float, S: float, K: float, T: float, r: float, q: float,
    kind: str = "call", lo: float = 1e-4, hi: float = 5.0,
) -> float:
    """Implied volatility by Brent's method, with a Newton polish.

    Method
    ------
    The BSM price is strictly increasing in ``sigma`` (vega > 0), so the root
    is unique and bracketed by ``[lo, hi]`` whenever the quote respects the
    no-arbitrage bounds.  Brent's method is used because it is bracketed
    (cannot diverge) and superlinear; a couple of Newton steps using vega then
    polish the answer.

    Returns ``nan``, rather than a misleading number, in three cases:

    1. **Arbitrage violation** -- the quote is below intrinsic or above the
       maximum value.  Bounds checked are
       ``max(0, S e^{-qT} - K e^{-rT}) <= price <= S e^{-qT}`` for a call and
       ``max(0, K e^{-rT} - S e^{-qT}) <= price <= K e^{-rT}`` for a put.
       Typically a stale or crossed market, or a deep-ITM American quote whose
       early-exercise premium a European model cannot explain.
    2. **No bracket** -- no volatility in ``[lo, hi]`` reproduces the price.
    3. **Unidentifiable** -- vega at the solution is below
       :data:`MIN_IDENTIFIABLE_VEGA`.  This is the important one: a deep-ITM
       short-dated option is worth its intrinsic value to forty decimal places,
       so *every* volatility produces the identical float64 price and the root
       finder converges on whichever bracket end it starts from.  Reporting
       that as a volatility would put a spurious near-zero point on the smile;
       reporting ``nan`` says truthfully that the quote contains no vol
       information.  Quotes above the threshold invert to ~1e-12 accuracy.
    """
    price = float(price)
    if not np.isfinite(price) or price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return float("nan")
    disc_r = np.exp(-r * T)
    disc_q = np.exp(-q * T)
    if kind.lower().startswith("c"):
        lower, upper = max(0.0, S * disc_q - K * disc_r), S * disc_q
    else:
        lower, upper = max(0.0, K * disc_r - S * disc_q), K * disc_r
    if price < lower - 1e-10 or price > upper + 1e-10:
        return float("nan")

    def f(sig: float) -> float:
        return float(bsm_price(S, K, T, r, q, sig, kind)) - price

    try:
        f_lo, f_hi = f(lo), f(hi)
        if f_lo * f_hi > 0:
            return float("nan")
        sig = float(optimize.brentq(f, lo, hi, xtol=1e-10, rtol=1e-12, maxiter=200))
    except (ValueError, RuntimeError):
        return float("nan")

    for _ in range(2):  # Newton polish
        g = bsm_greeks(S, K, T, r, q, sig, kind)
        if g.vega <= 1e-12:
            break
        step = (g.price - price) / g.vega
        new = sig - step
        if not (lo <= new <= hi):
            break
        sig = new

    if bsm_greeks(S, K, T, r, q, sig, kind).vega < MIN_IDENTIFIABLE_VEGA:
        return float("nan")
    return float(sig)


def implied_vol_vector(
    prices: Sequence[float], S: float, strikes: Sequence[float],
    T: Sequence[float] | float, r: float, q: float,
    kinds: Sequence[str] | str = "call",
) -> np.ndarray:
    """Solve implied vol for a whole quote vector, returning ``nan`` on failure.

    Loops over :func:`implied_vol` -- the root-find is scalar and cheap, and a
    per-quote loop keeps one bad quote from poisoning the rest of the chain.
    """
    strikes = np.asarray(strikes, dtype=float)
    n = strikes.size
    Ts = np.broadcast_to(np.asarray(T, dtype=float), (n,))
    ks = [kinds] * n if isinstance(kinds, str) else list(kinds)
    px = np.asarray(prices, dtype=float)
    out = np.empty(n, dtype=float)
    for i in range(n):
        out[i] = implied_vol(px[i], S, strikes[i], Ts[i], r, q, ks[i])
    return out


def build_iv_surface(
    chain, S: float, r: float = 0.04, q: float = 0.0,
    moneyness_range: Tuple[float, float] = (0.6, 1.4),
    min_points: int = 4,
    require_two_sided: bool = True,
):
    """Turn a raw option chain into a tidy implied-vol surface table.

    ``chain`` must be a DataFrame with columns ``strike``, ``expiry_years``,
    ``mid`` (or ``lastPrice``) and ``kind``.  Rows are filtered to the given
    moneyness window and to positive prices, implied vol is solved per row, and
    failures are dropped.

    Illiquid contracts are screened out before inverting (see the code): a
    zero-bid quote has no two-sided market and inverts to a meaningless
    three-digit implied vol that would dominate the smile.  Set
    ``require_two_sided=False`` to keep them.

    Returns ``(tidy_df, pivot_df)`` where ``pivot_df`` has expiries as rows and
    strikes as columns -- the grid the 3D surface plot consumes.  Expiries with
    fewer than ``min_points`` solvable quotes are dropped because a two-point
    "smile" is noise, not structure.

    Caveat: exchange-listed US single-stock options are American, so their IVs
    contain an early-exercise premium a European solver attributes to
    volatility.  The distortion is small for OTM calls and short-dated
    contracts, larger for deep ITM puts.
    """
    import pandas as pd

    if chain is None or len(chain) == 0:
        return pd.DataFrame(), pd.DataFrame()
    df = chain.copy()
    price_col = "mid" if "mid" in df.columns else "lastPrice"
    if price_col not in df.columns:
        return pd.DataFrame(), pd.DataFrame()
    df = df[np.isfinite(df[price_col]) & (df[price_col] > 0)]
    df = df[df["expiry_years"] > 1e-4]
    lo, hi = moneyness_range
    df = df[(df["strike"] >= lo * S) & (df["strike"] <= hi * S)]

    # Liquidity screen.  A contract quoted with no bid has no real two-sided
    # market: its "price" is a stale last trade or a one-sided ask, and
    # inverting it produces implied vols in the hundreds of percent that
    # dominate the smile and wreck the surface.  Requiring a positive bid, and
    # some open interest where the field is present, keeps only contracts a
    # trader could actually transact in.  This is a *display* filter -- the raw
    # chain is untouched.
    if require_two_sided and "bid" in df.columns:
        bid = pd.to_numeric(df["bid"], errors="coerce")
        if (bid > 0).sum() >= min_points:
            df = df[bid > 0]
    if "openInterest" in df.columns:
        oi = pd.to_numeric(df["openInterest"], errors="coerce").fillna(0)
        if (oi > 0).sum() >= min_points:
            df = df[oi > 0]
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = df.reset_index(drop=True)
    df["iv"] = implied_vol_vector(
        df[price_col].to_numpy(), S, df["strike"].to_numpy(),
        df["expiry_years"].to_numpy(), r, q,
        df["kind"].tolist() if "kind" in df.columns else "call",
    )
    df = df[np.isfinite(df["iv"]) & (df["iv"] > 1e-3) & (df["iv"] < 4.0)]
    if df.empty:
        return df, pd.DataFrame()
    df["moneyness"] = df["strike"] / float(S)

    counts = df.groupby("expiry_years")["iv"].transform("size")
    df = df[counts >= min_points]
    if df.empty:
        return df, pd.DataFrame()
    pivot = df.pivot_table(
        index="expiry_years", columns="strike", values="iv", aggfunc="mean"
    )
    return df, pivot
