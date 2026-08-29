"""
Headless correctness suite for the whole model stack (``--selftest``).

Runs every model against synthetic and cached data with no GUI, asserts the
properties that must hold, prints a pass/fail table and exits non-zero on any
failure.  The assertions are chosen to be *diagnostic*, not decorative: each
one fails for a specific, identifiable reason.

Three kinds of check appear here:

* **Analytic identities** -- exact relationships that must hold to machine
  precision (put-call parity, barrier in + out = vanilla, Greeks against
  finite differences).  Tolerances are tight.
* **Statistical convergence** -- Monte Carlo estimates against closed forms,
  checked against their own standard error (a 4-sigma band, so the suite fails
  spuriously about once in 16,000 runs per check rather than flapping).
* **Estimator round trips** -- simulate with known parameters, calibrate, and
  confirm the parameters come back.  Tolerances here are wide because the
  estimators are genuinely noisy on finite samples.

Every check uses a fixed seed, so a failure is reproducible.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import numpy as np

from .engine import SimRequest, SimulationEngine
from .models import calibration as cal
from .models import multiasset as ma
from .models import paths as pm
from .models import pricing as pr
from .models import risk as rk
from .models import stats as st
from .models import technicals as tech

__all__ = ["run_selftest", "Check"]

TRADING_DAYS = 252.0
DT = 1.0 / TRADING_DAYS


@dataclass
class Check:
    """One assertion and its outcome."""

    group: str
    name: str
    passed: bool
    detail: str
    elapsed: float


class _Runner:
    """Collects checks, catching exceptions as failures."""

    def __init__(self, verbose: bool = False) -> None:
        self.checks: List[Check] = []
        self.verbose = verbose

    def check(self, group: str, name: str, fn: Callable[[], Tuple[bool, str]]) -> None:
        t0 = time.perf_counter()
        try:
            ok, detail = fn()
        except Exception as exc:
            ok = False
            detail = f"{type(exc).__name__}: {exc}"
            if self.verbose:
                traceback.print_exc()
        self.checks.append(
            Check(group, name, bool(ok), str(detail), time.perf_counter() - t0)
        )

    @property
    def failures(self) -> List[Check]:
        return [c for c in self.checks if not c.passed]


def _rel(a: float, b: float) -> float:
    """Relative error, falling back to absolute when the reference is ~0."""
    denom = max(abs(b), 1e-12)
    return abs(a - b) / denom if abs(b) > 1e-9 else abs(a - b)


# ==========================================================================
# 1. path models
# ==========================================================================
def _register_path_models(r: _Runner) -> None:
    g = "path models"

    def gbm_lognormal_moments():
        """Terminal distribution must match the analytic lognormal moments."""
        s0, mu, sigma, T = 100.0, 0.07, 0.25, 1.0
        n = 400_000
        p = pm.simulate_gbm(s0, 252, n, DT, np.random.default_rng(1), mu, sigma)
        term = p[:, -1]
        exp_mean = s0 * np.exp(mu * T)
        exp_var = s0**2 * np.exp(2 * mu * T) * (np.exp(sigma**2 * T) - 1.0)
        se = np.sqrt(exp_var / n)
        mean_ok = abs(term.mean() - exp_mean) < 4 * se
        var_ok = _rel(term.var(), exp_var) < 0.02
        # log-space moments are exact, so they can be checked much tighter
        lg = np.log(term / s0)
        lm_ok = abs(lg.mean() - (mu - 0.5 * sigma**2) * T) < 4 * sigma / np.sqrt(n)
        lv_ok = _rel(lg.var(), sigma**2 * T) < 0.02
        return (mean_ok and var_ok and lm_ok and lv_ok,
                f"E[S_T]={term.mean():.4f} vs {exp_mean:.4f}; "
                f"Var rel err {_rel(term.var(), exp_var):.4f}; "
                f"E[logR]={lg.mean():.5f} vs {(mu-0.5*sigma**2)*T:.5f}")

    def gbm_exact_first_step():
        """One step of GBM is exact: no discretisation bias at any dt."""
        s0, mu, sigma = 100.0, 0.05, 0.3
        for dt in (1 / 252, 1 / 12, 1.0):
            p = pm.simulate_gbm(s0, 1, 200_000, dt, np.random.default_rng(2), mu, sigma)
            lg = np.log(p[:, -1] / s0)
            expected = (mu - 0.5 * sigma**2) * dt
            se = sigma * np.sqrt(dt) / np.sqrt(200_000)
            if abs(lg.mean() - expected) > 4 * se:
                return False, f"dt={dt}: mean {lg.mean():.6f} vs {expected:.6f}"
        return True, "unbiased at dt = 1/252, 1/12 and 1.0"

    def antithetic_reduces_variance():
        """Antithetic pairing must lower the variance of the mean estimator."""
        s0, mu, sigma, n = 100.0, 0.08, 0.25, 40_000
        trials_plain, trials_anti = [], []
        for k in range(40):
            a = pm.simulate_gbm(s0, 63, n, DT, np.random.default_rng(100 + k),
                                mu, sigma, antithetic=False)
            b = pm.simulate_gbm(s0, 63, n, DT, np.random.default_rng(500 + k),
                                mu, sigma, antithetic=True)
            trials_plain.append(a[:, -1].mean())
            trials_anti.append(b[:, -1].mean())
        v_plain = float(np.var(trials_plain, ddof=1))
        v_anti = float(np.var(trials_anti, ddof=1))
        return (v_anti < v_plain,
                f"variance of the mean: plain {v_plain:.3e} -> antithetic "
                f"{v_anti:.3e} ({v_plain/max(v_anti,1e-300):.1f}x reduction)")

    def student_t_variance_and_tails():
        """Student-t keeps GBM's variance but adds kurtosis."""
        nu, sigma = 5.0, 0.25
        n = 200_000
        rng = np.random.default_rng(3)
        pt = pm.simulate_student_t(100.0, 1, n, DT, rng, 0.0, sigma, nu)
        pg = pm.simulate_gbm(100.0, 1, n, DT, np.random.default_rng(4), 0.0, sigma)
        rt = np.log(pt[:, -1] / 100.0)
        rg = np.log(pg[:, -1] / 100.0)
        var_ok = _rel(rt.var(), rg.var()) < 0.05
        from scipy import stats as sps
        k_t, k_g = sps.kurtosis(rt), sps.kurtosis(rg)
        theoretical = 6.0 / (nu - 4.0)
        return (var_ok and k_t > k_g + 1.0,
                f"var ratio {rt.var()/rg.var():.4f}; excess kurtosis t={k_t:.2f} "
                f"(theory {theoretical:.2f}) vs normal {k_g:.3f}")

    def merton_drift_compensated():
        """The jump compensator must preserve E[S_T] = S0 exp(mu T)."""
        s0, mu, T, n = 100.0, 0.06, 1.0, 400_000
        p = pm.simulate_merton(s0, 252, n, DT, np.random.default_rng(5), mu,
                               0.15, lam=3.0, jump_mean=-0.05, jump_std=0.08)
        term = p[:, -1]
        expected = s0 * np.exp(mu * T)
        se = term.std(ddof=1) / np.sqrt(n)
        return (abs(term.mean() - expected) < 4 * se,
                f"E[S_T]={term.mean():.4f} vs {expected:.4f} (4 se = {4*se:.4f})")

    def merton_adds_negative_skew():
        """Negative mean jumps must produce a left-skewed terminal distribution."""
        from scipy import stats as sps
        p = pm.simulate_merton(100.0, 252, 200_000, DT, np.random.default_rng(6),
                               0.05, 0.15, lam=4.0, jump_mean=-0.06, jump_std=0.05)
        g = pm.simulate_gbm(100.0, 252, 200_000, DT, np.random.default_rng(7),
                            0.05, 0.20)
        sk_m = sps.skew(np.log(p[:, -1]))
        sk_g = sps.skew(np.log(g[:, -1]))
        return (sk_m < sk_g - 0.05,
                f"log-terminal skew: merton {sk_m:.3f} vs gbm {sk_g:.3f}")

    def heston_mean_and_variance():
        """Heston preserves the drift and reverts variance to theta."""
        s0, mu, theta, T, n = 100.0, 0.05, 0.04, 1.0, 200_000
        p = pm.simulate_heston(s0, 252, n, DT, np.random.default_rng(8), mu,
                               v0=theta, kappa=4.0, theta=theta, xi=0.4, rho=-0.6)
        term = p[:, -1]
        expected = s0 * np.exp(mu * T)
        se = term.std(ddof=1) / np.sqrt(n)
        mean_ok = abs(term.mean() - expected) < 5 * se
        realised_var = float(np.var(np.log(term / s0)))
        var_ok = _rel(realised_var, theta * T) < 0.08
        return (mean_ok and var_ok,
                f"E[S_T]={term.mean():.3f} vs {expected:.3f}; "
                f"Var[log R]={realised_var:.5f} vs theta*T={theta*T:.5f}")

    def heston_leverage_skew():
        """Negative rho must generate negative skew (the equity smirk)."""
        from scipy import stats as sps
        common = dict(v0=0.04, kappa=3.0, theta=0.04, xi=0.6)
        neg = pm.simulate_heston(100.0, 252, 120_000, DT,
                                 np.random.default_rng(9), 0.05, rho=-0.8, **common)
        pos = pm.simulate_heston(100.0, 252, 120_000, DT,
                                 np.random.default_rng(10), 0.05, rho=+0.8, **common)
        s_neg = sps.skew(np.log(neg[:, -1]))
        s_pos = sps.skew(np.log(pos[:, -1]))
        return (s_neg < s_pos, f"skew rho=-0.8: {s_neg:.3f} < rho=+0.8: {s_pos:.3f}")

    def garch_long_run_vol():
        """Realised vol of long GARCH paths must match the long-run level."""
        omega, alpha, beta = 3e-6, 0.08, 0.90
        lr_var = omega / (1 - alpha - beta)
        target = np.sqrt(lr_var / DT)
        p = pm.simulate_garch(100.0, 2520, 2_000, DT, np.random.default_rng(11),
                              mu=0.0, omega=omega, alpha=alpha, beta=beta)
        r = np.diff(np.log(p), axis=1)
        realised = float(r.std()) / np.sqrt(DT)
        return (_rel(realised, target) < 0.06,
                f"realised annualised vol {realised:.4f} vs long-run {target:.4f}")

    def garch_clusters_volatility():
        """Squared GARCH returns must be autocorrelated; GBM's must not be."""
        p = pm.simulate_garch(100.0, 4000, 1, DT, np.random.default_rng(12),
                              mu=0.0, omega=3e-6, alpha=0.10, beta=0.87)
        r = np.diff(np.log(p[0]))
        g = np.diff(np.log(pm.simulate_gbm(100.0, 4000, 1, DT,
                                           np.random.default_rng(13), 0.0, 0.2)[0]))
        a_g, band = st.acf(r**2, 10)
        b_g, _ = st.acf(g**2, 10)
        return (a_g[1] > 3 * band and abs(b_g[1]) < 3 * band,
                f"ACF(1) of r^2: garch {a_g[1]:.4f}, gbm {b_g[1]:.4f}, band {band:.4f}")

    def bootstrap_matches_empirical_moments():
        """IID bootstrap must reproduce the empirical per-step moments."""
        rng = np.random.default_rng(14)
        hist = np.concatenate([rng.normal(0.0004, 0.01, 1500),
                               rng.normal(-0.02, 0.04, 60)])
        p = pm.simulate_bootstrap(100.0, 252, 100_000, DT,
                                  np.random.default_rng(15), returns=hist)
        lg = np.log(p[:, -1] / 100.0)
        exp_mean, exp_var = hist.mean() * 252, hist.var() * 252
        return (_rel(lg.mean(), exp_mean) < 0.05 and _rel(lg.var(), exp_var) < 0.05,
                f"mean {lg.mean():.5f} vs {exp_mean:.5f}; "
                f"var {lg.var():.6f} vs {exp_var:.6f}")

    def block_bootstrap_preserves_autocorrelation():
        """Block resampling must keep short-lag dependence the iid one destroys."""
        rng = np.random.default_rng(16)
        # AR(1) returns with strong positive autocorrelation
        e = rng.normal(0, 0.01, 3000)
        hist = np.zeros(3000)
        for i in range(1, 3000):
            hist[i] = 0.45 * hist[i - 1] + e[i]
        target = st.acf(hist, 3)[0][1]
        blk = pm.simulate_block_bootstrap(100.0, 252, 400, DT,
                                          np.random.default_rng(17),
                                          returns=hist, block=40)
        iid = pm.simulate_bootstrap(100.0, 252, 400, DT,
                                    np.random.default_rng(18), returns=hist)
        acf_blk = np.mean([st.acf(np.diff(np.log(row)), 3)[0][1] for row in blk])
        acf_iid = np.mean([st.acf(np.diff(np.log(row)), 3)[0][1] for row in iid])
        return (acf_blk > 0.5 * target and abs(acf_iid) < 0.1,
                f"historical ACF(1)={target:.3f}; block {acf_blk:.3f}, "
                f"iid {acf_iid:.3f}")

    def all_models_produce_valid_paths():
        """No model may emit non-positive, nan or wrongly shaped output."""
        rng = np.random.default_rng(19)
        hist = rng.standard_normal(1000) * 0.012
        bad = []
        for model in pm.MODEL_REGISTRY:
            prm = pm.default_params(model)
            if model in pm.HISTORY_MODELS:
                prm["returns"] = hist
            p = pm.simulate_paths(model, 100.0, 60, 512, DT,
                                  np.random.default_rng(20), prm, antithetic=True)
            if p.shape != (512, 61):
                bad.append(f"{model}: shape {p.shape}")
            elif not np.all(np.isfinite(p)):
                bad.append(f"{model}: non-finite values")
            elif not np.all(p > 0):
                bad.append(f"{model}: non-positive prices")
            elif not np.allclose(p[:, 0], 100.0):
                bad.append(f"{model}: column 0 is not the spot price")
        return (not bad, "; ".join(bad) if bad
                else f"all {len(pm.MODEL_REGISTRY)} models: shape, positivity, S0 ok")

    r.check(g, "GBM matches lognormal moments", gbm_lognormal_moments)
    r.check(g, "GBM exact at any step size", gbm_exact_first_step)
    r.check(g, "antithetic cuts estimator variance", antithetic_reduces_variance)
    r.check(g, "Student-t: same var, fatter tails", student_t_variance_and_tails)
    r.check(g, "Merton drift compensator", merton_drift_compensated)
    r.check(g, "Merton produces negative skew", merton_adds_negative_skew)
    r.check(g, "Heston mean + variance reversion", heston_mean_and_variance)
    r.check(g, "Heston leverage effect (rho<0)", heston_leverage_skew)
    r.check(g, "GARCH long-run volatility", garch_long_run_vol)
    r.check(g, "GARCH clusters volatility", garch_clusters_volatility)
    r.check(g, "bootstrap matches empirical moments",
            bootstrap_matches_empirical_moments)
    r.check(g, "block bootstrap keeps autocorrelation",
            block_bootstrap_preserves_autocorrelation)
    r.check(g, "all models emit valid paths", all_models_produce_valid_paths)


