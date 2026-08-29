"""
Matplotlib canvases for every tab of the terminal.

Each class owns one figure and exposes a ``render(...)`` method that clears and
redraws from scratch.  Full redraws are used rather than artist updates because
the fan chart's contents change shape every batch (more paths, wider bands),
and at these figure sizes a redraw costs a few milliseconds -- far cheaper than
the bookkeeping needed to mutate artists in place.

Performance notes that matter during streaming:

* Sample paths are drawn as a single ``LineCollection`` rather than N calls to
  ``plot``.  150 individual ``Line2D`` artists would dominate the frame time;
  one collection does not.
* ``draw_idle()`` is used instead of ``draw()`` so Qt coalesces repaints when
  batches arrive faster than the screen refreshes.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import matplotlib
matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure

from .theme import PALETTE, band_colors

__all__ = [
    "ChartCanvas", "PriceChart", "FanChart", "DistributionChart",
    "OptionsChart", "DiagnosticsChart", "CorrelationChart",
]


class ChartCanvas(FigureCanvasQTAgg):
    """Base canvas: dark figure, PNG export, and a centred placeholder."""

    def __init__(self, parent=None, tight: bool = True) -> None:
        self.figure = Figure(figsize=(8, 5), dpi=100,
                             facecolor=PALETTE["panel"], layout=None)
        super().__init__(self.figure)
        if parent is not None:
            self.setParent(parent)
        self._tight = tight
        self.setMinimumHeight(220)

    # -- helpers ---------------------------------------------------------
    def clear(self) -> None:
        self.figure.clear()

    def finish(self) -> None:
        """Lay out and schedule a repaint."""
        if self._tight:
            try:
                self.figure.tight_layout(pad=1.1)
            except Exception:
                pass  # tight_layout can fail on 3D axes; not worth failing over
        self.draw_idle()

    def placeholder(self, text: str) -> None:
        """Show a centred message instead of a chart."""
        self.clear()
        ax = self.figure.add_subplot(111)
        ax.text(0.5, 0.5, text, ha="center", va="center",
                color=PALETTE["fg_faint"], fontsize=10, wrap=True)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.grid(False)
        self.finish()

    def export_png(self, path: str, dpi: int = 160) -> bool:
        """Save the current figure.  Returns False rather than raising."""
        try:
            self.figure.savefig(path, dpi=dpi, facecolor=PALETTE["panel"],
                                bbox_inches="tight")
            return True
        except Exception:
            return False


# --------------------------------------------------------------------------
# 1. price and technicals
# --------------------------------------------------------------------------
class PriceChart(ChartCanvas):
    """Price with moving averages, Bollinger bands, regime shading, RSI/MACD.

    Uses explicit gridspec margins instead of ``tight_layout``: the three
    ``sharex``-linked panes are not a layout tight_layout can solve, and it
    warns on every redraw when asked to try.  Fixed margins also keep the price
    pane from resizing as tick-label widths change between tickers.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent, tight=False)

    def render(
        self, frame, indicators: Optional[Dict[str, np.ndarray]] = None,
        regimes: Optional[np.ndarray] = None, title: str = "",
        show_bollinger: bool = True, show_ma: bool = True,
    ) -> None:
        if frame is None or len(frame) < 2:
            self.placeholder("No price history loaded.\n"
                             "Enter a ticker and press Load.")
            return
        ind = indicators or {}
        self.clear()
        gs = self.figure.add_gridspec(3, 1, height_ratios=[3.0, 0.9, 0.9],
                                      hspace=0.14, left=0.075, right=0.985,
                                      top=0.945, bottom=0.075)
        ax = self.figure.add_subplot(gs[0])
        ax_rsi = self.figure.add_subplot(gs[1], sharex=ax)
        ax_macd = self.figure.add_subplot(gs[2], sharex=ax)

        x = np.arange(len(frame))
        close = frame["close"].to_numpy(dtype=float)

        # regime shading sits behind everything else
        if regimes is not None and len(regimes) == len(close):
            self._shade_regimes(ax, x, np.asarray(regimes))

        ax.plot(x, close, color=PALETTE["fg"], lw=1.1, label="Close", zorder=3)
        if show_ma:
            for key, colour, label in (("sma_fast", PALETTE["info"], "SMA 20"),
                                       ("sma_slow", PALETTE["violet"], "SMA 50"),
                                       ("ema", PALETTE["teal"], "EMA 20")):
                if key in ind:
                    ax.plot(x, ind[key], color=colour, lw=0.9, alpha=0.85,
                            label=label, zorder=2)
        if show_bollinger and "bb_upper" in ind and "bb_lower" in ind:
            ax.plot(x, ind["bb_upper"], color=PALETTE["fg_faint"], lw=0.7,
                    ls="--", alpha=0.8, zorder=2)
            ax.plot(x, ind["bb_lower"], color=PALETTE["fg_faint"], lw=0.7,
                    ls="--", alpha=0.8, zorder=2)
            ax.fill_between(x, ind["bb_lower"], ind["bb_upper"],
                            color=PALETTE["info"], alpha=0.05, zorder=1)

        ax.set_title(title or "Price and technicals", loc="left")
        ax.set_ylabel("Price")
        ax.legend(loc="upper left", ncols=4)
        ax.tick_params(labelbottom=False)

        if "rsi" in ind:
            ax_rsi.plot(x, ind["rsi"], color=PALETTE["accent"], lw=0.9)
            ax_rsi.axhline(70, color=PALETTE["down"], lw=0.6, ls="--", alpha=0.7)
            ax_rsi.axhline(30, color=PALETTE["up"], lw=0.6, ls="--", alpha=0.7)
            ax_rsi.set_ylim(0, 100)
            ax_rsi.set_yticks([30, 70])
        ax_rsi.set_ylabel("RSI", fontsize=8)
        ax_rsi.tick_params(labelbottom=False)

        if "macd" in ind and "macd_signal" in ind:
            hist = ind.get("macd_hist", ind["macd"] - ind["macd_signal"])
            colors = np.where(np.nan_to_num(hist) >= 0, PALETTE["up"], PALETTE["down"])
            ax_macd.bar(x, hist, color=colors, width=1.0, alpha=0.55)
            ax_macd.plot(x, ind["macd"], color=PALETTE["info"], lw=0.9)
            ax_macd.plot(x, ind["macd_signal"], color=PALETTE["accent"], lw=0.9)
        ax_macd.set_ylabel("MACD", fontsize=8)

        self._date_axis(ax_macd, frame)
        self.finish()

    @staticmethod
    def _shade_regimes(ax, x: np.ndarray, regimes: np.ndarray) -> None:
        """Shade contiguous runs of the high-volatility regime."""
        mask = np.asarray(regimes) > 0
        if not mask.any():
            return
        edges = np.flatnonzero(np.diff(mask.astype(int)))
        starts = [0] if mask[0] else []
        ends: List[int] = []
        for e in edges:
            (ends if mask[e] else starts).append(int(e) + 1)
        if mask[-1]:
            ends.append(len(mask))
        for s, e in zip(starts, ends):
            ax.axvspan(x[s], x[min(e, len(x) - 1)], color=PALETTE["down"],
                       alpha=0.09, lw=0, zorder=0)

    @staticmethod
    def _date_axis(ax, frame, n_ticks: int = 7) -> None:
        """Label the shared x-axis with dates rather than integer positions."""
        n = len(frame)
        step = max(1, n // n_ticks)
        pos = np.arange(0, n, step)
        try:
            labels = [frame.index[int(p)].strftime("%Y-%m") for p in pos]
        except Exception:
            labels = [str(int(p)) for p in pos]
        ax.set_xticks(pos)
        ax.set_xticklabels(labels, rotation=0)


# --------------------------------------------------------------------------
# 2. Monte Carlo fan
# --------------------------------------------------------------------------
class FanChart(ChartCanvas):
    """Sample paths behind shaded percentile ribbons."""

    def render(
        self, result, n_sample_paths: int = 150,
        bands: Sequence[float] = (5, 25, 50, 75, 95),
        target: Optional[float] = None, barrier: Optional[float] = None,
        title: str = "",
    ) -> None:
        if result is None or result.fan_paths.size == 0:
            self.placeholder("No simulation yet.\nPress Run to start.")
            return
        self.clear()
        ax = self.figure.add_subplot(111)
        paths = result.fan_paths
        t = np.arange(paths.shape[1])
        s0 = float(result.request.s0)

        # sample paths first, so the ribbons read on top of them
        n_show = int(min(max(0, n_sample_paths), paths.shape[0]))
        if n_show:
            idx = np.linspace(0, paths.shape[0] - 1, n_show).astype(int)
            segs = [np.column_stack([t, paths[i]]) for i in idx]
            ax.add_collection(LineCollection(
                segs, colors=PALETTE["info"], linewidths=0.35, alpha=0.13,
                zorder=1))

        band_map = result.bands(bands)
        levels = sorted(band_map)
        pairs = [(levels[i], levels[-(i + 1)])
                 for i in range(len(levels) // 2)]
        colours = band_colors(len(pairs))
        for (lo, hi), colour in zip(pairs, colours):
            ax.fill_between(t, band_map[lo], band_map[hi], color=colour,
                            alpha=0.55, lw=0, zorder=2,
                            label=f"{lo:g}-{hi:g}%")
        if 50.0 in band_map:
            ax.plot(t, band_map[50.0], color=PALETTE["accent"], lw=1.4,
                    zorder=4, label="Median")

        ax.axhline(s0, color=PALETTE["fg_faint"], lw=0.8, ls=":", zorder=3,
                   label=f"Spot {s0:,.2f}")
        if target is not None and np.isfinite(target) and target > 0:
            ax.axhline(target, color=PALETTE["up"], lw=0.9, ls="--", zorder=3,
                       label=f"Target {target:,.2f}")
        if barrier is not None and np.isfinite(barrier) and barrier > 0:
            ax.axhline(barrier, color=PALETTE["warn"], lw=0.9, ls="--",
                       zorder=3, label=f"Barrier {barrier:,.2f}")

        ax.set_xlim(0, max(1, paths.shape[1] - 1))
        ax.set_xlabel("Trading days ahead")
        ax.set_ylabel("Price")
        ax.set_title(title or "Monte Carlo fan", loc="left")
        ax.legend(loc="upper left", ncols=3, fontsize=7.5)
        self.finish()


# --------------------------------------------------------------------------
# 3. terminal distribution
# --------------------------------------------------------------------------
class DistributionChart(ChartCanvas):
    """Terminal-price histogram with a fitted density and percentile markers."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, tight=False)

    def render(self, result, n_bins: int = 90, target: Optional[float] = None,
               title: str = "") -> None:
        if result is None or result.terminal.size < 10:
            self.placeholder("No simulation yet.\nPress Run to start.")
            return
        from scipy import stats as sps

        self.clear()
        gs = self.figure.add_gridspec(2, 1, height_ratios=[2.4, 1.0], hspace=0.32,
                                      left=0.085, right=0.98, top=0.94,
                                      bottom=0.085)
        ax = self.figure.add_subplot(gs[0])
        ax_conv = self.figure.add_subplot(gs[1])

        term = result.terminal
        s0 = float(result.request.s0)
        ax.hist(term, bins=n_bins, color=PALETTE["info"], alpha=0.45,
                density=True, edgecolor="none", label="Simulated")

        # lognormal reference fitted to the simulated sample
        try:
            lg = np.log(term[term > 0])
            mu_l, sd_l = float(lg.mean()), float(lg.std(ddof=1))
            grid = np.linspace(max(term.min(), 1e-9), term.max(), 400)
            pdf = sps.lognorm.pdf(grid, s=sd_l, scale=np.exp(mu_l))
            ax.plot(grid, pdf, color=PALETTE["accent"], lw=1.3,
                    label="Fitted lognormal")
        except Exception:
            pass

        summary = result.summary()
        for key, colour, style, label in (
            ("p5", PALETTE["down"], "--", "5%"),
            ("p50", PALETTE["fg"], "-", "Median"),
            ("p95", PALETTE["up"], "--", "95%"),
        ):
            if key in summary:
                ax.axvline(summary[key], color=colour, lw=0.9, ls=style,
                           alpha=0.9, label=f"{label} {summary[key]:,.2f}")
        ax.axvline(s0, color=PALETTE["fg_faint"], lw=0.9, ls=":",
                   label=f"Spot {s0:,.2f}")
        if target is not None and np.isfinite(target) and target > 0:
            ax.axvline(target, color=PALETTE["violet"], lw=0.9, ls="-.",
                       label=f"Target {target:,.2f}")

        ax.set_xlabel("Terminal price")
        ax.set_ylabel("Density")
        ax.set_title(title or "Terminal price distribution", loc="left")
        ax.legend(loc="upper right", fontsize=7.5, ncols=2)

        counts, means, se = result.convergence()
        if counts.size:
            ax_conv.plot(counts, means, color=PALETTE["accent"], lw=1.1,
                         label="Running mean")
            ax_conv.fill_between(counts, means - 2 * se, means + 2 * se,
                                 color=PALETTE["accent"], alpha=0.18,
                                 lw=0, label="+/- 2 standard errors")
            ax_conv.axhline(float(means[-1]), color=PALETTE["fg_faint"],
                            lw=0.7, ls=":")
            ax_conv.set_xscale("log")
            ax_conv.set_xlabel("Paths simulated")
            ax_conv.set_ylabel("Mean")
            ax_conv.set_title("Convergence", loc="left", fontsize=9)
            ax_conv.legend(loc="upper right", fontsize=7)
        self.finish()


# --------------------------------------------------------------------------
# 4. options / implied vol
# --------------------------------------------------------------------------
class OptionsChart(ChartCanvas):
    """Implied-vol smile, term structure and 3D surface.

    ``tight_layout`` is disabled here: it cannot handle a 3D axes and emits a
    UserWarning on every redraw.  The gridspec below sets its own margins.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent, tight=False)

    def render(self, tidy, pivot, spot: float, title: str = "") -> None:
        if tidy is None or len(tidy) == 0:
            self.placeholder(
                "No option chain available.\n\n"
                "Press Load Chain. Names without listed options, and offline\n"
                "runs with no cached chain, will stay empty."
            )
            return
        self.clear()
        gs = self.figure.add_gridspec(2, 2, hspace=0.34, wspace=0.24,
                                      left=0.07, right=0.97, top=0.93,
                                      bottom=0.06)
        ax_smile = self.figure.add_subplot(gs[0, 0])
        ax_term = self.figure.add_subplot(gs[0, 1])
        ax_surf = self.figure.add_subplot(gs[1, :], projection="3d")

        expiries = sorted(tidy["expiry_years"].unique())
        palette = [PALETTE["accent"], PALETTE["info"], PALETTE["up"],
                   PALETTE["violet"], PALETTE["pink"], PALETTE["teal"]]
        for i, exp in enumerate(expiries[:6]):
            sub = tidy[tidy["expiry_years"] == exp].sort_values("moneyness")
            ax_smile.plot(sub["moneyness"], sub["iv"] * 100,
                          color=palette[i % len(palette)], lw=1.0, marker="o",
                          ms=2.2, label=f"{exp*365:.0f}d")
        ax_smile.axvline(1.0, color=PALETTE["fg_faint"], lw=0.7, ls=":")
        # Very short-dated deep-OTM contracts genuinely trade at three-digit
        # implied vols.  Those points are real and stay plotted, but letting
        # them set the y-range squashes the rest of the surface into a flat
        # line, so the axis is clipped to the bulk of the distribution.
        ivs = tidy["iv"].to_numpy(dtype=float) * 100.0
        ivs = ivs[np.isfinite(ivs)]
        if ivs.size:
            top = float(np.percentile(ivs, 97)) * 1.20
            if top > 0 and top < float(ivs.max()):
                ax_smile.set_ylim(max(0.0, float(ivs.min()) * 0.85), top)
        ax_smile.set_xlabel("Moneyness  K / S")
        ax_smile.set_ylabel("Implied vol  %")
        ax_smile.set_title("Smile by expiry", loc="left", fontsize=9)
        ax_smile.legend(fontsize=7, ncols=2)

        atm = tidy.iloc[(tidy["moneyness"] - 1.0).abs().argsort()[:60]]
        term = atm.groupby("expiry_years")["iv"].mean().sort_index()
        if len(term) > 1:
            ax_term.plot(term.index * 365, term.to_numpy() * 100,
                         color=PALETTE["accent"], lw=1.2, marker="o", ms=3)
        ax_term.set_xlabel("Days to expiry")
        ax_term.set_ylabel("ATM implied vol  %")
        ax_term.set_title("Term structure (near-ATM)", loc="left", fontsize=9)

        if pivot is not None and pivot.shape[0] >= 2 and pivot.shape[1] >= 2:
            grid = pivot.interpolate(axis=1, limit_direction="both")
            X, Y = np.meshgrid(grid.columns.to_numpy(dtype=float),
                               grid.index.to_numpy(dtype=float) * 365.0)
            Z = grid.to_numpy(dtype=float) * 100.0
            ok = np.isfinite(Z)
            if ok.sum() > 8:
                Z = np.where(ok, Z, np.nanmean(Z))
                ax_surf.plot_surface(X, Y, Z, cmap="viridis", edgecolor="none",
                                     alpha=0.92, rstride=1, cstride=1)
                ax_surf.set_xlabel("Strike", fontsize=8, labelpad=-2)
                ax_surf.set_ylabel("Days", fontsize=8, labelpad=-2)
                ax_surf.set_zlabel("IV %", fontsize=8, labelpad=-2)
                ax_surf.view_init(elev=24, azim=-125)
        ax_surf.set_title("Implied volatility surface", loc="left", fontsize=9)
        ax_surf.set_facecolor(PALETTE["panel"])
        for pane in (ax_surf.xaxis, ax_surf.yaxis, ax_surf.zaxis):
            pane.set_pane_color((0.07, 0.09, 0.13, 1.0))
            pane._axinfo["grid"]["color"] = PALETTE["grid"]
        ax_surf.tick_params(labelsize=6.5)

        if title:
            self.figure.suptitle(title, color=PALETTE["fg"], fontsize=10,
                                 x=0.01, ha="left")
        self.finish()


# --------------------------------------------------------------------------
# 5. return diagnostics
# --------------------------------------------------------------------------
class DiagnosticsChart(ChartCanvas):
    """Return series, rolling vol estimators, ACF, QQ plot and the vol cone."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, tight=False)

    def render(self, returns: np.ndarray, vols: Dict[str, np.ndarray],
               acf_values: Optional[Tuple[np.ndarray, float]] = None,
               cone_rows: Optional[list] = None, title: str = "") -> None:
        r = np.asarray(returns, dtype=float)
        r = r[np.isfinite(r)]
        if r.size < 30:
            self.placeholder("Not enough history for diagnostics.\n"
                             "Load at least 30 bars.")
            return
        from scipy import stats as sps

        self.clear()
        gs = self.figure.add_gridspec(2, 3, hspace=0.38, wspace=0.30,
                                      left=0.06, right=0.98, top=0.90,
                                      bottom=0.09)
        ax_ret = self.figure.add_subplot(gs[0, 0])
        ax_vol = self.figure.add_subplot(gs[0, 1])
        ax_acf = self.figure.add_subplot(gs[0, 2])
        ax_qq = self.figure.add_subplot(gs[1, 0])
        ax_hist = self.figure.add_subplot(gs[1, 1])
        ax_cone = self.figure.add_subplot(gs[1, 2])

        ax_ret.plot(r * 100, color=PALETTE["info"], lw=0.5)
        ax_ret.axhline(0, color=PALETTE["fg_faint"], lw=0.6)
        ax_ret.set_title("Log returns %", loc="left", fontsize=9)

        colours = {"realized": PALETTE["accent"], "ewma": PALETTE["info"],
                   "parkinson": PALETTE["up"], "garman_klass": PALETTE["violet"]}
        for name, series in (vols or {}).items():
            s = np.asarray(series, dtype=float)
            if s.size and np.isfinite(s).any():
                ax_vol.plot(s * 100, lw=0.8, alpha=0.9,
                            color=colours.get(name, PALETTE["fg_dim"]),
                            label=name.replace("_", "-"))
        ax_vol.set_title("Annualised volatility %", loc="left", fontsize=9)
        ax_vol.legend(fontsize=6.5, ncols=2)

        if acf_values is not None and len(acf_values[0]):
            vals, band = acf_values
            lags = np.arange(len(vals))
            ax_acf.bar(lags[1:], vals[1:], color=PALETTE["info"], width=0.8)
            ax_acf.axhline(band, color=PALETTE["down"], lw=0.7, ls="--")
            ax_acf.axhline(-band, color=PALETTE["down"], lw=0.7, ls="--")
            ax_acf.axhline(0, color=PALETTE["fg_faint"], lw=0.6)
        ax_acf.set_title("ACF of returns (95% band)", loc="left", fontsize=9)

        probs = (np.arange(1, r.size + 1) - 0.375) / (r.size + 0.25)
        theo = sps.norm.ppf(probs)
        ordered = np.sort(r)
        ax_qq.scatter(theo, ordered * 100, s=2.0, color=PALETTE["info"],
                      alpha=0.55, edgecolors="none")
        q_s = np.percentile(r, [25, 75])
        q_t = sps.norm.ppf([0.25, 0.75])
        slope = (q_s[1] - q_s[0]) / (q_t[1] - q_t[0])
        icept = q_s[0] - slope * q_t[0]
        ax_qq.plot(theo, (slope * theo + icept) * 100, color=PALETTE["accent"],
                   lw=1.0)
        ax_qq.set_title("QQ vs normal", loc="left", fontsize=9)
        ax_qq.set_xlabel("Theoretical", fontsize=8)

        ax_hist.hist(r * 100, bins=70, density=True, color=PALETTE["info"],
                     alpha=0.5, edgecolor="none")
        grid = np.linspace(r.min(), r.max(), 300)
        ax_hist.plot(grid * 100, sps.norm.pdf(grid, r.mean(), r.std()) / 100,
                     color=PALETTE["accent"], lw=1.1, label="Normal")
        try:
            df, loc, scale = sps.t.fit(r)
            ax_hist.plot(grid * 100, sps.t.pdf(grid, df, loc, scale) / 100,
                         color=PALETTE["up"], lw=1.1, label=f"t (df={df:.1f})")
        except Exception:
            pass
        ax_hist.set_title("Return density", loc="left", fontsize=9)
        ax_hist.legend(fontsize=7)

        if cone_rows:
            xs = [row.window for row in cone_rows]
            for attr, colour, alpha, label in (
                ("p_max", PALETTE["fg_faint"], 0.6, "max"),
                ("p90", PALETTE["down"], 0.8, "90%"),
                ("median", PALETTE["fg"], 0.9, "median"),
                ("p10", PALETTE["up"], 0.8, "10%"),
                ("p_min", PALETTE["fg_faint"], 0.6, "min"),
            ):
                ax_cone.plot(xs, [getattr(row, attr) * 100 for row in cone_rows],
                             color=colour, lw=0.8, alpha=alpha, label=label)
            ax_cone.plot(xs, [row.current * 100 for row in cone_rows],
                         color=PALETTE["accent"], lw=1.6, marker="o", ms=3,
                         label="current")
            ax_cone.set_xscale("log")
            ax_cone.set_xticks(xs)
            ax_cone.set_xticklabels([str(x) for x in xs], fontsize=7)
            ax_cone.legend(fontsize=6.5, ncols=2)
        ax_cone.set_title("Realised vol cone %", loc="left", fontsize=9)
        ax_cone.set_xlabel("Window (days)", fontsize=8)

        if title:
            self.figure.suptitle(title, color=PALETTE["fg"], fontsize=10,
                                 x=0.01, ha="left")
        self.finish()


# --------------------------------------------------------------------------
# 6. correlation
# --------------------------------------------------------------------------
class CorrelationChart(ChartCanvas):
    """Correlation heatmap plus the correlated-basket simulation outcome."""

    def render(self, corr: np.ndarray, names: Sequence[str],
               basket=None, title: str = "") -> None:
        if corr is None or np.asarray(corr).size == 0 or not len(names):
            self.placeholder(
                "No basket loaded.\n\n"
                "Enter comma-separated tickers in the Basket panel\n"
                "and press Analyse Basket."
            )
            return
        self.clear()
        c = np.asarray(corr, dtype=float)
        has_basket = basket is not None and basket.portfolio_paths.size
        if has_basket:
            gs = self.figure.add_gridspec(1, 2, width_ratios=[1.05, 1.0],
                                          wspace=0.26)
            ax = self.figure.add_subplot(gs[0])
            ax_sim = self.figure.add_subplot(gs[1])
        else:
            ax = self.figure.add_subplot(111)
            ax_sim = None

        im = ax.imshow(c, cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
        ax.set_xticks(range(len(names)))
        ax.set_yticks(range(len(names)))
        ax.set_xticklabels(names, rotation=45, ha="right", fontsize=7.5)
        ax.set_yticklabels(names, fontsize=7.5)
        n = len(names)
        if n <= 14:  # annotations become unreadable past this
            for i in range(n):
                for j in range(n):
                    val = c[i, j]
                    ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                            fontsize=6.5,
                            color="#101010" if abs(val) > 0.45 else PALETTE["fg"])
        ax.grid(False)
        ax.set_title(title or "Return correlation", loc="left", fontsize=9)
        cb = self.figure.colorbar(im, ax=ax, fraction=0.042, pad=0.03)
        cb.ax.tick_params(labelsize=7, colors=PALETTE["fg_faint"])
        cb.outline.set_edgecolor(PALETTE["border"])

        if ax_sim is not None:
            port = basket.portfolio_paths
            t = np.arange(port.shape[1])
            qs = np.percentile(port, [5, 25, 50, 75, 95], axis=0)
            ax_sim.fill_between(t, qs[0], qs[4], color=band_colors(2)[0],
                                alpha=0.55, lw=0, label="5-95%")
            ax_sim.fill_between(t, qs[1], qs[3], color=band_colors(2)[1],
                                alpha=0.6, lw=0, label="25-75%")
            ax_sim.plot(t, qs[2], color=PALETTE["accent"], lw=1.3,
                        label="Median")
            ax_sim.axhline(1.0, color=PALETTE["fg_faint"], lw=0.8, ls=":")
            ax_sim.set_title("Correlated basket, rebalanced to weights",
                             loc="left", fontsize=9)
            ax_sim.set_xlabel("Trading days ahead")
            ax_sim.set_ylabel("Portfolio value (start = 1.0)")
            ax_sim.legend(fontsize=7)
        self.finish()
