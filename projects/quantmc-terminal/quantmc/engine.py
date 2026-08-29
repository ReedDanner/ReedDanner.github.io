"""
Batched, cancellable, streaming Monte Carlo engine.

The engine is deliberately UI-free: it takes plain callbacks and a
``threading.Event``, so it runs identically under a Qt worker thread, a pytest
run, or a plain script.  :mod:`quantmc.ui` wraps it in a ``QThread`` and turns
the callbacks into Qt signals.

Why batching
------------
Three requirements fall out of it at once:

* **Streaming** -- partial results are published every few batches, so the fan
  chart and statistics fill in progressively instead of appearing at the end.
* **Cancellation** -- the cancel flag is checked between batches, so a
  100k-path run stops within one batch (tens of milliseconds), not at the end.
* **Bounded memory** -- each batch's ``(batch, steps+1)`` matrix is reduced to
  four per-path vectors and discarded.  Only a fixed-size reservoir of whole
  paths is retained for the fan chart, so peak memory is independent of the
  total path count.

MODELLING TOOL, NOT INVESTMENT ADVICE.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .models import paths as pathmod
from .models import risk as riskmod

__all__ = [
    "SimRequest", "SimProgress", "SimResult", "SimulationEngine",
    "run_simulation",
]

TRADING_DAYS = 252.0


# --------------------------------------------------------------------------
# request
# --------------------------------------------------------------------------
@dataclass
class SimRequest:
    """Everything needed to run one simulation.

    ``params`` holds the chosen model's own parameters (see
    :data:`quantmc.models.paths.MODEL_PARAM_SPECS`).  ``history_returns`` is
    required by the bootstrap models and ignored by the parametric ones.
    """

    ticker: str = "SYNTH"
    s0: float = 100.0
    model: str = "gbm"
    params: Dict[str, float] = field(default_factory=dict)
    horizon_days: int = 252
    n_paths: int = 100_000
    dt: float = 1.0 / TRADING_DAYS
    seed: Optional[int] = 42
    antithetic: bool = False
    batch_size: int = 10_000
    update_every: int = 1
    """Publish a partial result every N batches."""
    max_fan_paths: int = 4_000
    """How many whole paths to retain for the fan chart."""
    history_returns: Optional[np.ndarray] = None
    target_price: Optional[float] = None
    barrier: Optional[float] = None
    barrier_direction: str = "up"
    ruin_level: Optional[float] = None
    risk_free: float = 0.04

    @property
    def horizon_years(self) -> float:
        return float(self.horizon_days) * float(self.dt)

    def resolved_params(self) -> Dict[str, float]:
        """Model parameters with the historical sample injected if required."""
        p = dict(self.params)
        if self.model in pathmod.HISTORY_MODELS:
            p["returns"] = self.history_returns
        return p

    def validate(self) -> Optional[str]:
        """Return a human-readable problem, or ``None`` if the request is runnable."""
        if self.model not in pathmod.MODEL_REGISTRY:
            return f"unknown model {self.model!r}"
        if not np.isfinite(self.s0) or self.s0 <= 0:
            return f"spot price must be positive, got {self.s0}"
        if self.horizon_days < 1:
            return "horizon must be at least 1 step"
        if self.n_paths < 2:
            return "need at least 2 paths"
        if self.dt <= 0:
            return "time step must be positive"
        if self.model in pathmod.HISTORY_MODELS:
            r = self.history_returns
            if r is None or np.asarray(r).size < 30:
                return (f"{pathmod.MODEL_LABELS[self.model]} needs at least 30 "
                        "historical returns; load more history first")
        return None


# --------------------------------------------------------------------------
# progress
# --------------------------------------------------------------------------
@dataclass
class SimProgress:
    """Progress snapshot handed to the progress callback."""

    paths_done: int
    paths_total: int
    batches_done: int
    elapsed: float

    @property
    def fraction(self) -> float:
        return min(1.0, self.paths_done / max(1, self.paths_total))

    @property
    def eta(self) -> float:
        """Seconds remaining, extrapolated from the throughput so far."""
        f = self.fraction
        if f <= 1e-9 or self.elapsed <= 0:
            return float("nan")
        return self.elapsed * (1.0 - f) / f

    @property
    def paths_per_second(self) -> float:
        return self.paths_done / self.elapsed if self.elapsed > 0 else float("nan")


# --------------------------------------------------------------------------
# result
# --------------------------------------------------------------------------
@dataclass
class SimResult:
    """Accumulated simulation state; also the final result object.

    Partial snapshots published mid-run have the same type as the final one --
    the only difference is ``complete``.  That keeps the UI code simple: one
    render path for streaming updates and for the finished run.
    """

    request: SimRequest
    terminal: np.ndarray
    path_max: np.ndarray
    path_min: np.ndarray
    max_drawdown: np.ndarray
    fan_paths: np.ndarray
    elapsed: float = 0.0
    complete: bool = False
    cancelled: bool = False
    error: str = ""

    @property
    def n_done(self) -> int:
        return int(self.terminal.size)

    @property
    def time_grid(self) -> np.ndarray:
        """Step index for the fan-chart x-axis (0 .. horizon_days)."""
        n = self.fan_paths.shape[1] if self.fan_paths.size else 1
        return np.arange(n, dtype=float)

    # -- derived views ---------------------------------------------------
    def bands(
        self, levels: Sequence[float] = riskmod.DEFAULT_BANDS
    ) -> Dict[float, np.ndarray]:
        """Pointwise percentile ribbons from the retained path reservoir."""
        if self.fan_paths.size == 0:
            return {}
        return riskmod.percentile_bands(self.fan_paths, levels)

    def summary(self) -> Dict[str, float]:
        """Terminal-distribution moments, percentile ladder and probabilities."""
        req = self.request
        out = riskmod.terminal_summary(self.terminal, req.s0)
        if not out:
            return out
        out["s0"] = float(req.s0)
        out["horizon_days"] = float(req.horizon_days)
        out["expected_max_drawdown"] = float(np.mean(self.max_drawdown)) \
            if self.max_drawdown.size else float("nan")
        out["median_max_drawdown"] = float(np.median(self.max_drawdown)) \
            if self.max_drawdown.size else float("nan")
        out["worst_max_drawdown"] = float(np.min(self.max_drawdown)) \
            if self.max_drawdown.size else float("nan")
        if req.target_price is not None:
            out["prob_above_target"] = riskmod.probability_above(
                self.terminal, req.target_price)
        if req.barrier is not None:
            out["prob_touch_barrier"] = riskmod.probability_touch(
                self.path_max, self.path_min, req.barrier, req.barrier_direction)
        if req.ruin_level is not None:
            out["prob_ruin"] = riskmod.probability_of_ruin(
                self.path_min, req.ruin_level)
        return out

    def risk(self) -> Dict[str, float]:
        """VaR/CVaR ladder, Sharpe, Sortino and drawdown percentiles."""
        req = self.request
        out: Dict[str, float] = {}
        if self.terminal.size < 2:
            return out
        for level, (var, cvar) in riskmod.var_cvar(self.terminal, req.s0).items():
            out[f"var_{int(level*100)}"] = var
            out[f"cvar_{int(level*100)}"] = cvar
        sharpe, sortino = riskmod.sharpe_sortino(
            self.terminal, req.s0, req.horizon_years, req.risk_free)
        out["sharpe"] = sharpe
        out["sortino"] = sortino
        if self.max_drawdown.size:
            for p in (5, 25, 50, 75, 95):
                out[f"mdd_p{p}"] = float(np.percentile(self.max_drawdown, p))
        return out

    def kelly(self) -> Dict[str, float]:
        """Growth-optimal position sizing implied by the simulated returns."""
        req = self.request
        return riskmod.kelly_fraction(
            self.terminal, req.s0, req.horizon_years, req.risk_free)

    def convergence(self, n_points: int = 120):
        """Running mean and standard error of the terminal price vs path count."""
        return riskmod.convergence_curve(self.terminal, n_points)

    def price_estimate(self, dividend: float = 0.0) -> Dict[str, float]:
        """Point estimate of the price at the horizon, with uncertainty bands.

        Three different "estimates" are reported because they answer different
        questions, and confusing them is the classic way to misread a Monte
        Carlo:

        * **expected** -- the mean of the simulated terminal prices, with its
          Monte Carlo standard error.  This is the probability-weighted average
          outcome.  Because the terminal distribution is right-skewed
          (lognormal-ish), the mean sits *above* the median and above the most
          likely single outcome.
        * **median** -- the 50th percentile: half the paths finish above it.
          For a skewed distribution this is the more honest "central" number,
          and it is what a trader should compare a price target against.
        * **mode** -- the peak of the terminal density (highest-count histogram
          bin), i.e. the single most likely outcome.  Lowest of the three for a
          right-skewed distribution.

        The **forward** price ``S0 * exp((r - q) * T)`` is the risk-neutral
        no-arbitrage price of delivery at the horizon -- what the market
        charges today, carrying no view.  ``vs_forward`` is the model's claimed
        edge over it.  A large positive ``vs_forward`` is not a signal; it means
        the drift you supplied is above the risk-free rate, which is an
        assumption you entered, not something the simulation discovered.

        Confidence bands are percentile intervals of the simulated
        distribution, so they inherit every assumption of the path model and
        are *not* statistical confidence intervals for a real future price.
        """
        req = self.request
        t = np.asarray(self.terminal, dtype=float)
        t = t[np.isfinite(t)]
        out: Dict[str, float] = {}
        if t.size < 2:
            return out
        s0 = float(req.s0)
        T = req.horizon_years
        r = float(req.risk_free)

        mean = float(t.mean())
        median = float(np.median(t))
        # modal outcome: densest histogram bin, using Freedman-Diaconis-ish
        # bin count capped so the mode is stable rather than noisy
        bins = int(np.clip(np.sqrt(t.size), 40, 250))
        counts, edges = np.histogram(t, bins=bins)
        peak = int(np.argmax(counts))
        mode = float(0.5 * (edges[peak] + edges[peak + 1]))

        forward = s0 * float(np.exp((r - float(dividend)) * T))
        out.update({
            "spot": s0,
            "horizon_days": float(req.horizon_days),
            "horizon_years": T,
            "expected": mean,
            "expected_se": float(t.std(ddof=1) / np.sqrt(t.size)),
            "expected_return": mean / s0 - 1.0,
            "median": median,
            "median_return": median / s0 - 1.0,
            "mode": mode,
            "lo68": float(np.percentile(t, 16)),
            "hi68": float(np.percentile(t, 84)),
            "lo95": float(np.percentile(t, 2.5)),
            "hi95": float(np.percentile(t, 97.5)),
            "forward": forward,
            "vs_forward": mean / forward - 1.0 if forward > 0 else float("nan"),
            "prob_above_spot": float((t > s0).mean()),
            "n_paths": float(t.size),
        })
        if T > 0:
            out["annualized_expected_return"] = float(
                np.expm1(np.log(max(mean / s0, 1e-12)) / T))
        return out

    def export_rows(self) -> List[Tuple[str, object]]:
        """Flat ``(key, value)`` rows for the CSV/JSON run export."""
        req = self.request
        rows: List[Tuple[str, object]] = [
            ("ticker", req.ticker),
            ("model", pathmod.MODEL_LABELS.get(req.model, req.model)),
            ("model_key", req.model),
            ("spot", req.s0),
            ("horizon_days", req.horizon_days),
            ("dt_years", req.dt),
            ("paths_requested", req.n_paths),
            ("paths_completed", self.n_done),
            ("seed", req.seed),
            ("antithetic", req.antithetic),
            ("elapsed_seconds", round(self.elapsed, 4)),
            ("cancelled", self.cancelled),
        ]
        for k, v in req.params.items():
            if k != "returns":
                rows.append((f"param.{k}", v))
        for k, v in self.price_estimate().items():
            rows.append((f"estimate.{k}", v))
        for k, v in self.summary().items():
            rows.append((f"stat.{k}", v))
        for k, v in self.risk().items():
            rows.append((f"risk.{k}", v))
        for k, v in self.kelly().items():
            rows.append((f"kelly.{k}", v))
        return rows


def _empty_result(request: SimRequest) -> SimResult:
    n_cols = int(request.horizon_days) + 1
    return SimResult(
        request=request,
        terminal=np.empty(0), path_max=np.empty(0), path_min=np.empty(0),
        max_drawdown=np.empty(0), fan_paths=np.empty((0, n_cols)),
    )


# --------------------------------------------------------------------------
# engine
# --------------------------------------------------------------------------
class SimulationEngine:
    """Runs a :class:`SimRequest` in batches with progress and cancellation.

    Threading note: numpy releases the GIL for the large array operations that
    dominate here, so a plain worker *thread* keeps the Qt event loop
    responsive without the pickling cost and start-up latency a process pool
    would add.  Nothing in the engine mutates shared state, so the only
    synchronisation needed is the cancel event.
    """

    def __init__(self) -> None:
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Request that the current run stop at the next batch boundary."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(
        self,
        request: SimRequest,
        on_progress: Optional[Callable[[SimProgress], None]] = None,
        on_partial: Optional[Callable[[SimResult], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> SimResult:
        """Execute the request, streaming partial results as batches complete.

        ``on_partial`` receives a :class:`SimResult` whose arrays are *views of
        the accumulated data so far*.  The UI must not hold on to them past the
        callback; it renders and drops them.

        Failures (a bad parameter, a model that cannot run, an out-of-memory
        batch) are captured into ``result.error`` rather than raised, because
        the caller is usually a worker thread whose exception nobody would see.
        """
        cancel = cancel_event if cancel_event is not None else self._cancel
        cancel.clear()

        problem = request.validate()
        if problem:
            res = _empty_result(request)
            res.error = problem
            res.complete = True
            return res

        n_total = int(request.n_paths)
        batch = int(max(256, min(request.batch_size, n_total)))
        rng = np.random.default_rng(request.seed)
        params = request.resolved_params()
        n_steps = int(request.horizon_days)

        term_chunks: List[np.ndarray] = []
        max_chunks: List[np.ndarray] = []
        min_chunks: List[np.ndarray] = []
        mdd_chunks: List[np.ndarray] = []
        fan: List[np.ndarray] = []
        fan_rows = 0

        result = _empty_result(request)
        started = time.perf_counter()
        done = 0
        batches = 0

        try:
            while done < n_total:
                if cancel.is_set():
                    result.cancelled = True
                    break
                size = min(batch, n_total - done)
                if request.antithetic and size % 2 and size > 1:
                    size -= 1  # keep antithetic pairs intact within a batch
                    if size == 0:
                        size = 1

                block = pathmod.simulate_paths(
                    request.model, request.s0, n_steps, size, request.dt,
                    rng, params, request.antithetic,
                )
                stats = riskmod.batch_stats(block)
                term_chunks.append(stats.terminal)
                max_chunks.append(stats.path_max)
                min_chunks.append(stats.path_min)
                mdd_chunks.append(stats.max_drawdown)

                if fan_rows < request.max_fan_paths:
                    take = min(request.max_fan_paths - fan_rows, block.shape[0])
                    fan.append(block[:take].copy())
                    fan_rows += take
                del block

                done += size
                batches += 1

                if on_progress is not None:
                    on_progress(SimProgress(done, n_total, batches,
                                            time.perf_counter() - started))
                if on_partial is not None and (
                    batches % max(1, request.update_every) == 0 or done >= n_total
                ):
                    snapshot = _assemble(request, term_chunks, max_chunks,
                                         min_chunks, mdd_chunks, fan)
                    snapshot.elapsed = time.perf_counter() - started
                    on_partial(snapshot)
        except MemoryError:
            result.error = (f"out of memory at {done:,} paths -- reduce the batch "
                            "size or the path count")
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"

        final = _assemble(request, term_chunks, max_chunks, min_chunks,
                          mdd_chunks, fan)
        final.elapsed = time.perf_counter() - started
        final.cancelled = result.cancelled or cancel.is_set()
        final.error = result.error
        final.complete = True
        return final


def _assemble(
    request: SimRequest,
    term: List[np.ndarray], mx: List[np.ndarray], mn: List[np.ndarray],
    mdd: List[np.ndarray], fan: List[np.ndarray],
) -> SimResult:
    """Concatenate the accumulated chunks into a result snapshot."""
    n_cols = int(request.horizon_days) + 1
    return SimResult(
        request=request,
        terminal=np.concatenate(term) if term else np.empty(0),
        path_max=np.concatenate(mx) if mx else np.empty(0),
        path_min=np.concatenate(mn) if mn else np.empty(0),
        max_drawdown=np.concatenate(mdd) if mdd else np.empty(0),
        fan_paths=np.vstack(fan) if fan else np.empty((0, n_cols)),
    )


def run_simulation(request: SimRequest, **kwargs) -> SimResult:
    """Convenience wrapper: run one request to completion on this thread."""
    return SimulationEngine().run(request, **kwargs)