# ==========================================================================
# 2. pricing
# ==========================================================================
def _register_pricing(r: _Runner) -> None:
    g = "pricing"
    S, K, T, rf, q, sig = 100.0, 105.0, 0.75, 0.045, 0.015, 0.28

    def put_call_parity():
        """C - P = S e^{-qT} - K e^{-rT} must hold to machine precision."""
        c = float(pr.bsm_price(S, K, T, rf, q, sig, "call"))
        p = float(pr.bsm_price(S, K, T, rf, q, sig, "put"))
        lhs = c - p
        rhs = S * np.exp(-q * T) - K * np.exp(-rf * T)
        return abs(lhs - rhs) < 1e-10, f"C-P={lhs:.10f} vs S e^-qT - K e^-rT={rhs:.10f}"

    def greeks_vs_finite_difference():
        """Every analytic Greek must match a central finite difference."""
        worst_name, worst = "", 0.0
        for kind in ("call", "put"):
            gr = pr.bsm_greeks(S, K, T, rf, q, sig, kind).as_dict()
            hS, hv, hT, hr = 1e-3, 1e-4, 1e-5, 1e-6
            px = lambda s=S, k=K, t=T, rr=rf, qq=q, v=sig: float(
                pr.bsm_price(s, k, t, rr, qq, v, kind))
            fd = {
                "delta": (px(s=S + hS) - px(s=S - hS)) / (2 * hS),
                "gamma": (px(s=S + hS) - 2 * px() + px(s=S - hS)) / hS**2,
                "vega": (px(v=sig + hv) - px(v=sig - hv)) / (2 * hv),
                "theta": -(px(t=T + hT) - px(t=T - hT)) / (2 * hT),
                "rho": (px(rr=rf + hr) - px(rr=rf - hr)) / (2 * hr),
                "vanna": (pr.bsm_greeks(S, K, T, rf, q, sig + hv, kind).delta
                          - pr.bsm_greeks(S, K, T, rf, q, sig - hv, kind).delta) / (2 * hv),
                "volga": (px(v=sig + hv) - 2 * px() + px(v=sig - hv)) / hv**2,
            }
            for name, val in fd.items():
                err = _rel(gr[name], val)
                if err > worst:
                    worst, worst_name = err, f"{kind}.{name}"
        return worst < 2e-4, f"worst relative error {worst:.2e} on {worst_name}"

    def binomial_converges_to_bsm():
        """CRR European price must converge to Black-Scholes as steps rise."""
        errs = []
        for n in (100, 400, 1600):
            b = pr.binomial_tree_price(S, K, T, rf, q, sig, n, "call", american=False)
            errs.append(abs(b - float(pr.bsm_price(S, K, T, rf, q, sig, "call"))))
        return (errs[-1] < 0.01 and errs[-1] < errs[0],
                f"|error| at 100/400/1600 steps: "
                + " -> ".join(f"{e:.5f}" for e in errs))

    def trinomial_converges_to_bsm():
        """Boyle trinomial European price must converge to Black-Scholes."""
        analytic = float(pr.bsm_price(S, K, T, rf, q, sig, "put"))
        v = pr.trinomial_tree_price(S, K, T, rf, q, sig, 800, "put", american=False)
        return abs(v - analytic) < 0.01, f"trinomial {v:.5f} vs BSM {analytic:.5f}"

    def american_premium_is_nonnegative():
        """American value >= European value, strictly so for an ITM put."""
        eu = pr.binomial_tree_price(S, 115.0, T, rf, q, sig, 800, "put", False)
        am = pr.binomial_tree_price(S, 115.0, T, rf, q, sig, 800, "put", True)
        eu_c = pr.binomial_tree_price(S, K, T, rf, 0.0, sig, 800, "call", False)
        am_c = pr.binomial_tree_price(S, K, T, rf, 0.0, sig, 800, "call", True)
        return (am > eu and abs(am_c - eu_c) < 5e-3,
                f"put: American {am:.4f} > European {eu:.4f} "
                f"(premium {am-eu:.4f}); zero-dividend call premium "
                f"{am_c-eu_c:.2e} ~ 0 as theory requires")

    def mc_european_within_error_bars():
        """MC price must agree with BSM inside four standard errors."""
        res = pr.mc_european_price(S, K, T, rf, q, sig, 400_000, "call",
                                   antithetic=True, control_variate=True, seed=21)
        return (abs(res.error) < 4 * res.stderr,
                f"MC {res.price:.5f} vs BSM {res.analytic:.5f}, "
                f"error {res.error:+.5f}, 4 se = {4*res.stderr:.5f}")

    def control_variate_reduces_error():
        """The S_T control variate must shrink the standard error materially."""
        plain = pr.mc_european_price(S, K, T, rf, q, sig, 200_000, "call",
                                     antithetic=False, control_variate=False, seed=22)
        cv = pr.mc_european_price(S, K, T, rf, q, sig, 200_000, "call",
                                  antithetic=False, control_variate=True, seed=22)
        ratio = plain.stderr / max(cv.stderr, 1e-15)
        return (ratio > 1.5, f"stderr {plain.stderr:.5f} -> {cv.stderr:.5f} "
                             f"({ratio:.1f}x tighter, beta={cv.cv_beta:.3f})")

    def digital_matches_closed_form():
        """MC digital price must match cash * e^{-rT} N(d2)."""
        res = pr.mc_exotic_price(S, K, T, rf, q, sig, "digital", "call",
                                 200_000, 1, seed=23)
        return (abs(res.error) < 4 * res.stderr,
                f"MC {res.price:.5f} vs closed form {res.analytic:.5f} "
                f"(4 se = {4*res.stderr:.5f})")

    def barrier_in_plus_out_equals_vanilla():
        """Knock-in + knock-out = vanilla, exactly, on the same path set."""
        kw = dict(n_paths=60_000, n_steps=126, barrier=118.0, seed=24)
        ki = pr.mc_exotic_price(S, K, T, rf, q, sig, "barrier_up_in", "call", **kw)
        ko = pr.mc_exotic_price(S, K, T, rf, q, sig, "barrier_up_out", "call", **kw)
        eu = pr.mc_exotic_price(S, K, T, rf, q, sig, "european", "call",
                                n_paths=60_000, n_steps=126, seed=24)
        return (abs(ki.price + ko.price - eu.price) < 1e-8,
                f"in {ki.price:.5f} + out {ko.price:.5f} = {ki.price+ko.price:.5f} "
                f"vs vanilla {eu.price:.5f}")

    def asian_cheaper_than_european():
        """Averaging cuts volatility, so an Asian call must be cheaper."""
        kw = dict(n_paths=80_000, n_steps=252, seed=25)
        asian = pr.mc_exotic_price(S, 100.0, T, rf, q, sig, "asian_arithmetic",
                                   "call", **kw)
        euro = pr.mc_exotic_price(S, 100.0, T, rf, q, sig, "european", "call", **kw)
        geo = pr.mc_exotic_price(S, 100.0, T, rf, q, sig, "asian_geometric",
                                 "call", **kw)
        return (asian.price < euro.price and geo.price < asian.price,
                f"geometric {geo.price:.4f} < arithmetic {asian.price:.4f} "
                f"< European {euro.price:.4f}")

    def lookback_dominates_vanilla():
        """A floating-strike lookback call is worth at least the vanilla."""
        kw = dict(n_paths=60_000, n_steps=252, seed=26)
        lb = pr.mc_exotic_price(S, S, T, rf, q, sig, "lookback_floating", "call", **kw)
        eu = pr.mc_exotic_price(S, S, T, rf, q, sig, "european", "call", **kw)
        return lb.price > eu.price, f"lookback {lb.price:.4f} > vanilla {eu.price:.4f}"

    def implied_vol_round_trip():
        """Pricing at sigma then solving must return sigma, or admit it cannot.

        Quotes whose vega is below the identifiability floor are expected to
        come back ``nan`` -- a deep-ITM short-dated option is worth intrinsic to
        forty decimals, so no volatility is recoverable from its price.  The
        assertion is that every quote either inverts essentially exactly or is
        reported as unidentifiable; a silently wrong number is the failure mode
        being guarded against.
        """
        worst, solved, unidentifiable = 0.0, 0, 0
        for k in (70.0, 85.0, 100.0, 115.0, 140.0):
            for t in (0.05, 0.25, 1.0, 2.0):
                for v in (0.10, 0.25, 0.60, 1.20):
                    for kind in ("call", "put"):
                        px = float(pr.bsm_price(S, k, t, rf, q, v, kind))
                        if px < 1e-6:
                            continue
                        got = pr.implied_vol(px, S, k, t, rf, q, kind)
                        vega = pr.bsm_greeks(S, k, t, rf, q, v, kind).vega
                        if not np.isfinite(got):
                            if vega >= pr.MIN_IDENTIFIABLE_VEGA:
                                return False, (f"solver gave up on an identifiable "
                                               f"quote: K={k}, T={t}, vol={v}, "
                                               f"vega={vega:.2e}")
                            unidentifiable += 1
                            continue
                        solved += 1
                        worst = max(worst, abs(got - v))
        # Achievable precision is bounded by eps*price/vega, so the tolerance
        # has to be consistent with the identifiability floor: at the floor
        # (vega 1e-8) a 1-ulp price wobble is worth ~1e-7 of vol.  Quotes with
        # ordinary vega invert to ~1e-12.
        return (worst < 1e-6 and solved > 100,
                f"{solved} quotes inverted, worst absolute vol error "
                f"{worst:.2e} (floor-limited); {unidentifiable} correctly "
                f"flagged unidentifiable (vega < {pr.MIN_IDENTIFIABLE_VEGA:.0e})")

    def implied_vol_rejects_arbitrage():
        """Quotes outside the no-arbitrage bounds must return nan, not a number."""
        below = pr.implied_vol(0.001, S, 60.0, 1.0, rf, q, "call")
        above = pr.implied_vol(S * 2, S, K, 1.0, rf, q, "call")
        return (not np.isfinite(below) and not np.isfinite(above),
                f"below-intrinsic -> {below}, above-spot -> {above}")

    r.check(g, "put-call parity", put_call_parity)
    r.check(g, "Greeks vs finite differences", greeks_vs_finite_difference)
    r.check(g, "binomial converges to BSM", binomial_converges_to_bsm)
    r.check(g, "trinomial converges to BSM", trinomial_converges_to_bsm)
    r.check(g, "American premium >= 0", american_premium_is_nonnegative)
    r.check(g, "MC European within 4 se of BSM", mc_european_within_error_bars)
    r.check(g, "control variate shrinks se", control_variate_reduces_error)
    r.check(g, "MC digital vs closed form", digital_matches_closed_form)
    r.check(g, "barrier in + out = vanilla", barrier_in_plus_out_equals_vanilla)
    r.check(g, "Asian < European", asian_cheaper_than_european)
    r.check(g, "lookback > vanilla", lookback_dominates_vanilla)
    r.check(g, "implied vol round trip", implied_vol_round_trip)
    r.check(g, "implied vol rejects arbitrage", implied_vol_rejects_arbitrage)


