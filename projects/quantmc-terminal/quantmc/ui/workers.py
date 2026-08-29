"""
QThread wrappers that keep every long operation off the GUI thread.

The engine and the data layer know nothing about Qt; these adapters translate
their plain callbacks into signals.  Three rules are enforced here:

1. **No widget is touched from a worker.**  Workers emit signals only; the main
   thread does all rendering.
2. **Partial results are throttled.**  A 100k-path run publishes a snapshot
   every batch, which can be faster than the screen refreshes.  Emitting all of
   them would queue up repaints the user never sees, so snapshots are dropped
   if the previous one was less than ``min_interval`` ago.  The final result is
   never dropped.
3. **Failures become signals, not tracebacks.**  An exception in a worker
   thread would otherwise vanish silently.
"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from ..engine import SimProgress, SimRequest, SimResult, SimulationEngine

__all__ = ["SimulationWorker", "DataWorker", "ChainWorker", "BasketWorker",
           "CallableWorker"]


class SimulationWorker(QThread):
    """Runs one :class:`SimRequest`, streaming progress and partial results."""

    progress = pyqtSignal(object)   # SimProgress
    partial = pyqtSignal(object)    # SimResult
    finished_run = pyqtSignal(object)  # SimResult
    failed = pyqtSignal(str)

    def __init__(self, request: SimRequest, min_interval: float = 0.10,
                 parent=None) -> None:
        super().__init__(parent)
        self.request = request
        self.engine = SimulationEngine()
        self._cancel = threading.Event()
        self._min_interval = float(min_interval)
        self._last_emit = 0.0
        self._last_progress = 0.0

    def cancel(self) -> None:
        """Ask the engine to stop at the next batch boundary."""
        self._cancel.set()
        self.engine.cancel()

    def _on_progress(self, p: SimProgress) -> None:
        now = time.perf_counter()
        if now - self._last_progress >= 0.05 or p.fraction >= 1.0:
            self._last_progress = now
            self.progress.emit(p)

    def _on_partial(self, res: SimResult) -> None:
        now = time.perf_counter()
        if now - self._last_emit < self._min_interval:
            return
        self._last_emit = now
        self.partial.emit(res)

    def run(self) -> None:  # noqa: D102 (QThread entry point)
        try:
            result = self.engine.run(
                self.request, on_progress=self._on_progress,
                on_partial=self._on_partial, cancel_event=self._cancel,
            )
            self.finished_run.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc(limit=6))


class CallableWorker(QThread):
    """Runs any callable off the GUI thread and emits its return value.

    Used for the operations that are slow but not streamed -- calibration,
    distribution fitting, the HMM, exotic Monte Carlo pricing.  A GARCH fit or
    a Baum-Welch run takes a few hundred milliseconds, which is long enough to
    drop frames if it happens on the GUI thread.
    """

    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D102
        try:
            self.done.emit(self._fn())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class DataWorker(QThread):
    """Fetches price history for one ticker."""

    done = pyqtSignal(object)   # HistoryResult
    quote_done = pyqtSignal(object)  # Quote
    failed = pyqtSignal(str)

    def __init__(self, market, ticker: str, period: str, interval: str,
                 force_refresh: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.market = market
        self.ticker = ticker
        self.period = period
        self.interval = interval
        self.force_refresh = force_refresh

    def run(self) -> None:  # noqa: D102
        try:
            res = self.market.history(self.ticker, self.period, self.interval,
                                      force_refresh=self.force_refresh)
            self.done.emit(res)
            # the quote is a second round trip; a failure here must not
            # invalidate the history that already arrived
            try:
                self.quote_done.emit(self.market.quote(self.ticker))
            except Exception:
                pass
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class ChainWorker(QThread):
    """Fetches an option chain and solves its implied-vol surface."""

    done = pyqtSignal(object, object, object)  # ChainResult, tidy, pivot
    failed = pyqtSignal(str)

    def __init__(self, market, ticker: str, spot: float, rate: float,
                 dividend: float, max_expiries: int = 8, parent=None) -> None:
        super().__init__(parent)
        self.market = market
        self.ticker = ticker
        self.spot = spot
        self.rate = rate
        self.dividend = dividend
        self.max_expiries = max_expiries

    def run(self) -> None:  # noqa: D102
        from ..models.pricing import build_iv_surface

        try:
            res = self.market.option_chain(self.ticker,
                                           max_expiries=self.max_expiries)
            spot = res.spot if np.isfinite(res.spot) and res.spot > 0 else self.spot
            if res.frame is None or len(res.frame) == 0:
                self.done.emit(res, None, None)
                return
            tidy, pivot = build_iv_surface(res.frame, spot, self.rate,
                                           self.dividend)
            self.done.emit(res, tidy, pivot)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class BasketWorker(QThread):
    """Loads several tickers and computes the correlation structure."""

    done = pyqtSignal(object, object, object)  # frame, corr, names
    failed = pyqtSignal(str)

    def __init__(self, market, tickers: Sequence[str], period: str,
                 interval: str, parent=None) -> None:
        super().__init__(parent)
        self.market = market
        self.tickers = list(tickers)
        self.period = period
        self.interval = interval

    def run(self) -> None:  # noqa: D102
        from ..models.multiasset import align_returns, correlation_matrix

        try:
            frame, _ = self.market.basket_history(self.tickers, self.period,
                                                  self.interval)
            if frame is None or frame.empty:
                self.done.emit(None, None, [])
                return
            rets, names = align_returns(frame)
            corr = correlation_matrix(rets) if rets.size else None
            self.done.emit(frame, corr, names)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