# ==========================================================================
# 3. statistics
# ==========================================================================
def _register_stats(r: _Runner) -> None:
    g = "statistics"

    def realized_vol_recovers_sigma():
        """Rolling realised vol on GBM data must recover the input volatility."""
        sigma = 0.32
        p = pm.simulate_gbm(100.0, 5000, 1, DT, np.random.default_rng(30), 0.0, sigma)
        ret = np.diff(np.log(p[0]))
        rv = st.rolling_realized_vol(ret, 252)
        est = float(np.nanmean(rv))
        return _rel(est, sigma) < 0.05, f"mean rolling vol {est:.4f} vs {sigma}"

    def ewma_tracks_a_vol_shift():
        """EWMA must adapt to a regime change faster than a 252-day window."""
        rng = np.random.default_rng(31)
        ret = np.concatenate([rng.normal(0, 0.008, 500), rng.normal(0, 0.030, 120)])
        ew = st.ewma_vol(ret, 0.94)[-1]
        slow = st.rolling_realized_vol(ret, 252)[-1]
        target = 0.030 * np.sqrt(252)
        return (abs(ew - target) < abs(slow - target),
                f"after the shift: EWMA {ew:.3f}, 252d window {slow:.3f}, "
                f"true {target:.3f}")

    def parkinson_and_gk_are_sane():
        """Range estimators must land near the true vol on synthetic OHLC."""
        rng = np.random.default_rng(32)
        n, sigma = 2000, 0.25
        step = sigma * np.sqrt(DT)
        close = 100 * np.exp(np.cumsum(rng.normal(0, step, n)))
        # a Brownian bridge's expected range gives a consistent H/L
        span = np.abs(rng.normal(0, step, n)) + np.abs(rng.normal(0, step, n))
        high, low = close * np.exp(span / 2), close * np.exp(-span / 2)
        open_ = close * np.exp(rng.normal(0, step / 2, n))
        pk = float(np.nanmean(st.parkinson_vol(high, low, 60)))
        gk = float(np.nanmean(st.garman_klass_vol(open_, high, low, close, 60)))
        return (0.4 * sigma < pk < 2.0 * sigma and 0.4 * sigma < gk < 2.0 * sigma,
                f"Parkinson {pk:.4f}, Garman-Klass {gk:.4f}, close-to-close "
                f"target {sigma:.4f}")

    def adf_separates_prices_from_returns():
        """Prices must look like a unit root; returns must not."""
        p = pm.simulate_gbm(100.0, 2000, 1, DT, np.random.default_rng(33), 0.05, 0.25)
        px = p[0]
        ret = np.diff(np.log(px))
        a_px = st.adf_test(px)
        a_ret = st.adf_test(ret)
        return (a_px["stationary_5%"] == 0.0 and a_ret["stationary_5%"] == 1.0,
                f"prices t={a_px['stat']:.2f} (not stationary), "
                f"returns t={a_ret['stat']:.2f} (stationary), crit 5% = -2.86")

    def jarque_bera_discriminates():
        """JB must accept a normal sample and reject a fat-tailed one."""
        rng = np.random.default_rng(34)
        normal = rng.standard_normal(4000)
        fat = rng.standard_t(3, 4000)
        _, p_norm = st.jarque_bera(normal)
        _, p_fat = st.jarque_bera(fat)
        return (p_norm > 0.01 and p_fat < 1e-6,
                f"p(normal)={p_norm:.3f} (accept), p(t3)={p_fat:.2e} (reject)")

    def acf_detects_dependence():
        """ACF must flag AR(1) dependence and clear iid noise."""
        rng = np.random.default_rng(35)
        e = rng.standard_normal(3000)
        ar = np.zeros(3000)
        for i in range(1, 3000):
            ar[i] = 0.5 * ar[i - 1] + e[i]
        a1, band = st.acf(ar, 10)
        a2, _ = st.acf(e, 10)
        _, p_ar = st.ljung_box(ar, 10)
        _, p_iid = st.ljung_box(e, 10)
        return (a1[1] > 0.4 and abs(a2[1]) < 3 * band and p_ar < 1e-8 and p_iid > 0.01,
                f"AR(1) rho1={a1[1]:.3f} (LB p={p_ar:.1e}); "
                f"iid rho1={a2[1]:.3f} (LB p={p_iid:.3f})")

    def distribution_fit_picks_the_truth():
        """AIC must prefer the family the data actually came from."""
        rng = np.random.default_rng(36)
        t_sample = rng.standard_t(3.5, 6000) * 0.01
        n_sample = rng.standard_normal(6000) * 0.01
        best_t = st.fit_distributions(t_sample)[0].name
        best_n = st.fit_distributions(n_sample)[0].name
        return (best_t in ("Student-t", "GED") and best_n in ("Normal", "Skew-normal"),
                f"t(3.5) data -> {best_t}; normal data -> {best_n}")

    def hmm_recovers_known_regimes():
        """Baum-Welch must recover the generating means, vols and transitions."""
        rng = np.random.default_rng(37)
        n = 3000
        true_state = np.zeros(n, dtype=int)
        stay = (0.98, 0.95)
        for t in range(1, n):
            s = true_state[t - 1]
            true_state[t] = s if rng.random() < stay[s] else 1 - s
        obs = np.where(true_state == 0, rng.normal(0.0005, 0.007, n),
                       rng.normal(-0.001, 0.025, n))
        res = st.fit_gaussian_hmm(obs, 2)
        if res is None:
            return False, "HMM failed to fit"
        acc = float((res.states == true_state).mean())
        vol_ok = _rel(res.stds[0], 0.007) < 0.15 and _rel(res.stds[1], 0.025) < 0.15
        trans_ok = abs(res.trans[0, 0] - 0.98) < 0.03 and abs(res.trans[1, 1] - 0.95) < 0.04
        return (acc > 0.9 and vol_ok and trans_ok,
                f"state accuracy {acc:.3f}; vols {res.stds.round(4).tolist()} "
                f"vs [0.007, 0.025]; stay probs "
                f"[{res.trans[0,0]:.3f}, {res.trans[1,1]:.3f}] vs [0.98, 0.95]")

    def hmm_states_sorted_by_volatility():
        """State 0 must always be the calm one, regardless of EM label switching."""
        rng = np.random.default_rng(38)
        obs = np.where(rng.random(2000) < 0.5, rng.normal(0, 0.005, 2000),
                       rng.normal(0, 0.03, 2000))
        res = st.fit_gaussian_hmm(obs, 2)
        return (res is not None and res.stds[0] < res.stds[1],
                f"stds {res.stds.round(5).tolist()} are ascending")

    def technicals_behave():
        """Indicators must satisfy their defining identities."""
        const = np.full(200, 50.0)
        up = np.arange(1, 201, dtype=float)
        problems = []
        if not np.isclose(np.nanmean(tech.sma(const, 20)), 50.0):
            problems.append("SMA of a constant is not the constant")
        if not np.isclose(tech.ema(const, 20)[-1], 50.0):
            problems.append("EMA of a constant is not the constant")
        u, m, l = tech.bollinger_bands(const, 20, 2.0)
        if not (np.isclose(u[-1], 50.0) and np.isclose(l[-1], 50.0)):
            problems.append("Bollinger bands of a constant are not degenerate")
        if not np.isclose(tech.rsi(up, 14)[-1], 100.0):
            problems.append(f"RSI of a monotone rise is {tech.rsi(up,14)[-1]}, not 100")
        if not np.isclose(tech.rsi(up[::-1], 14)[-1], 0.0):
            problems.append("RSI of a monotone fall is not 0")
        line, sig, hist = tech.macd(up)
        if not np.allclose(hist, line - sig, equal_nan=True):
            problems.append("MACD histogram != line - signal")
        a = tech.atr(up + 1, up - 1, up, 14)
        if not np.isfinite(a[-1]) or a[-1] <= 0:
            problems.append("ATR is not positive")
        return (not problems, "; ".join(problems) if problems
                else "SMA, EMA, Bollinger, RSI, MACD, ATR identities hold")

    def vol_cone_brackets_current():
        """Today's realised vol must sit inside its own historical range."""
        p = pm.simulate_gbm(100.0, 3000, 1, DT, np.random.default_rng(39), 0.0, 0.25)
        rows = tech.vol_cone(np.diff(np.log(p[0])))
        bad = [row.window for row in rows
               if not (row.p_min <= row.current <= row.p_max)
               or not (0.0 <= row.percentile_rank <= 100.0)]
        return (rows and not bad,
                f"{len(rows)} horizons, all with min <= current <= max"
                if not bad else f"windows out of range: {bad}")

    def adf_is_correctly_sized():
        """The ADF test must reject a true unit root at its nominal 5% rate.

        A stationarity test that over-rejects would tell the user a random walk
        mean-reverts, which is the single most expensive false positive this
        app could produce.  Size is checked on simulated random walks and power
        on their returns.
        """
        false_pos = 0
        power = 0
        n_trials = 200
        for s in range(n_trials):
            px = pm.simulate_gbm(100.0, 504, 1, DT,
                                 np.random.default_rng(3000 + s), 0.05, 0.22)[0]
            if st.adf_test(px)["stationary_5%"]:
                false_pos += 1
            if st.adf_test(np.diff(np.log(px)))["stationary_5%"]:
                power += 1
        size = false_pos / n_trials
        return (0.01 <= size <= 0.11 and power == n_trials,
                f"rejects a true unit root {size:.1%} of the time "
                f"(nominal 5%); rejects for returns "
                f"{power/n_trials:.0%} of the time (power)")

    r.check(g, "ADF has the right size and power", adf_is_correctly_sized)
    r.check(g, "realised vol recovers sigma", realized_vol_recovers_sigma)
    r.check(g, "EWMA adapts faster than a window", ewma_tracks_a_vol_shift)
    r.check(g, "Parkinson / Garman-Klass sane", parkinson_and_gk_are_sane)
    r.check(g, "ADF separates prices from returns", adf_separates_prices_from_returns)
    r.check(g, "Jarque-Bera discriminates", jarque_bera_discriminates)
    r.check(g, "ACF / Ljung-Box detect dependence", acf_detects_dependence)
    r.check(g, "AIC picks the true family", distribution_fit_picks_the_truth)
    r.check(g, "HMM recovers known regimes", hmm_recovers_known_regimes)
    r.check(g, "HMM states sorted by vol", hmm_states_sorted_by_volatility)
    r.check(g, "technical indicator identities", technicals_behave)
    r.check(g, "vol cone brackets current", vol_cone_brackets_current)


# ==========================================================================
# 4. calibration
# ==========================================================================
def _register_calibration(r: _Runner) -> None:
    g = "calibration"

    def gbm_round_trip():
        """Simulate GBM with known sigma, calibrate, get sigma back."""
        sigma = 0.31
        p = pm.simulate_gbm(100.0, 4000, 1, DT, np.random.default_rng(40), 0.09, sigma)
        est = cal.calibrate_gbm(np.diff(np.log(p[0])), DT)
        return _rel(est["sigma"], sigma) < 0.05, \
            f"sigma {est['sigma']:.4f} vs {sigma} (mu is not asserted: its "\
            f"standard error over 16 years of data is still ~8%/yr)"

    def student_t_round_trip():
        """Fitted degrees of freedom must land near the generating value."""
        nu = 4.0
        p = pm.simulate_student_t(100.0, 6000, 1, DT, np.random.default_rng(41),
                                  0.05, 0.25, nu)
        est = cal.calibrate_student_t(np.diff(np.log(p[0])), DT)
        return (abs(est["nu"] - nu) < 1.5 and _rel(est["sigma"], 0.25) < 0.08,
                f"nu {est['nu']:.2f} vs {nu}; sigma {est['sigma']:.4f} vs 0.25")

    def merton_round_trip():
        """Threshold estimator must separate diffusion from jumps."""
        p = pm.simulate_merton(100.0, 5000, 1, DT, np.random.default_rng(42),
                               0.06, 0.15, lam=8.0, jump_mean=-0.05, jump_std=0.06)
        est = cal.calibrate_merton(np.diff(np.log(p[0])), DT)
        return (_rel(est["sigma"], 0.15) < 0.15 and est["lam"] > 1.0
                and est["jump_mean"] < 0,
                f"sigma {est['sigma']:.4f} vs 0.15; lambda {est['lam']:.2f} vs 8 "
                f"(threshold misses sub-3-sigma jumps by construction); "
                f"jump mean {est['jump_mean']:.4f} vs -0.05")

    def garch_round_trip():
        """QMLE must recover alpha, beta and the implied persistence."""
        true = dict(omega=3e-6, alpha=0.09, beta=0.89)
        p = pm.simulate_garch(100.0, 5000, 1, DT, np.random.default_rng(43),
                              mu=0.08, **true)
        est = cal.calibrate_garch(np.diff(np.log(p[0])), DT)
        return (abs(est["alpha"] - 0.09) < 0.04 and abs(est["beta"] - 0.89) < 0.06,
                f"alpha {est['alpha']:.4f} vs 0.09; beta {est['beta']:.4f} vs 0.89; "
                f"persistence {est['persistence']:.4f} vs 0.98")

    def heston_round_trip():
        """Heston estimates must show their *documented* accuracy, not more.

        Averaged over several independent paths so the check tests the
        estimator rather than one lucky draw.  ``theta`` is asserted tightly
        because it is unbiased; ``kappa`` and ``rho`` are only asserted to have
        the right sign and order of magnitude, because errors-in-variables
        attenuation biases them in a known direction (see the docstring of
        ``calibrate_heston``).  Asserting them tightly would be asserting
        something false.
        """
        thetas, kappas, rhos, xis = [], [], [], []
        for s in range(4):
            p = pm.simulate_heston(100.0, 6000, 1, DT, np.random.default_rng(44 + s),
                                   0.07, v0=0.05, kappa=3.0, theta=0.05,
                                   xi=0.5, rho=-0.7)
            est = cal.calibrate_heston(np.diff(np.log(p[0])), DT)
            thetas.append(est["theta"])
            kappas.append(est["kappa"])
            rhos.append(est["rho"])
            xis.append(est["xi"])
        th, ka, rh, xi = (float(np.mean(v)) for v in (thetas, kappas, rhos, xis))
        return (_rel(th, 0.05) < 0.15 and rh < -0.05 and 0.5 < ka < 12.0
                and 0.1 < xi < 2.0,
                f"mean over 4 paths -- theta {th:.4f} vs 0.05 (unbiased); "
                f"kappa {ka:.2f} vs 3.0 (biased high as documented); "
                f"rho {rh:+.3f} vs -0.7 (sign right, attenuated); xi {xi:.3f} vs 0.5")

    def garch_likelihood_is_correct():
        """The vectorised likelihood must equal a direct loop implementation."""
        rng = np.random.default_rng(45)
        ret = rng.normal(0, 0.012, 800)
        omega, a, b = 4e-6, 0.08, 0.90
        mean = float(ret.mean())
        e2 = (ret - mean) ** 2
        h = float(e2.mean())
        loop = 0.0
        for i in range(ret.size):
            loop += np.log(h) + e2[i] / h
            h = omega + a * e2[i] + b * h
        loop = 0.5 * (loop + ret.size * np.log(2 * np.pi))
        fast = cal.garch_loglik((omega, a, b), ret, mean)
        return abs(fast - loop) < 1e-8, f"filter {fast:.10f} vs loop {loop:.10f}"

    def calibration_dispatch_covers_every_model():
        """Every registered model must have a working calibrator."""
        rng = np.random.default_rng(46)
        ret = rng.normal(0.0004, 0.013, 1500)
        missing = []
        for model in pm.MODEL_REGISTRY:
            try:
                out = cal.calibrate(model, ret, DT)
                if not out or not all(np.isfinite(v) for v in out.values()):
                    missing.append(f"{model}: non-finite output")
            except Exception as exc:
                missing.append(f"{model}: {type(exc).__name__}")
        return (not missing, "; ".join(missing) if missing
                else f"all {len(pm.MODEL_REGISTRY)} models calibrate cleanly")

    def calibrated_params_drive_the_simulator():
        """Calibrated output must feed straight back into the generator."""
        rng = np.random.default_rng(47)
        ret = rng.normal(0.0004, 0.013, 1500)
        broken = []
        for model in pm.MODEL_REGISTRY:
            params = cal.calibrate(model, ret, DT)
            if model in pm.HISTORY_MODELS:
                params["returns"] = ret
            p = pm.simulate_paths(model, 100.0, 60, 512, DT,
                                  np.random.default_rng(48), params)
            if not np.all(np.isfinite(p)) or not np.all(p > 0):
                broken.append(model)
        return (not broken, "; ".join(broken) if broken
                else "calibrate -> simulate round trip clean for every model")

    r.check(g, "GBM parameter round trip", gbm_round_trip)
    r.check(g, "Student-t round trip", student_t_round_trip)
    r.check(g, "Merton round trip", merton_round_trip)
    r.check(g, "GARCH QMLE round trip", garch_round_trip)
    r.check(g, "Heston moment matching", heston_round_trip)
    r.check(g, "GARCH likelihood == loop form", garch_likelihood_is_correct)
    r.check(g, "every model has a calibrator", calibration_dispatch_covers_every_model)
    r.check(g, "calibrate -> simulate round trip",
            calibrated_params_drive_the_simulator)


# ==========================================================================
# 5. risk
# ==========================================================================
def _register_risk(r: _Runner) -> None:
    g = "risk"

    def var_matches_normal_quantile():
        """On lognormal terminals, VaR must match the analytic quantile."""
        from scipy import stats as sps
        s0, sigma, T = 100.0, 0.25, 1.0
        p = pm.simulate_gbm(s0, 252, 400_000, DT, np.random.default_rng(50),
                            0.0, sigma)
        got = rk.var_cvar(p[:, -1], s0, (0.95,))[0.95][0]
        z = sps.norm.ppf(0.05)
        analytic = -(np.exp((0.0 - 0.5 * sigma**2) * T + sigma * np.sqrt(T) * z) - 1)
        return _rel(got, analytic) < 0.01, f"MC VaR95 {got:.5f} vs analytic {analytic:.5f}"

    def cvar_exceeds_var():
        """Expected shortfall must be at least as large as VaR at every level."""
        p = pm.simulate_gbm(100.0, 252, 100_000, DT, np.random.default_rng(51),
                            0.05, 0.3)
        table = rk.var_cvar(p[:, -1], 100.0)
        bad = [lv for lv, (v, c) in table.items() if c < v]
        return (not bad, "; ".join(f"level {lv}" for lv in bad) if bad
                else ", ".join(f"{int(lv*100)}%: VaR {v:.3f} <= CVaR {c:.3f}"
                               for lv, (v, c) in sorted(table.items())))

    def max_drawdown_is_exact():
        """Drawdown must be exact on hand-constructed paths."""
        paths = np.array([
            [100.0, 110.0, 120.0, 130.0],     # monotone up -> 0
            [100.0, 50.0, 75.0, 60.0],        # peak 100, trough 50 -> -50%
            [100.0, 120.0, 60.0, 200.0],      # peak 120, trough 60 -> -50%
        ])
        got = rk.max_drawdown_paths(paths)
        expected = np.array([0.0, -0.5, -0.5])
        return (np.allclose(got, expected),
                f"got {got.round(6).tolist()} vs {expected.tolist()}")

    def barrier_touch_probability_matches_theory():
        """P(max > barrier) must match the reflection-principle formula."""
        from scipy import stats as sps
        s0, sigma, T, b = 100.0, 0.25, 1.0, 130.0
        p = pm.simulate_gbm(s0, 2520, 200_000, T / 2520, np.random.default_rng(52),
                            0.0, sigma)
        got = rk.probability_touch(p.max(axis=1), p.min(axis=1), b, "up")
        # continuous-monitoring first-passage probability for driftless log-price
        nu = (0.0 - 0.5 * sigma**2) / sigma
        a = np.log(b / s0) / sigma
        analytic = float(sps.norm.cdf((nu * T - a) / np.sqrt(T))
                         + np.exp(2 * nu * a) * sps.norm.cdf((-a - nu * T) / np.sqrt(T)))
        return (abs(got - analytic) < 0.01,
                f"simulated {got:.4f} vs continuous-monitoring theory "
                f"{analytic:.4f} (discrete monitoring biases this low)")

    def kelly_matches_gaussian_formula():
        """Empirical Kelly must converge to (mu - rf)/sigma^2 as the horizon shrinks.

        The continuous formula is the *rebalancing* limit, so it is only the
        right reference at a short horizon.  This checks both halves of that
        statement: agreement at one week, and the documented downward drift of
        the buy-and-hold optimum as the horizon lengthens.
        """
        mu, sigma, rfr = 0.12, 0.20, 0.02
        analytic = (mu - rfr) / sigma**2
        short = rk.kelly_fraction(
            pm.simulate_gbm(100.0, 5, 300_000, DT, np.random.default_rng(53),
                            mu, sigma)[:, -1],
            100.0, 5 * DT, rf=rfr)
        long = rk.kelly_fraction(
            pm.simulate_gbm(100.0, 252, 300_000, DT, np.random.default_rng(53),
                            mu, sigma)[:, -1],
            100.0, 1.0, rf=rfr)
        return (_rel(short["kelly_empirical"], analytic) < 0.08
                and long["kelly_empirical"] < short["kelly_empirical"]
                and abs(short["half_kelly"] - short["kelly_empirical"] / 2) < 1e-9,
                f"1-week hold f*={short['kelly_empirical']:.3f} vs continuous "
                f"closed form {analytic:.3f}; 1-year hold falls to "
                f"{long['kelly_empirical']:.3f} as buy-and-hold variance drag "
                f"accumulates")

    def convergence_se_decays_as_sqrt_n():
        """The standard error must fall like 1/sqrt(n)."""
        p = pm.simulate_gbm(100.0, 252, 200_000, DT, np.random.default_rng(54),
                            0.05, 0.25)
        counts, means, se = rk.convergence_curve(p[:, -1], 100)
        i, j = len(counts) // 4, len(counts) - 1
        ratio = se[i] / se[j]
        expected = np.sqrt(counts[j] / counts[i])
        return (_rel(ratio, expected) < 0.35,
                f"se ratio {ratio:.2f} vs sqrt(n) prediction {expected:.2f} "
                f"over {counts[i]:,} -> {counts[j]:,} paths")

    def sharpe_is_sane():
        """Sharpe of a known GBM must match (mu - rf)/sigma within sampling error."""
        mu, sigma = 0.15, 0.20
        p = pm.simulate_gbm(100.0, 252, 200_000, DT, np.random.default_rng(55),
                            mu, sigma)
        sh, so = rk.sharpe_sortino(p[:, -1], 100.0, 1.0, rf=0.03)
        # the ratio is built on log growth, so the reference uses the log drift
        target = (mu - 0.5 * sigma**2 - 0.03) / sigma
        return (_rel(sh, target) < 0.1 and so > sh,
                f"Sharpe {sh:.4f} vs log-drift reference {target:.4f}; "
                f"Sortino {so:.4f} > Sharpe as expected for a right-skewed payoff")

    def correlation_injection_works():
        """Cholesky must reproduce the target correlation in simulated returns."""
        target = np.array([[1.0, 0.7, -0.3], [0.7, 1.0, 0.1], [-0.3, 0.1, 1.0]])
        res = ma.simulate_correlated_gbm(
            [100, 50, 200], [0.08, 0.05, 0.03], [0.2, 0.3, 0.15], target,
            126, 20_000, rng=np.random.default_rng(56))
        err = float(np.abs(res.realised_corr - target).max())
        return err < 0.02, f"max correlation error {err:.4f} against the target"

    def psd_repair_enables_cholesky():
        """An inconsistent correlation matrix must be repaired, not crash."""
        bad = np.array([[1.0, 0.99, -0.99], [0.99, 1.0, 0.99], [-0.99, 0.99, 1.0]])
        if np.linalg.eigvalsh(bad).min() >= 0:
            return False, "test fixture is not actually indefinite"
        fixed = ma.nearest_psd(bad)
        L = ma.cholesky_factor(bad)
        return (np.linalg.eigvalsh(fixed).min() > -1e-12 and L.shape == (3, 3)
                and np.all(np.isfinite(L)),
                f"min eigenvalue {np.linalg.eigvalsh(bad).min():.3f} -> "
                f"{np.linalg.eigvalsh(fixed).min():.2e}; Cholesky succeeds")

    r.check(g, "VaR matches analytic quantile", var_matches_normal_quantile)
    r.check(g, "CVaR >= VaR at every level", cvar_exceeds_var)
    r.check(g, "max drawdown exact on fixtures", max_drawdown_is_exact)
    r.check(g, "barrier touch vs reflection principle",
            barrier_touch_probability_matches_theory)
    r.check(g, "Kelly matches closed form", kelly_matches_gaussian_formula)
    r.check(g, "standard error decays as 1/sqrt(n)", convergence_se_decays_as_sqrt_n)
    r.check(g, "Sharpe / Sortino sane", sharpe_is_sane)
    r.check(g, "Cholesky reproduces correlation", correlation_injection_works)
    r.check(g, "PSD repair enables Cholesky", psd_repair_enables_cholesky)


# ==========================================================================
# 6. engine and data layer
# ==========================================================================
def _register_engine(r: _Runner) -> None:
    g = "engine + data"

    def engine_is_reproducible():
        """Same seed and batching must give bit-identical results."""
        req = SimRequest(model="gbm", n_paths=50_000, horizon_days=126, seed=99,
                         params=pm.default_params("gbm"), batch_size=8_000)
        a = SimulationEngine().run(req)
        b = SimulationEngine().run(req)
        return (np.array_equal(a.terminal, b.terminal),
                f"{a.n_done:,} paths identical across two runs "
                f"(mean {a.summary()['mean']:.6f})")

    def engine_streams_partials():
        """Partial results must arrive during the run, monotonically growing."""
        seen: List[int] = []
        req = SimRequest(model="gbm", n_paths=60_000, horizon_days=63,
                         params=pm.default_params("gbm"), batch_size=6_000)
        res = SimulationEngine().run(req, on_partial=lambda s: seen.append(s.n_done))
        growing = all(b > a for a, b in zip(seen, seen[1:]))
        return (len(seen) >= 5 and growing and seen[-1] == res.n_done == 60_000,
                f"{len(seen)} partial snapshots, monotonically increasing, "
                f"final {seen[-1]:,}")

    def engine_cancels_promptly():
        """Cancellation must stop mid-run and still return usable partial data."""
        import threading
        req = SimRequest(model="gbm", n_paths=4_000_000, horizon_days=252,
                         params=pm.default_params("gbm"), batch_size=20_000)
        eng = SimulationEngine()
        box: List = []
        th = threading.Thread(target=lambda: box.append(eng.run(req)))
        t0 = time.perf_counter()
        th.start()
        time.sleep(0.35)
        eng.cancel()
        th.join(timeout=10)
        el = time.perf_counter() - t0
        res = box[0]
        return (res.cancelled and 0 < res.n_done < 4_000_000 and el < 3.0
                and bool(res.summary()),
                f"stopped after {el:.2f}s with {res.n_done:,} of 4,000,000 paths; "
                f"partial statistics still computable")

    def engine_memory_is_bounded():
        """The fan reservoir must cap regardless of the total path count."""
        req = SimRequest(model="gbm", n_paths=200_000, horizon_days=252,
                         params=pm.default_params("gbm"), batch_size=25_000,
                         max_fan_paths=2_000)
        res = SimulationEngine().run(req)
        return (res.fan_paths.shape == (2_000, 253) and res.terminal.size == 200_000,
                f"200,000 paths simulated, fan reservoir held at "
                f"{res.fan_paths.shape[0]:,} x {res.fan_paths.shape[1]}")

    def engine_hits_performance_target():
        """100k paths x 252 steps of GBM must finish in under 2 seconds."""
        req = SimRequest(model="gbm", n_paths=100_000, horizon_days=252,
                         params=pm.default_params("gbm"), batch_size=10_000)
        t0 = time.perf_counter()
        res = SimulationEngine().run(req)
        el = time.perf_counter() - t0
        return (el < 2.0 and res.n_done == 100_000,
                f"{el:.2f}s for 100,000 x 252 "
                f"({res.n_done/max(el,1e-9)/1000:.0f}k paths/s)")

    def engine_rejects_bad_requests():
        """Invalid requests must return an error, never raise."""
        cases = [
            (SimRequest(model="does_not_exist"), "unknown model"),
            (SimRequest(s0=-1.0), "positive"),
            (SimRequest(model="bootstrap", history_returns=None), "historical"),
            (SimRequest(n_paths=1), "at least 2 paths"),
            (SimRequest(horizon_days=0), "at least 1 step"),
        ]
        for req, needle in cases:
            res = SimulationEngine().run(req)
            if not res.error or needle not in res.error:
                return False, f"expected an error mentioning {needle!r}, got {res.error!r}"
        return True, f"all {len(cases)} invalid requests degraded to error messages"

    def every_model_runs_through_the_engine():
        """The engine must drive every registered model end to end."""
        rng = np.random.default_rng(60)
        hist = rng.normal(0.0004, 0.012, 1200)
        broken = []
        for model in pm.MODEL_REGISTRY:
            req = SimRequest(model=model, params=pm.default_params(model),
                             n_paths=8_000, horizon_days=63, history_returns=hist,
                             target_price=105.0, barrier=115.0, ruin_level=80.0,
                             batch_size=4_000)
            res = SimulationEngine().run(req)
            s = res.summary()
            if res.error or not s or not np.isfinite(s.get("mean", np.nan)):
                broken.append(f"{model}: {res.error or 'no summary'}")
            elif not np.isfinite(res.risk().get("var_95", np.nan)):
                broken.append(f"{model}: risk table broken")
        return (not broken, "; ".join(broken) if broken
                else f"all {len(pm.MODEL_REGISTRY)} models run + summarise + risk")

    def cache_round_trips():
        """Bars written to the cache must read back identically."""
        import pandas as pd
        from .data.cache import BarCache

        path = os.path.join(tempfile.mkdtemp(prefix="quantmc_st_"), "t.sqlite")
        cache = BarCache(path)
        try:
            idx = pd.bdate_range("2024-01-01", periods=300)
            rng = np.random.default_rng(61)
            close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
            frame = pd.DataFrame(
                {"Open": close, "High": close * 1.01, "Low": close * 0.99,
                 "Close": close, "Volume": rng.integers(1e6, 5e6, 300)}, index=idx)
            written = cache.write_bars("TEST", "1d", frame, source="unit")
            back = cache.read_bars("TEST", "1d")
            cov = cache.coverage("TEST", "1d")
            same = np.allclose(back["close"].to_numpy(), close)
            # idempotent upsert: writing twice must not duplicate rows
            cache.write_bars("TEST", "1d", frame)
            n_after = len(cache.read_bars("TEST", "1d"))
            limited = cache.read_bars("TEST", "1d", limit=50)
            tail_ok = (len(limited) == 50
                       and np.allclose(limited["close"].to_numpy(), close[-50:]))
            return (written == 300 and same and n_after == 300 and cov.rows == 300
                    and tail_ok,
                    f"wrote {written}, read {len(back)}, re-wrote -> {n_after} "
                    f"(no duplicates), limit=50 returns the last 50 bars")
        finally:
            cache.close()

    def provider_degrades_gracefully():
        """Bad ticker, offline mode and empty responses must not raise."""
        from .data.cache import BarCache
        from .data.provider import Health, MarketData, SyntheticProvider

        path = os.path.join(tempfile.mkdtemp(prefix="quantmc_st_"), "p.sqlite")
        cache = BarCache(path)
        try:
            md = MarketData(provider=SyntheticProvider(), cache=cache,
                            fallback_synthetic=True)
            first = md.history("ZZZZ", "1y", "1d")
            second = md.history("ZZZZ", "1y", "1d")
            offline = MarketData(provider=SyntheticProvider(), cache=cache,
                                 offline=True, fallback_synthetic=False)
            missing = offline.history("NEVER_SEEN")
            cached = offline.history("ZZZZ")
            empty = md.history("")
            return (not first.empty and second.status.health == Health.CACHED
                    and missing.status.health == Health.ERROR and missing.empty
                    and cached.status.health == Health.CACHED
                    and empty.status.health == Health.ERROR,
                    "fetch -> cache hit -> offline cache hit -> offline miss "
                    "returns ERROR -> empty ticker returns ERROR, no exceptions")
        finally:
            cache.close()

    def synthetic_data_is_deterministic():
        """Offline fixtures must be identical across processes and instances."""
        from .data.provider import SyntheticProvider

        a = SyntheticProvider().get_history("REPRO").close
        b = SyntheticProvider().get_history("REPRO").close
        c = SyntheticProvider().get_history("OTHER").close
        return (np.array_equal(a, b) and not np.array_equal(a[: len(c)], c[: len(a)]),
                f"same ticker reproduces exactly ({a[-1]:.6f}); a different "
                f"ticker gives a different series ({c[-1]:.6f})")

    def synthetic_chain_inverts_to_its_own_surface():
        """IVs solved from the synthetic chain must recover the input vols."""
        from .data.provider import SyntheticProvider

        prov = SyntheticProvider()
        chain = prov.get_option_chain("SURF")
        tidy, pivot = pr.build_iv_surface(chain.frame, chain.spot, r=0.04, q=0.0)
        if tidy.empty:
            return False, "surface build produced no rows"
        err = float((tidy["iv"] - tidy["impliedVolatility"]).abs().max())
        dropped = len(chain.frame) - len(tidy)
        return (err < 1e-6 and pivot.shape[0] >= 3,
                f"{len(tidy)} contracts inverted to within {err:.2e} vol; "
                f"{dropped} dropped as unidentifiable or out of the moneyness "
                f"window; surface grid {pivot.shape[0]}x{pivot.shape[1]}")

    def config_round_trips():
        """Settings must survive a save/load cycle and tolerate corruption."""
        from .config import AppConfig

        path = os.path.join(tempfile.mkdtemp(prefix="quantmc_st_"), "cfg.json")
        cfg = AppConfig(ticker="NVDA", model="heston", n_paths=250_000,
                        horizon_days=63)
        cfg.set_params_for("heston", {"mu": 0.11, "kappa": 2.5, "returns": None})
        if not cfg.save(path):
            return False, "save failed"
        back = AppConfig.load(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json at all")
        corrupt = AppConfig.load(path)
        return (back.ticker == "NVDA" and back.model == "heston"
                and back.n_paths == 250_000
                and back.model_params["heston"]["kappa"] == 2.5
                and "returns" not in back.model_params["heston"]
                and corrupt.ticker == AppConfig().ticker,
                "round trip preserves settings, drops the return sample, and a "
                "corrupt file falls back to defaults")

    r.check(g, "engine reproducible with a seed", engine_is_reproducible)
    r.check(g, "engine streams partial results", engine_streams_partials)
    r.check(g, "engine cancels promptly", engine_cancels_promptly)
    r.check(g, "engine memory stays bounded", engine_memory_is_bounded)
    r.check(g, "100k x 252 under 2 seconds", engine_hits_performance_target)
    r.check(g, "engine rejects bad requests", engine_rejects_bad_requests)
    r.check(g, "every model runs end to end", every_model_runs_through_the_engine)
    r.check(g, "cache round trip + upsert", cache_round_trips)
    r.check(g, "provider degrades gracefully", provider_degrades_gracefully)
    r.check(g, "synthetic data deterministic", synthetic_data_is_deterministic)
    r.check(g, "synthetic chain inverts", synthetic_chain_inverts_to_its_own_surface)
    r.check(g, "config round trip", config_round_trips)


# ==========================================================================
# runner
# ==========================================================================
def run_selftest(verbose: bool = False, groups: Optional[List[str]] = None) -> int:
    """Run the suite, print the results table, return a process exit code.

    Returns 0 when every check passes and 1 otherwise, so it drops straight
    into CI.
    """
    runner = _Runner(verbose=verbose)
    registrars = {
        "paths": _register_path_models,
        "pricing": _register_pricing,
        "stats": _register_stats,
        "calibration": _register_calibration,
        "risk": _register_risk,
        "engine": _register_engine,
    }
    selected = groups or list(registrars)
    started = time.perf_counter()

    print()
    print("=" * 100)
    print("  QuantMC self-test -- model suite on synthetic and cached data, no GUI")
    print("=" * 100)

    for key in selected:
        fn = registrars.get(key)
        if fn is None:
            print(f"  ! unknown group {key!r}, skipping")
            continue
        fn(runner)

    total_elapsed = time.perf_counter() - started

    current = ""
    for c in runner.checks:
        if c.group != current:
            current = c.group
            print(f"\n  {current.upper()}")
            print("  " + "-" * 96)
        mark = "PASS" if c.passed else "FAIL"
        print(f"  [{mark}] {c.name:<38} {c.elapsed:6.2f}s  {c.detail}")

    n = len(runner.checks)
    failed = runner.failures
    print()
    print("=" * 100)
    if failed:
        print(f"  RESULT: {n - len(failed)}/{n} passed, {len(failed)} FAILED "
              f"in {total_elapsed:.1f}s")
        for c in failed:
            print(f"     - [{c.group}] {c.name}: {c.detail}")
    else:
        print(f"  RESULT: {n}/{n} checks passed in {total_elapsed:.1f}s")
    print("=" * 100)
    print("  Reminder: this is a modelling tool, not investment advice.  Every")
    print("  simulated distribution is conditional on the assumptions of the")
    print("  model that generated it.")
    print()
    return 1 if failed else 0
