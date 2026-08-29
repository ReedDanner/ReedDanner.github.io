"""
The terminal window: top bar, parameter panel, chart tabs and live stat tables.

Layout
------
    +--------------------------------------------------------------+
    |  ticker  period  interval | price  chg | LED | Run Cancel ... |  top bar
    +-----------+------------------------------------+-------------+
    |  model    |  Price | Fan | Distribution | ...   |  statistics |
    |  params   |                                     |  risk       |
    |  targets  |          chart area (tabs)          |  sizing     |
    |  options  |                                     |             |
    |  basket   |                                     |             |
    +-----------+------------------------------------+-------------+
    |  status bar: data source, cache age, last action              |
    +--------------------------------------------------------------+

Everything slow runs in a worker (see :mod:`quantmc.ui.workers`); this module
only builds widgets and reacts to signals.
"""

from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStatusBar, QTabWidget, QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, export_dir
from ..data import (Health, INTERVALS, MarketData, PERIODS, default_provider,
                    interval_to_dt)
from ..engine import SimRequest, SimResult
from ..models import calibration as cal
from ..models import multiasset as ma
from ..models import paths as pathmod
from ..models import pricing as pricing
from ..models import risk as riskmod
from ..models import stats as statmod
from ..models import technicals as tech
from .charts import (
    CorrelationChart, DiagnosticsChart, DistributionChart, FanChart,
    OptionsChart, PriceChart,
)
from .panels import (
    CollapsibleSection, MetricStrip, NumField, ParamGrid, StatTable, StatusLED,
    TabInfoBar, fmt_money, fmt_num, fmt_pct, with_info_bar,
)
from .theme import PALETTE, STYLESHEET, apply_mpl_theme, sign_color
from .workers import (
    BasketWorker, CallableWorker, ChainWorker, DataWorker, SimulationWorker,
)

__all__ = ["MainWindow", "launch"]

TRADING_DAYS = 252.0


class MainWindow(QMainWindow):
    """The application window."""

    def __init__(self, config: AppConfig, market: MarketData, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.market = market

        # -- live state ---------------------------------------------------
        self.history = None            # HistoryResult
        self.returns = np.array([])    # log returns of the loaded series
        self.spot = float("nan")
        self.result: Optional[SimResult] = None
        self.chain_tidy = None
        self.chain_pivot = None
        self._chain_ticker = ""      # symbol the loaded chain belongs to
        self._chain_loading = False
        self.basket_corr = None
        self.basket_names: List[str] = []
        self.basket_result = None
        self.hmm_regimes: Optional[np.ndarray] = None
        self.dist_fits: List = []
        self._workers: List = []       # keeps QThreads alive
        self._sim: Optional[SimulationWorker] = None
        self._run_started = 0.0

        self.setWindowTitle("QuantMC  --  Monte Carlo & Quantitative Modelling Terminal")
        self.setStyleSheet(STYLESHEET)

        self._build_ui()
        self._restore_geometry()
        self._install_shortcuts()
        self._on_model_changed(initial=True)
        self._show_initial_placeholders()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        QTimer.singleShot(120, self._load_ticker)

    # ==================================================================
    # construction
    # ==================================================================
    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 4)
        outer.setSpacing(5)

        outer.addWidget(self._build_topbar())
        self.banner = self._build_banner()
        outer.addWidget(self.banner)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_left_panel())
        split.addWidget(self._build_center())
        split.addWidget(self._build_right_panel())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([310, 900, 330])
        self.main_split = split
        outer.addWidget(split, 1)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    # -- top bar -------------------------------------------------------
    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background: {PALETTE['panel']}; "
            f"border: 1px solid {PALETTE['border']}; border-radius: 3px; }}"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(9)

        self.ticker_edit = QLineEdit(self.config.ticker)
        self.ticker_edit.setProperty("role", "ticker")
        self.ticker_edit.setFixedWidth(112)
        self.ticker_edit.setPlaceholderText("TICKER")
        self.ticker_edit.returnPressed.connect(self._load_ticker)
        # Typing a symbol does not load it.  Without this, the box can read
        # NVDA while every number on screen still belongs to the previously
        # loaded ticker -- the most dangerous failure mode in the whole app,
        # because nothing about the numbers looks wrong.
        self.ticker_edit.textChanged.connect(self._on_ticker_typed)
        row.addWidget(self.ticker_edit)

        self.pending_label = QLabel("")
        self.pending_label.setStyleSheet(
            f"color: {PALETTE['warn']}; font-size: 10px; font-weight: 700;")
        self.pending_label.setVisible(False)
        row.addWidget(self.pending_label)

        self.period_combo = QComboBox()
        self.period_combo.addItems(list(PERIODS))
        self.period_combo.setCurrentText(self.config.period)
        self.period_combo.setFixedWidth(66)
        self.period_combo.currentTextChanged.connect(lambda _: self._load_ticker())
        row.addWidget(self.period_combo)

        self.interval_combo = QComboBox()
        self.interval_combo.addItems(list(INTERVALS))
        self.interval_combo.setCurrentText(self.config.interval)
        self.interval_combo.setFixedWidth(62)
        self.interval_combo.currentTextChanged.connect(lambda _: self._load_ticker())
        row.addWidget(self.interval_combo)

        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._load_ticker)
        load_btn.setToolTip("Reload from the provider (F5), bypassing the cache")
        row.addWidget(load_btn)

        row.addWidget(self._vline())
        self.metrics = MetricStrip(["last", "change", "ann vol", "bars",
                                    "est. price"])
        row.addWidget(self.metrics, 1)

        row.addWidget(self._vline())
        self.led = StatusLED()
        row.addWidget(self.led)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(190)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFormat("idle")
        row.addWidget(self.progress)

        self.run_btn = QPushButton("Run")
        self.run_btn.setProperty("role", "primary")
        self.run_btn.setFixedWidth(64)
        self.run_btn.setToolTip("Run the Monte Carlo simulation  (Ctrl+R)")
        self.run_btn.clicked.connect(self._run_simulation)
        row.addWidget(self.run_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("role", "danger")
        self.cancel_btn.setFixedWidth(64)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setToolTip("Stop the running simulation  (Esc)")
        self.cancel_btn.clicked.connect(self._cancel_simulation)
        row.addWidget(self.cancel_btn)

        reset_btn = QPushButton("Reset")
        reset_btn.setFixedWidth(58)
        reset_btn.setToolTip("Clear results and restore default parameters")
        reset_btn.clicked.connect(self._reset)
        row.addWidget(reset_btn)
        return bar

    def _build_banner(self) -> QLabel:
        banner = QLabel("")
        banner.setWordWrap(True)
        banner.setVisible(False)
        banner.setStyleSheet(
            f"QLabel {{ background: #2a1418; color: {PALETTE['down']}; "
            f"border: 1px solid {PALETTE['down']}; border-radius: 3px; "
            f"padding: 4px 8px; font-size: 11px; }}"
        )
        return banner

    @staticmethod
    def _vline() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setStyleSheet(f"color: {PALETTE['border']};")
        line.setFixedWidth(1)
        return line

    # -- left panel ----------------------------------------------------
    def _build_left_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(292)
        scroll.setMaximumWidth(400)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(2, 0, 4, 0)
        col.setSpacing(0)

        # --- model ---
        sec_model = CollapsibleSection("Model")
        self.model_combo = QComboBox()
        for key, label in pathmod.MODEL_LABELS.items():
            self.model_combo.addItem(label, key)
        idx = self.model_combo.findData(self.config.model)
        self.model_combo.setCurrentIndex(max(0, idx))
        self.model_combo.currentIndexChanged.connect(lambda _: self._on_model_changed())
        sec_model.add(self.model_combo)
        self.model_note = QLabel("")
        self.model_note.setWordWrap(True)
        self.model_note.setStyleSheet(
            f"color: {PALETTE['fg_faint']}; font-size: 10px; padding: 2px 0;")
        sec_model.add(self.model_note)
        col.addWidget(sec_model)

        # --- simulation ---
        sec_sim = CollapsibleSection("Simulation")
        self.f_horizon = NumField("horizon (days)", self.config.horizon_days,
                                  "Number of trading steps to simulate forward")
        self.f_paths = NumField("paths", self.config.n_paths,
                                "Number of independent sample paths")
        self.f_seed = NumField("seed", self.config.seed,
                               "RNG seed; same seed + same batch size = "
                               "identical results")
        self.chk_seed = QCheckBox("Use fixed seed (reproducible)")
        self.chk_seed.setChecked(self.config.use_seed)
        self.chk_anti = QCheckBox("Antithetic variates")
        self.chk_anti.setChecked(self.config.antithetic)
        self.chk_anti.setToolTip(
            "Pair each shock with its negation: same distribution, lower "
            "variance of the estimate")
        self.f_batch = NumField("batch size", self.config.batch_size,
                                "Paths per batch. Smaller = smoother streaming "
                                "and faster cancel; larger = slightly faster")
        self.f_fan = NumField("fan paths drawn", self.config.fan_sample_paths,
                              "Individual paths drawn behind the percentile "
                              "ribbons (display only)")
        for w in (self.f_horizon, self.f_paths, self.f_seed, self.chk_seed,
                  self.chk_anti, self.f_batch, self.f_fan):
            sec_sim.add(w)
        col.addWidget(sec_sim)

        # --- model parameters ---
        sec_params = CollapsibleSection("Model parameters")
        self.param_grid = ParamGrid()
        sec_params.add(self.param_grid)
        self.f_lookback = NumField("calib. lookback", self.config.calibration_lookback,
                                   "Number of most recent bars used by "
                                   "Calibrate from history")
        sec_params.add(self.f_lookback)
        calib_btn = QPushButton("Calibrate from history")
        calib_btn.setToolTip(
            "Estimate this model's parameters from the loaded price history "
            "and write them into the fields above")
        calib_btn.clicked.connect(self._calibrate)
        sec_params.add(calib_btn)
        self.calib_note = QLabel("")
        self.calib_note.setWordWrap(True)
        self.calib_note.setStyleSheet(
            f"color: {PALETTE['fg_faint']}; font-size: 10px;")
        sec_params.add(self.calib_note)
        col.addWidget(sec_params)

        # --- probability targets ---
        sec_targets = CollapsibleSection("Probability targets", expanded=False)
        self.f_target = NumField("target price", self.config.target_price,
                                 "P(terminal price above this level). "
                                 "0 = 110% of spot")
        self.f_barrier = NumField("barrier", self.config.barrier,
                                  "P(touched at any step). 0 = 120% of spot")
        self.barrier_dir = QComboBox()
        self.barrier_dir.addItems(["up", "down"])
        self.barrier_dir.setCurrentText(self.config.barrier_direction)
        self.f_ruin = NumField("ruin level (% spot)", self.config.ruin_pct,
                               "P(price ever falls to this percentage of spot)")
        self.f_rate = NumField("risk-free rate", self.config.risk_free,
                               "Annual continuously compounded rate, e.g. 0.04")
        for w in (self.f_target, self.f_barrier, self.barrier_dir, self.f_ruin,
                  self.f_rate):
            sec_targets.add(w)
        col.addWidget(sec_targets)

        # --- options ---
        sec_opt = CollapsibleSection("Options", expanded=False)
        self.f_strike = NumField("strike", self.config.opt_strike,
                                 "0 = at the money")
        self.f_opt_days = NumField("days to expiry", self.config.opt_days)
        self.opt_kind = QComboBox()
        self.opt_kind.addItems(["call", "put"])
        self.opt_kind.setCurrentText(self.config.opt_kind)
        self.f_opt_vol = NumField("volatility", self.config.opt_vol,
                                  "Annualised; 0 = use the model's sigma")
        self.f_div = NumField("dividend yield", self.config.opt_dividend)
        self.opt_style = QComboBox()
        self.opt_style.addItems(list(pricing.EXOTIC_STYLES))
        self.opt_style.setCurrentText(self.config.opt_style)
        self.f_opt_barrier = NumField("exotic barrier", self.config.opt_barrier,
                                      "Barrier level for barrier payoffs")
        self.f_tree = NumField("tree steps", self.config.opt_tree_steps)
        self.f_opt_paths = NumField("MC paths", self.config.opt_mc_paths)
        for w in (self.f_strike, self.f_opt_days, self.opt_kind, self.f_opt_vol,
                  self.f_div, self.opt_style, self.f_opt_barrier, self.f_tree,
                  self.f_opt_paths):
            sec_opt.add(w)
        price_btn = QPushButton("Price options")
        price_btn.setToolTip("Black-Scholes, trees, Monte Carlo and the exotic "
                             "payoff, all at once")
        price_btn.clicked.connect(self._price_options)
        sec_opt.add(price_btn)
        chain_btn = QPushButton("Load option chain")
        chain_btn.clicked.connect(self._load_chain)
        sec_opt.add(chain_btn)
        col.addWidget(sec_opt)

        # --- basket ---
        sec_basket = CollapsibleSection("Basket / correlation", expanded=False)
        self.basket_edit = QLineEdit(", ".join(self.config.basket))
        self.basket_edit.setPlaceholderText("SPY, QQQ, TLT, GLD")
        sec_basket.add(self.basket_edit)
        basket_btn = QPushButton("Analyse basket")
        basket_btn.clicked.connect(self._analyse_basket)
        sec_basket.add(basket_btn)
        self.basket_note = QLabel("")
        self.basket_note.setWordWrap(True)
        self.basket_note.setStyleSheet(
            f"color: {PALETTE['fg_faint']}; font-size: 10px;")
        sec_basket.add(self.basket_note)
        col.addWidget(sec_basket)

        # --- export ---
        sec_export = CollapsibleSection("Export", expanded=False)
        for label, slot, tip in (
            ("Save chart as PNG", self._export_chart,
             "Save the visible chart tab"),
            ("Save tables as CSV", self._export_tables,
             "Save the statistics, risk and sizing tables"),
            ("Export full run", self._export_run,
             "Timestamped CSV + JSON of parameters and all summary statistics"),
        ):
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            sec_export.add(btn)
        col.addWidget(sec_export)

        col.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    #: Short explainers shown by the collapsible "About this tab" strip at the
    #: bottom of every tab.  Kept factual about what the numbers mean and where
    #: they mislead, rather than describing the widgets.
    _TAB_INFO = {
        "price": (
            "Price & Technicals",
            "Adjusted closing price with SMA(20)/SMA(50)/EMA(20), Bollinger "
            "bands (20, 2σ), RSI(14) and MACD(12,26,9). Red shading marks the "
            "high-volatility state of a 2-state Gaussian hidden Markov model "
            "fitted to the returns — it is a description of the past, not a "
            "signal.  Prices are dividend- and split-adjusted, which is right "
            "for return and volatility estimation but means the level will not "
            "match a broker's quote on a dividend payer.  Indicators are "
            "descriptive summaries of past prices; none carries predictive "
            "content on its own."
        ),
        "fan": (
            "Monte Carlo Fan",
            "Simulated price paths under the model and parameters in the left "
            "panel. Shaded ribbons are the 5–95% and 25–75% pointwise "
            "percentiles; the amber line is the median.  Important: these are "
            "*pointwise* quantiles, so the 5–95% region is NOT a 90% band for "
            "whole paths — the chance a path stays inside it the entire "
            "horizon is far lower.  Ribbons come from a reservoir of up to "
            "4,000 retained paths, while the statistics on the right use every "
            "path simulated."
        ),
        "distribution": (
            "Distribution",
            "Top: the terminal-price histogram with a lognormal fitted to the "
            "simulated sample, plus spot, median and the 5/95% marks.  Bottom: "
            "the convergence diagnostic — the running mean with its ±2 "
            "standard-error envelope against path count on a log axis.  When "
            "the mean has settled inside a narrow envelope the run has "
            "converged *for the mean*; tail percentiles converge far more "
            "slowly, because the 99% number is estimated from only 1% of the "
            "paths."
        ),
        "options": (
            "Options / IV",
            "Left: the implied-volatility smile by expiry, the near-ATM term "
            "structure, and the 3D surface, all solved from live chain mid "
            "prices with Brent's method.  Right: Black-Scholes-Merton price "
            "and Greeks, binomial/trinomial lattices (European and American), "
            "a Monte Carlo price with its error against the closed form, and "
            "the selected exotic payoff.  Caveats: listed US single-stock "
            "options are American but the IV solver is European, so "
            "early-exercise premium is misread as volatility (small for OTM "
            "calls, larger for deep ITM puts); and exotics are monitored "
            "discretely, which makes knock-outs worth more and touch "
            "probabilities lower than continuous monitoring."
        ),
        "diagnostics": (
            "Diagnostics",
            "Whether the loaded returns actually satisfy the assumptions your "
            "chosen model makes.  Charts: return series, four volatility "
            "estimators (realised, EWMA, Parkinson, Garman-Klass), the ACF "
            "with its 95% white-noise band, a QQ plot against the normal, "
            "fitted densities, and the realised-volatility cone.  Tests: "
            "Jarque-Bera for normality, ADF for a unit root (prices should NOT "
            "reject; returns should), and Ljung-Box on squared returns for "
            "volatility clustering.  The AIC ranking suggests which return "
            "distribution fits best — if Student-t wins decisively, GBM is "
            "understating your tail risk."
        ),
        "correlation": (
            "Correlation",
            "Pearson correlation of the basket's log returns, with a "
            "Cholesky-driven correlated simulation of the equal-weight "
            "portfolio (continuously rebalanced, so not buy-and-hold).  Two "
            "limits worth holding in mind: correlation is estimated on a "
            "single common window and is not robust to outliers, and the "
            "simulation assumes Gaussian dependence — constant through time "
            "with no tail dependence.  Real equity correlations rise toward 1 "
            "in a crash, exactly when diversification is needed, so basket "
            "downside here is understated."
        ),
    }

    def _build_center(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.price_chart = PriceChart()
        self.tabs.addTab(with_info_bar(self.price_chart, *self._TAB_INFO["price"]),
                         "Price && Technicals")

        self.fan_chart = FanChart()
        self.tabs.addTab(with_info_bar(self.fan_chart, *self._TAB_INFO["fan"]),
                         "Monte Carlo Fan")

        self.dist_chart = DistributionChart()
        self.tabs.addTab(
            with_info_bar(self.dist_chart, *self._TAB_INFO["distribution"]),
            "Distribution")

        opt_split = QSplitter(Qt.Orientation.Horizontal)
        self.options_chart = OptionsChart()
        opt_split.addWidget(self.options_chart)
        self.option_table = StatTable("Value")
        self.option_table.setMinimumWidth(280)
        opt_split.addWidget(self.option_table)
        opt_split.setStretchFactor(0, 1)
        opt_split.setSizes([700, 320])
        self.tabs.addTab(with_info_bar(opt_split, *self._TAB_INFO["options"]),
                         "Options / IV")

        diag_split = QSplitter(Qt.Orientation.Horizontal)
        self.diag_chart = DiagnosticsChart()
        diag_split.addWidget(self.diag_chart)
        self.diag_table = StatTable("Value")
        self.diag_table.setMinimumWidth(280)
        diag_split.addWidget(self.diag_table)
        diag_split.setStretchFactor(0, 1)
        diag_split.setSizes([720, 300])
        self.tabs.addTab(with_info_bar(diag_split, *self._TAB_INFO["diagnostics"]),
                         "Diagnostics")

        corr_split = QSplitter(Qt.Orientation.Horizontal)
        self.corr_chart = CorrelationChart()
        corr_split.addWidget(self.corr_chart)
        self.corr_table = StatTable("Value")
        self.corr_table.setMinimumWidth(250)
        corr_split.addWidget(self.corr_table)
        corr_split.setStretchFactor(0, 1)
        corr_split.setSizes([760, 280])
        self.tabs.addTab(with_info_bar(corr_split, *self._TAB_INFO["correlation"]),
                         "Correlation")
        return self.tabs

    # -- right panel ---------------------------------------------------
    def _build_right_panel(self) -> QWidget:
        split = QSplitter(Qt.Orientation.Vertical)
        split.setMinimumWidth(280)

        self.estimate_table = StatTable("Value")
        self.estimate_table.set_headers("Price estimate", "Value")
        split.addWidget(self._wrap_table(
            "PRICE ESTIMATE", self.estimate_table,
            "The model's estimate of the price at the horizon. Mean, median "
            "and mode differ because the distribution is skewed; the forward "
            "is the market's own no-view price."))

        self.stat_table = StatTable("Value")
        self.stat_table.set_headers("Distribution", "Value")
        split.addWidget(self._wrap_table("TERMINAL DISTRIBUTION", self.stat_table))

        self.risk_table = StatTable("Value")
        self.risk_table.set_headers("Risk", "Value")
        split.addWidget(self._wrap_table("RISK", self.risk_table))

        self.kelly_table = StatTable("Value")
        self.kelly_table.set_headers("Position sizing", "Value")
        split.addWidget(self._wrap_table("POSITION SIZING", self.kelly_table))

        split.setSizes([300, 380, 280, 160])
        return split

    @staticmethod
    def _wrap_table(title: str, table: StatTable, tooltip: str = "") -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        label = QLabel(title)
        label.setProperty("role", "section")
        label.setStyleSheet(
            f"color: {PALETTE['fg_dim']}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; padding: 2px 3px;")
        if tooltip:
            label.setToolTip(tooltip)
            table.setToolTip(tooltip)
        col.addWidget(label)
        col.addWidget(table, 1)
        return box

    def _show_initial_placeholders(self) -> None:
        """Give every chart a message before any data arrives.

        A freshly constructed matplotlib canvas draws nothing at all, which
        reads as a broken tab rather than an empty one.  Each placeholder says
        what the tab needs and how to get it.
        """
        self.price_chart.placeholder(
            "No price history yet.\n\nEnter a ticker and press Load (or Enter).")
        self.fan_chart.placeholder(
            "No simulation yet.\n\nPress Run (Ctrl+R) to simulate.")
        self.dist_chart.placeholder(
            "No simulation yet.\n\nPress Run (Ctrl+R) to simulate.")
        self.options_chart.placeholder(
            "No option chain loaded yet.\n\n"
            "Opening this tab fetches the live chain automatically,\n"
            "or press the Load option chain button on the left.\n\n"
            "Press Price options for Black-Scholes, Greeks,\n"
            "lattices and exotics using the parameters on the left.")
        self.corr_chart.placeholder(
            "No basket loaded yet.\n\n"
            "Open the Basket / Correlation panel on the left,\n"
            "enter comma-separated tickers and press Analyse Basket.")

    def _on_tab_changed(self, index: int) -> None:
        """Fetch what a tab needs the first time the user opens it.

        Only the option chain is auto-fetched: it is a single request for the
        symbol already on screen.  The basket is left manual because it is
        several network calls for symbols the user has not chosen yet.
        """
        if index != 3 or self.history is None or self.history.empty:
            return
        if self._chain_ticker == self.loaded_ticker or self._chain_loading:
            return
        self._load_chain()

    def _install_shortcuts(self) -> None:
        for keys, slot in (
            ("Ctrl+R", self._run_simulation),
            ("Esc", self._cancel_simulation),
            ("F5", self._load_ticker),
            ("Ctrl+L", lambda: (self.ticker_edit.setFocus(),
                                self.ticker_edit.selectAll())),
            ("Ctrl+E", self._export_run),
            ("Ctrl+S", self._export_chart),
            ("Ctrl+K", self._calibrate),
        ):
            QShortcut(QKeySequence(keys), self, activated=slot)
        for i in range(6):
            QShortcut(QKeySequence(f"Ctrl+{i+1}"), self,
                      activated=lambda idx=i: self.tabs.setCurrentIndex(idx))

    def _restore_geometry(self) -> None:
        geo = self.config.window_geometry
        try:
            if len(geo) == 4 and all(isinstance(v, (int, float)) for v in geo):
                screen = QGuiApplication.primaryScreen().availableGeometry()
                w = int(min(geo[2], screen.width()))
                h = int(min(geo[3], screen.height()))
                x = int(min(max(geo[0], screen.left()), screen.right() - 200))
                y = int(min(max(geo[1], screen.top()), screen.bottom() - 150))
                self.setGeometry(x, y, max(w, 1100), max(h, 700))
                return
        except Exception:
            pass
        self.resize(1680, 980)

    # ==================================================================
    # messaging
    # ==================================================================
    def _error(self, message: str) -> None:
        """Show a dismissible in-UI banner instead of a modal dialog.

        Modal dialogs would interrupt a streaming run; the banner lets the user
        keep working and read the problem at their own pace.
        """
        self.banner.setText("⚠  " + message)
        self.banner.setVisible(True)
        self.statusBar().showMessage(message, 8000)

    def _clear_error(self) -> None:
        self.banner.setVisible(False)

    def _status(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    # ==================================================================
    # ticker / loaded-data agreement
    # ==================================================================
    @property
    def loaded_ticker(self) -> str:
        """The symbol the on-screen data actually belongs to."""
        return self.history.ticker if self.history is not None else ""

    def _on_ticker_typed(self, _text: str = "") -> None:
        """Flag when the ticker box no longer matches the loaded data."""
        typed = self.ticker_edit.text().strip().upper()
        loaded = self.loaded_ticker
        stale = bool(typed) and bool(loaded) and typed != loaded
        self.pending_label.setText(f"↵ load {typed}" if stale else "")
        self.pending_label.setVisible(stale)
        self.ticker_edit.setStyleSheet(
            f"QLineEdit {{ border: 1px solid {PALETTE['warn']}; }}" if stale else "")
        if stale:
            self._status(f"Showing {loaded}. Press Enter or Load to fetch {typed}.")

    def _guard_ticker(self) -> bool:
        """Refuse to act on data belonging to a different symbol.

        Returns True when it is safe to proceed.  Simulating on AAPL bars while
        the box reads NVDA produces a result that is wrong in a way no chart
        would reveal, so this blocks rather than warns.
        """
        typed = self.ticker_edit.text().strip().upper()
        loaded = self.loaded_ticker
        if typed and loaded and typed != loaded:
            self._error(
                f"The ticker box says {typed} but the loaded data is {loaded}. "
                f"Press Enter or Load to fetch {typed} first.")
            return False
        return True

    def _track(self, worker) -> None:
        """Keep a reference so the QThread is not garbage collected mid-run."""
        self._workers = [w for w in self._workers if w.isRunning()]
        self._workers.append(worker)

    # ==================================================================
    # data loading
    # ==================================================================
    def _load_ticker(self) -> None:
        ticker = self.ticker_edit.text().strip().upper()
        if not ticker:
            self._error("Enter a ticker symbol.")
            return
        self.ticker_edit.setText(ticker)
        self.config.ticker = ticker
        self.config.period = self.period_combo.currentText()
        self.config.interval = self.interval_combo.currentText()
        self.led.set_state("busy", "loading...")
        self._status(f"Loading {ticker} ...")

        worker = DataWorker(self.market, ticker, self.config.period,
                            self.config.interval)
        worker.done.connect(self._on_history)
        worker.quote_done.connect(self._on_quote)
        worker.failed.connect(self._error)
        self._track(worker)
        worker.start()

    @pyqtSlot(object)
    def _on_history(self, res) -> None:
        self.history = res
        status = res.status
        self.led.set_state(status.health.value, status.health.value,
                           status.message)

        if res.empty:
            self._error(f"No data for {res.ticker}: {status.message}")
            self.price_chart.placeholder(f"No data for {res.ticker}.\n"
                                         f"{status.message}")
            self.returns = np.array([])
            return

        if status.health in (Health.STALE, Health.SYNTHETIC):
            self._error(f"{res.ticker}: {status.message}")
        else:
            self._clear_error()

        if res.ticker != self._chain_ticker:
            # the chain on screen belongs to the previous symbol
            self.chain_tidy = self.chain_pivot = None
            self._chain_ticker = ""
            self.options_chart.placeholder(
                f"Option chain not loaded for {res.ticker}.\n\n"
                "Press 'Load option chain', or reopen this tab.")
            self.option_table.set_rows([])
        self._on_ticker_typed()

        frame = res.frame
        self.spot = res.spot
        self.returns = statmod.log_returns(res.close)
        self._status(f"{res.ticker}: {len(frame)} bars  ({status.message})")

        ann_vol = (float(np.std(self.returns, ddof=1))
                   / np.sqrt(interval_to_dt(self.config.interval))
                   if self.returns.size > 2 else float("nan"))
        self.metrics.set("last", fmt_money(self.spot), PALETTE["fg"])
        self.metrics.set("ann vol", fmt_pct(ann_vol, 1), PALETTE["fg"])
        self.metrics.set("bars", f"{len(frame):,}", PALETTE["fg"])

        self._refresh_price_tab()
        self._refresh_diagnostics()
        self._detect_regimes()
        # Switching tickers while already sitting on the Options tab fires no
        # currentChanged signal, so the auto-load has to be triggered here too
        # or the tab would keep showing the previous symbol's placeholder.
        if self.tabs.currentIndex() == 3 and self._chain_ticker != res.ticker:
            QTimer.singleShot(0, self._load_chain)

    @pyqtSlot(object)
    def _on_quote(self, quote) -> None:
        if not np.isfinite(quote.price):
            return
        self.metrics.set("last", fmt_money(quote.price), PALETTE["fg"])
        pct = quote.change_pct
        if np.isfinite(pct):
            self.metrics.set("change", f"{pct:+.2f}%  ({quote.change:+,.2f})",
                             sign_color(pct))

    # ==================================================================
    # price tab and diagnostics
    # ==================================================================
    def _refresh_price_tab(self) -> None:
        if self.history is None or self.history.empty:
            return
        frame = self.history.frame
        close = frame["close"].to_numpy(dtype=float)
        upper, mid, lower = tech.bollinger_bands(close, 20, 2.0)
        line, signal, hist = tech.macd(close)
        indicators = {
            "sma_fast": tech.sma(close, 20),
            "sma_slow": tech.sma(close, 50),
            "ema": tech.ema(close, 20),
            "bb_upper": upper, "bb_mid": mid, "bb_lower": lower,
            "rsi": tech.rsi(close, 14),
            "macd": line, "macd_signal": signal, "macd_hist": hist,
        }
        label = pathmod.MODEL_LABELS.get(self.config.model, "")
        self.price_chart.render(
            frame, indicators, self.hmm_regimes,
            title=f"{self.history.ticker}   {self.config.period} / "
                  f"{self.config.interval}   |   {label}",
        )

    def _refresh_diagnostics(self) -> None:
        if self.returns.size < 30:
            self.diag_chart.placeholder("Not enough history for diagnostics.")
            self.diag_table.set_rows([])
            return
        frame = self.history.frame
        r = self.returns
        window = int(self.config.vol_window)
        vols = {
            "realized": statmod.rolling_realized_vol(r, window),
            "ewma": statmod.ewma_vol(r, self.config.ewma_lambda),
        }
        try:
            vols["parkinson"] = statmod.parkinson_vol(
                frame["high"].to_numpy(float), frame["low"].to_numpy(float),
                window)[1:]
            vols["garman_klass"] = statmod.garman_klass_vol(
                frame["open"].to_numpy(float), frame["high"].to_numpy(float),
                frame["low"].to_numpy(float), frame["close"].to_numpy(float),
                window)[1:]
        except Exception:
            pass  # a feed without OHLC still gets the close-to-close estimators

        cone = tech.vol_cone(r)
        self.diag_chart.render(r, vols, statmod.acf(r, 40), cone,
                               title=f"{self.history.ticker} return diagnostics")

        jb_stat, jb_p = statmod.jarque_bera(r)
        adf_r = statmod.adf_test(r)
        adf_p = statmod.adf_test(self.history.close)
        lb_stat, lb_p = statmod.ljung_box(r**2, 20)
        acf_vals, band = statmod.acf(r, 5)
        dt = interval_to_dt(self.config.interval)
        mu_hat, sigma_hat = cal.annualized_moments(r, dt)
        from scipy import stats as sps

        rows = [
            ("observations", f"{r.size:,}"),
            ("ann. drift (mu)", fmt_pct(mu_hat, 2)),
            ("ann. volatility", fmt_pct(sigma_hat, 2)),
            ("skew", fmt_num(sps.skew(r), 3)),
            ("excess kurtosis", fmt_num(sps.kurtosis(r), 3)),
            ("Jarque-Bera", f"{fmt_num(jb_stat, 1)}  (p={jb_p:.2g})"),
            ("  normal?", "rejected" if jb_p < 0.05 else "not rejected"),
            ("ADF, returns", f"{fmt_num(adf_r['stat'], 2)}  (5% = -2.86)"),
            ("  stationary?", "yes" if adf_r["stationary_5%"] else "no"),
            ("ADF, prices", f"{fmt_num(adf_p['stat'], 2)}"),
            ("  stationary?", "yes" if adf_p["stationary_5%"] else "no (unit root)"),
            ("ACF(1) returns", fmt_num(acf_vals[1] if acf_vals.size > 1 else np.nan, 4)),
            ("  95% band", f"+/- {fmt_num(band, 4)}"),
            ("Ljung-Box r^2 (20)", f"{fmt_num(lb_stat, 1)}  (p={lb_p:.2g})"),
            ("  vol clustering?", "yes" if lb_p < 0.05 else "no"),
        ]
        colors: Dict[int, str] = {
            6: PALETTE["down"] if jb_p < 0.05 else PALETTE["up"],
            8: PALETTE["up"] if adf_r["stationary_5%"] else PALETTE["down"],
            10: PALETTE["up"] if not adf_p["stationary_5%"] else PALETTE["warn"],
            14: PALETTE["warn"] if lb_p < 0.05 else PALETTE["up"],
        }

        fits = statmod.fit_distributions(r, dt)
        self.dist_fits = fits
        if fits:
            rows.append(("", ""))
            rows.append(("DISTRIBUTION FIT", "AIC  (best first)"))
            for f in fits:
                rows.append((f"  {f.name}", f"{f.aic:,.1f}"))
            rows.append(("  best by AIC", fits[0].name))
        self.diag_table.set_rows(rows, colors)

    def _detect_regimes(self) -> None:
        """Fit the HMM off-thread and shade the price chart when it lands."""
        if self.returns.size < 120:
            self.hmm_regimes = None
            return
        r = self.returns.copy()
        n_states = int(self.config.hmm_states)

        def job():
            res = statmod.fit_gaussian_hmm(r, n_states)
            if res is None:
                _, labels, _ = statmod.volatility_regimes(r)
                return ("threshold", labels, None)
            return ("hmm", res.states, res)

        worker = CallableWorker(job)
        worker.done.connect(self._on_regimes)
        worker.failed.connect(lambda m: self._status(f"Regime fit failed: {m}"))
        self._track(worker)
        worker.start()

    @pyqtSlot(object)
    def _on_regimes(self, payload) -> None:
        kind, labels, res = payload
        # returns are one shorter than prices; pad so the shading aligns
        self.hmm_regimes = np.concatenate([[labels[0]], labels]) \
            if len(labels) else None
        self._refresh_price_tab()
        if kind == "hmm" and res is not None:
            dur = res.expected_durations
            self._status(
                f"HMM: calm vol {res.stds[0]*np.sqrt(252):.1%} "
                f"(avg {dur[0]:.0f}d), stressed vol {res.stds[1]*np.sqrt(252):.1%} "
                f"(avg {dur[1]:.0f}d); currently "
                f"{'STRESSED' if labels[-1] else 'calm'}"
            )

    # ==================================================================
    # model / calibration
    # ==================================================================
    def _current_model(self) -> str:
        return self.model_combo.currentData() or "gbm"

    _MODEL_NOTES = {
        "gbm": "Constant vol, Gaussian returns. The reference case: thin "
               "tails, no clustering, no jumps.",
        "student_t": "Same total variance as GBM with fatter tails. nu below "
                     "4 gives infinite kurtosis.",
        "merton": "Diffusion plus Poisson jumps, drift-compensated. Jumps "
                  "arrive independently -- no crash clustering.",
        "heston": "Stochastic variance with leverage. rho<0 gives the equity "
                  "smirk. Feller 2*kappa*theta > xi^2 keeps variance positive.",
        "garch": "Volatility clusters and mean-reverts. Parameters are PER "
                 "STEP, not annualised. Needs alpha+beta<1.",
        "bootstrap": "Resamples real returns. Keeps the historical shape "
                     "exactly; destroys all autocorrelation.",
        "block_bootstrap": "Resamples contiguous blocks, so clustering up to "
                           "the block length survives.",
    }

    def _on_model_changed(self, initial: bool = False) -> None:
        model = self._current_model()
        if not initial:
            prev = self.config.model
            if prev in pathmod.MODEL_PARAM_SPECS and self.param_grid.field_names():
                self.config.set_params_for(prev, self.param_grid.values())
        self.config.model = model
        specs = pathmod.MODEL_PARAM_SPECS.get(model, ())
        note = ""
        if model in pathmod.PER_STEP_PARAM_MODELS:
            note = "Parameters below are per step, not annualised."
        elif model in pathmod.HISTORY_MODELS:
            note = "Draws from the loaded return history; load a ticker first."
        self.param_grid.build(specs, self.config.params_for(model), note)
        self.model_note.setText(self._MODEL_NOTES.get(model, ""))
        if self.history is not None:
            self._refresh_price_tab()

    def _calibrate(self) -> None:
        if not self._guard_ticker():
            return
        if self.returns.size < 60:
            self._error("Load at least 60 bars of history before calibrating.")
            return
        model = self._current_model()
        lookback = int(max(60, self.f_lookback.value(self.config.calibration_lookback)))
        self.config.calibration_lookback = lookback
        sample = self.returns[-lookback:]
        dt = interval_to_dt(self.config.interval)
        self._status(f"Calibrating {pathmod.MODEL_LABELS[model]} on "
                     f"{sample.size} bars ...")

        def job():
            return cal.calibrate(model, sample, dt)

        worker = CallableWorker(job)
        worker.done.connect(lambda params: self._on_calibrated(params, sample.size))
        worker.failed.connect(lambda m: self._error(f"Calibration failed: {m}"))
        self._track(worker)
        worker.start()

    @pyqtSlot(object)
    def _on_calibrated(self, params: Dict[str, float], n: int) -> None:
        self.param_grid.set_values(params)
        model = self._current_model()
        self.config.set_params_for(model, self.param_grid.values())
        extras = []
        for key, label in (("persistence", "persistence"),
                           ("half_life", "vol half-life"),
                           ("sigma_lr", "long-run vol")):
            if key in params and np.isfinite(params[key]):
                value = (f"{params[key]:.1f}d" if key == "half_life"
                         else f"{params[key]:.4f}")
                extras.append(f"{label} {value}")
        note = f"Calibrated on {n} bars."
        if extras:
            note += "  " + ", ".join(extras) + "."
        if model == "heston":
            note += ("  kappa is biased high and rho attenuated toward zero "
                     "by realised-variance measurement error -- see the "
                     "docstring.")
        if model in ("gbm", "student_t", "merton", "heston", "garch"):
            note += ("  Drift is the least reliable estimate here; override mu "
                     "with a view if you have one.")
        self.calib_note.setText(note)
        self._status("Calibration complete.")

    # ==================================================================
    # simulation
    # ==================================================================
    def _resolve_targets(self) -> Tuple[float, float, float]:
        spot = self.spot if np.isfinite(self.spot) and self.spot > 0 else 100.0
        target = self.f_target.value(0.0) or spot * 1.10
        barrier = self.f_barrier.value(0.0) or spot * 1.20
        ruin_pct = self.f_ruin.value(self.config.ruin_pct) or 50.0
        return float(target), float(barrier), float(spot * ruin_pct / 100.0)

    def _build_request(self) -> Optional[SimRequest]:
        model = self._current_model()
        spot = self.spot if np.isfinite(self.spot) and self.spot > 0 else 100.0
        params = self.param_grid.values()
        self.config.set_params_for(model, params)
        target, barrier, ruin = self._resolve_targets()

        request = SimRequest(
            ticker=self.config.ticker,
            s0=float(spot),
            model=model,
            params=params,
            horizon_days=int(max(1, self.f_horizon.value(252))),
            n_paths=int(max(2, self.f_paths.value(100_000))),
            dt=interval_to_dt(self.config.interval),
            seed=int(self.f_seed.value(42)) if self.chk_seed.isChecked() else None,
            antithetic=self.chk_anti.isChecked(),
            batch_size=int(max(256, self.f_batch.value(10_000))),
            update_every=int(max(1, self.config.update_every)),
            max_fan_paths=int(max(50, self.config.max_fan_paths)),
            history_returns=self.returns if self.returns.size else None,
            target_price=target,
            barrier=barrier,
            barrier_direction=self.barrier_dir.currentText(),
            ruin_level=ruin,
            risk_free=float(self.f_rate.value(0.04)),
        )
        problem = request.validate()
        if problem:
            self._error(problem)
            return None
        return request

    def _run_simulation(self) -> None:
        if self._sim is not None and self._sim.isRunning():
            self._status("A simulation is already running.")
            return
        if not self._guard_ticker():
            return
        request = self._build_request()
        if request is None:
            return
        self._clear_error()
        self._sync_config_from_ui()

        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self.progress.setFormat("starting ...")
        self._run_started = time.perf_counter()
        self.tabs.setCurrentIndex(1)

        worker = SimulationWorker(request)
        worker.progress.connect(self._on_progress)
        worker.partial.connect(self._on_partial)
        worker.finished_run.connect(self._on_finished)
        worker.failed.connect(self._on_sim_failed)
        self._sim = worker
        self._track(worker)
        worker.start()
        self._status(f"Running {pathmod.MODEL_LABELS[request.model]}: "
                     f"{request.n_paths:,} paths x {request.horizon_days} steps")

    def _cancel_simulation(self) -> None:
        if self._sim is not None and self._sim.isRunning():
            self._sim.cancel()
            self.progress.setFormat("cancelling ...")
            self._status("Cancelling ...")

    @pyqtSlot(object)
    def _on_progress(self, p) -> None:
        self.progress.setValue(int(p.fraction * 1000))
        eta = p.eta
        eta_txt = f"eta {eta:4.1f}s" if np.isfinite(eta) else "eta --"
        self.progress.setFormat(
            f"{p.paths_done:,}/{p.paths_total:,}  {p.elapsed:4.1f}s  {eta_txt}"
        )

    @pyqtSlot(object)
    def _on_partial(self, res) -> None:
        self.result = res
        self._render_result(res, streaming=True)

    @pyqtSlot(object)
    def _on_finished(self, res) -> None:
        self.result = res
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(1000 if not res.cancelled else self.progress.value())
        if res.error:
            self.progress.setFormat("error")
            self._error(res.error)
            return
        self._render_result(res, streaming=False)
        rate = res.n_done / max(res.elapsed, 1e-9)
        verb = "cancelled after" if res.cancelled else "done in"
        self.progress.setFormat(f"{res.n_done:,} paths  {res.elapsed:.2f}s")
        self._status(f"Simulation {verb} {res.elapsed:.2f}s -- "
                     f"{res.n_done:,} paths ({rate/1000:.0f}k/s)")

    @pyqtSlot(str)
    def _on_sim_failed(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setFormat("error")
        self._error(f"Simulation thread failed:\n{message}")

    def _render_result(self, res, streaming: bool) -> None:
        target, barrier, _ = self._resolve_targets()
        label = pathmod.MODEL_LABELS.get(res.request.model, res.request.model)
        suffix = " (streaming)" if streaming else ""
        self.fan_chart.render(
            res, n_sample_paths=int(self.f_fan.value(150)),
            target=target, barrier=barrier,
            title=f"{res.request.ticker}  {label}  --  {res.n_done:,} paths x "
                  f"{res.request.horizon_days} days{suffix}",
        )
        if not streaming or self.tabs.currentIndex() == 2:
            self.dist_chart.render(res, target=target,
                                   title=f"{res.request.ticker} terminal "
                                         f"distribution ({res.n_done:,} paths)")
        self._fill_stat_tables(res)

    def _fill_price_estimate(self, res) -> None:
        """Populate the PRICE ESTIMATE panel and the top-bar headline number."""
        est = res.price_estimate(dividend=float(self.f_div.value(0.0)))
        if not est:
            return
        s0 = est["spot"]
        days = int(est["horizon_days"])
        rows = [
            ("spot (live)", fmt_money(s0)),
            ("horizon", f"{days} steps"),
            ("", ""),
            (f"EXPECTED IN {days}d", ""),
            ("  mean", fmt_money(est["expected"])),
            ("  as return", fmt_pct(est["expected_return"])),
            ("  +/- MC std error", fmt_money(est["expected_se"], 3)),
            ("  annualised", fmt_pct(est.get("annualized_expected_return",
                                             float("nan")))),
            ("", ""),
            ("CENTRAL ESTIMATES", ""),
            ("  median (50%)", fmt_money(est["median"])),
            ("  most likely (mode)", fmt_money(est["mode"])),
            ("", ""),
            ("CONFIDENCE BANDS", ""),
            ("  68%", f"{est['lo68']:,.2f} - {est['hi68']:,.2f}"),
            ("  95%", f"{est['lo95']:,.2f} - {est['hi95']:,.2f}"),
            ("", ""),
            ("MARKET REFERENCE", ""),
            ("  forward S*e^(r-q)T", fmt_money(est["forward"])),
            ("  model vs forward", fmt_pct(est["vs_forward"])),
            ("  P(above spot)", fmt_pct(est["prob_above_spot"])),
        ]
        colors = {
            4: sign_color(est["expected_return"]),
            5: sign_color(est["expected_return"]),
            10: sign_color(est["median_return"]),
            19: sign_color(est["vs_forward"]),
        }
        self.estimate_table.set_rows(rows, colors)
        self.metrics.set("est. price",
                         f"{est['expected']:,.2f}",
                         sign_color(est["expected_return"]))

    def _fill_stat_tables(self, res) -> None:
        s = res.summary()
        if not s:
            return
        self._fill_price_estimate(res)
        s0 = float(res.request.s0)
        rows = [
            ("paths", f"{res.n_done:,}"),
            ("spot", fmt_money(s0)),
            ("horizon", f"{res.request.horizon_days} steps"),
            ("", ""),
            ("mean", fmt_money(s["mean"])),
            ("  as return", fmt_pct(s["mean_return"])),
            ("median", fmt_money(s["median"])),
            ("  as return", fmt_pct(s["median_return"])),
            ("std dev", fmt_money(s["std"])),
            ("std error of mean", fmt_money(s["stderr"], 4)),
            ("skew", fmt_num(s["skew"], 3)),
            ("excess kurtosis", fmt_num(s["kurtosis"], 3)),
            ("", ""),
            ("PERCENTILE LADDER", ""),
        ]
        for p in (1, 5, 10, 25, 50, 75, 90, 95, 99):
            key = f"p{p}"
            if key in s:
                rows.append((f"  {p}%", f"{fmt_money(s[key])}   "
                                        f"({(s[key]/s0-1)*100:+.1f}%)"))
        rows += [
            ("", ""),
            ("PROBABILITIES", ""),
            ("  finish above spot", fmt_pct(s["prob_up"])),
        ]
        colors: Dict[int, str] = {}
        if "prob_above_target" in s:
            rows.append((f"  above {fmt_money(res.request.target_price)}",
                         fmt_pct(s["prob_above_target"])))
        if "prob_touch_barrier" in s:
            rows.append((f"  touch {fmt_money(res.request.barrier)} "
                         f"({res.request.barrier_direction})",
                         fmt_pct(s["prob_touch_barrier"])))
        if "prob_ruin" in s:
            idx = len(rows)
            rows.append((f"  fall to {fmt_money(res.request.ruin_level)}",
                         fmt_pct(s["prob_ruin"])))
            colors[idx] = PALETTE["down"]
        rows += [
            ("", ""),
            ("DRAWDOWN", ""),
            ("  expected max", fmt_pct(s["expected_max_drawdown"])),
            ("  median max", fmt_pct(s["median_max_drawdown"])),
            ("  worst path", fmt_pct(s["worst_max_drawdown"])),
        ]
        colors[len(rows) - 1] = PALETTE["down"]
        colors[4] = sign_color(s["mean_return"])
        colors[5] = sign_color(s["mean_return"])
        self.stat_table.set_rows(rows, colors)

        r = res.risk()
        risk_rows = [("VALUE AT RISK", "loss, % of notional")]
        risk_colors: Dict[int, str] = {}
        for level in (90, 95, 99):
            vk, ck = f"var_{level}", f"cvar_{level}"
            if vk in r:
                risk_rows.append((f"  VaR {level}%", fmt_pct(r[vk])))
                risk_colors[len(risk_rows) - 1] = PALETTE["down"]
                risk_rows.append((f"  CVaR {level}%", fmt_pct(r[ck])))
                risk_colors[len(risk_rows) - 1] = PALETTE["down"]
        risk_rows += [("", ""), ("RATIOS", "annualised")]
        if "sharpe" in r:
            risk_rows.append(("  Sharpe", fmt_num(r["sharpe"], 3)))
            risk_colors[len(risk_rows) - 1] = sign_color(r["sharpe"])
            risk_rows.append(("  Sortino", fmt_num(r["sortino"], 3)))
            risk_colors[len(risk_rows) - 1] = sign_color(r["sortino"])
        risk_rows += [("", ""), ("MAX DRAWDOWN", "percentiles")]
        for p in (5, 25, 50, 75, 95):
            key = f"mdd_p{p}"
            if key in r:
                risk_rows.append((f"  {p}%", fmt_pct(r[key])))
        risk_rows += [
            ("", ""),
            ("risk-free used", fmt_pct(res.request.risk_free)),
        ]
        self.risk_table.set_rows(risk_rows, risk_colors)

        k = res.kelly()
        kelly_rows = [
            ("full Kelly (empirical)", fmt_num(k["kelly_empirical"], 3)),
            ("half Kelly", fmt_num(k["half_kelly"], 3)),
            ("quarter Kelly", fmt_num(k["quarter_kelly"], 3)),
            ("", ""),
            ("Gaussian (mu-r)/sigma^2", fmt_num(k["kelly_gaussian"], 3)),
            ("log growth rate", fmt_pct(k["growth_rate"])),
            ("", ""),
            ("note", "empirical = this holding"),
            ("", "period; Gaussian = the"),
            ("", "continuous-rebalancing"),
            ("", "limit. They diverge as"),
            ("", "the horizon lengthens."),
        ]
        self.kelly_table.set_rows(
            kelly_rows, {0: PALETTE["accent"], 1: PALETTE["up"]})

    # ==================================================================
    # options
    # ==================================================================
    def _price_options(self) -> None:
        if not self._guard_ticker():
            return
        spot = self.spot if np.isfinite(self.spot) and self.spot > 0 else 100.0
        strike = self.f_strike.value(0.0) or spot
        days = max(1.0, self.f_opt_days.value(30))
        T = days / 365.0
        rate = float(self.f_rate.value(0.04))
        div = float(self.f_div.value(0.0))
        kind = self.opt_kind.currentText()
        vol = self.f_opt_vol.value(0.0)
        if vol <= 0:
            params = self.param_grid.values()
            vol = float(params.get("sigma", 0.0)) or self._fallback_vol()
        style = self.opt_style.currentText()
        barrier = self.f_opt_barrier.value(0.0) or spot * 1.2
        tree_steps = int(max(20, self.f_tree.value(500)))
        mc_paths = int(max(1000, self.f_opt_paths.value(100_000)))
        self._status("Pricing ...")

        def job():
            greeks = pricing.bsm_greeks(spot, strike, T, rate, div, vol, kind)
            euro_bin = pricing.binomial_tree_price(spot, strike, T, rate, div,
                                                   vol, tree_steps, kind, False)
            amer_bin = pricing.binomial_tree_price(spot, strike, T, rate, div,
                                                   vol, tree_steps, kind, True)
            amer_tri = pricing.trinomial_tree_price(spot, strike, T, rate, div,
                                                    vol, max(60, tree_steps // 2),
                                                    kind, True)
            mc = pricing.mc_european_price(spot, strike, T, rate, div, vol,
                                           mc_paths, kind, True, True, seed=7)
            kwargs = {"barrier": barrier} if style.startswith("barrier") else {}
            exotic = pricing.mc_exotic_price(
                spot, strike, T, rate, div, vol, style, kind,
                n_paths=min(mc_paths, 200_000),
                n_steps=int(max(5, min(504, days))), seed=11, **kwargs)
            iv = pricing.implied_vol(greeks.price, spot, strike, T, rate, div, kind)
            return greeks, euro_bin, amer_bin, amer_tri, mc, exotic, iv

        worker = CallableWorker(job)
        worker.done.connect(lambda out: self._on_priced(
            out, spot, strike, days, vol, kind, style, barrier, tree_steps))
        worker.failed.connect(lambda m: self._error(f"Pricing failed: {m}"))
        self._track(worker)
        worker.start()

    def _fallback_vol(self) -> float:
        if self.returns.size > 10:
            _, sigma = cal.annualized_moments(
                self.returns, interval_to_dt(self.config.interval))
            if np.isfinite(sigma) and sigma > 0:
                return float(sigma)
        return 0.25

    @pyqtSlot(object)
    def _on_priced(self, out, spot, strike, days, vol, kind, style, barrier,
                   tree_steps) -> None:
        greeks, euro_bin, amer_bin, amer_tri, mc, exotic, iv = out
        early = amer_bin - euro_bin
        # Row indices for the highlighted "price" lines are found by scanning
        # after the fact rather than hardcoded: the block below changes shape
        # (barrier level, closed form, error) depending on the payoff, so fixed
        # indices would silently highlight the wrong row.
        rows = [
            ("INPUTS", ""),
            ("  spot", fmt_money(spot)),
            ("  strike", fmt_money(strike)),
            ("  days to expiry", f"{days:.0f}"),
            ("  volatility", fmt_pct(vol)),
            ("  type", kind),
            ("", ""),
            ("BLACK-SCHOLES-MERTON", ""),
            ("  price", fmt_money(greeks.price, 4)),
            ("  implied vol (round trip)", fmt_pct(iv) if np.isfinite(iv)
             else "unidentifiable"),
            ("", ""),
            ("GREEKS", ""),
            ("  delta", fmt_num(greeks.delta, 4)),
            ("  gamma", fmt_num(greeks.gamma, 5)),
            ("  vega  (per 1 vol pt)", fmt_num(greeks.vega / 100.0, 4)),
            ("  theta (per day)", fmt_num(greeks.theta / 365.0, 4)),
            ("  rho   (per 1% rate)", fmt_num(greeks.rho / 100.0, 4)),
            ("  vanna", fmt_num(greeks.vanna, 4)),
            ("  volga", fmt_num(greeks.volga, 4)),
            ("", ""),
            ("LATTICES", f"{tree_steps} steps"),
            ("  binomial, European", fmt_money(euro_bin, 4)),
            ("  binomial, American", fmt_money(amer_bin, 4)),
            ("  trinomial, American", fmt_money(amer_tri, 4)),
            ("  early-exercise premium", fmt_money(early, 4)),
            ("", ""),
            ("MONTE CARLO", f"{mc.n_paths:,} paths"),
            ("  price", fmt_money(mc.price, 4)),
            ("  standard error", fmt_money(mc.stderr, 5)),
            ("  vs closed form", f"{mc.error:+.5f}"),
            ("  error in std errors",
             f"{abs(mc.error)/max(mc.stderr,1e-12):.2f} se"),
            ("  antithetic", "yes" if mc.antithetic else "no"),
            ("  control variate beta", fmt_num(mc.cv_beta, 4)
             if mc.cv_beta is not None else "--"),
            ("", ""),
            ("EXOTIC PAYOFF", style),
            ("  price", fmt_money(exotic.price, 4)),
            ("  standard error", fmt_money(exotic.stderr, 5)),
        ]
        colors = {i: PALETTE["accent"]
                  for i, (key, _) in enumerate(rows) if key == "  price"}
        if style.startswith("barrier"):
            rows.append(("  barrier level", fmt_money(barrier)))
        if exotic.analytic is not None:
            rows.append(("  closed form", fmt_money(exotic.analytic, 4)))
            rows.append(("  error", f"{exotic.error:+.5f}"))
        rows += [
            ("", ""),
            ("note", "discrete monitoring"),
            ("", "raises knock-out and"),
            ("", "lowers touch"),
            ("", "probabilities vs"),
            ("", "continuous."),
        ]
        self.option_table.set_rows(rows, colors)
        self.tabs.setCurrentIndex(3)
        self._status(f"Priced {kind} {fmt_money(strike)} / {days:.0f}d at "
                     f"{fmt_pct(vol)} vol")

    def _load_chain(self) -> None:
        if self.history is None or self.history.empty:
            self._error("Load a ticker before fetching its option chain.")
            return
        if not self._guard_ticker():
            return
        if self._chain_loading:
            return
        self._chain_loading = True
        ticker = self.loaded_ticker or self.config.ticker
        spot = self.spot if np.isfinite(self.spot) and self.spot > 0 else 100.0
        self._status(f"Loading option chain for {ticker} ...")
        worker = ChainWorker(self.market, ticker, spot,
                             float(self.f_rate.value(0.04)),
                             float(self.f_div.value(0.0)))
        worker.done.connect(self._on_chain)
        worker.failed.connect(self._on_chain_failed)
        self._track(worker)
        worker.start()

    @pyqtSlot(str)
    def _on_chain_failed(self, message: str) -> None:
        self._chain_loading = False
        self.options_chart.placeholder(f"Option chain failed.\n\n{message}")
        self._error(f"Chain load failed: {message}")

    @pyqtSlot(object, object, object)
    def _on_chain(self, res, tidy, pivot) -> None:
        self._chain_loading = False
        if tidy is None or len(tidy) == 0:
            self.options_chart.placeholder(
                f"No option chain for {res.ticker}.\n\n{res.status.message}")
            self._error(f"No usable option chain for {res.ticker}: "
                        f"{res.status.message}")
            return
        self.chain_tidy, self.chain_pivot = tidy, pivot
        self._chain_ticker = res.ticker
        spot = res.spot if np.isfinite(res.spot) and res.spot > 0 else self.spot
        self.options_chart.render(
            tidy, pivot, spot,
            title=f"{res.ticker} implied volatility  ({res.status.health.value})")
        self.tabs.setCurrentIndex(3)
        self._status(f"{res.ticker}: {len(tidy)} contracts inverted "
                     f"({res.status.message})")

    # ==================================================================
    # basket
    # ==================================================================
    def _analyse_basket(self) -> None:
        tickers = [t.strip().upper() for t in self.basket_edit.text().split(",")
                   if t.strip()]
        if len(tickers) < 2:
            self._error("Enter at least two comma-separated tickers.")
            return
        self.config.basket = tickers
        self._status(f"Loading basket: {', '.join(tickers)} ...")
        worker = BasketWorker(self.market, tickers, self.config.period,
                              self.config.interval)
        worker.done.connect(self._on_basket)
        worker.failed.connect(lambda m: self._error(f"Basket failed: {m}"))
        self._track(worker)
        worker.start()

    @pyqtSlot(object, object, object)
    def _on_basket(self, frame, corr, names) -> None:
        if corr is None or not names:
            self._error("Could not load enough basket data.")
            return
        self.basket_corr, self.basket_names = corr, list(names)
        rets, _ = ma.align_returns(frame)
        dt = interval_to_dt(self.config.interval)
        mus, sigmas = [], []
        for i in range(rets.shape[1]):
            mu, sigma = cal.annualized_moments(rets[:, i], dt)
            mus.append(mu)
            sigmas.append(sigma)
        spots = frame.iloc[-1].to_numpy(dtype=float)

        try:
            basket = ma.simulate_correlated_gbm(
                spots, mus, sigmas, corr,
                int(max(1, self.f_horizon.value(252))), 20_000,
                dt=dt, rng=np.random.default_rng(int(self.f_seed.value(42))),
                tickers=names)
        except Exception as exc:
            self._error(f"Basket simulation failed: {exc}")
            basket = None
        self.basket_result = basket
        self.corr_chart.render(corr, names, basket,
                               title=f"Correlation ({len(frame)} common bars)")

        off_diag = corr[~np.eye(len(names), dtype=bool)]
        rows = [("assets", str(len(names))), ("common bars", f"{len(frame):,}"),
                ("", ""), ("ANNUALISED", "mu / sigma")]
        for i, name in enumerate(names):
            rows.append((f"  {name}", f"{mus[i]*100:+.1f}% / {sigmas[i]*100:.1f}%"))
        rows += [
            ("", ""),
            ("CORRELATION", ""),
            ("  mean off-diagonal", fmt_num(float(off_diag.mean()), 3)),
            ("  max", fmt_num(float(off_diag.max()), 3)),
            ("  min", fmt_num(float(off_diag.min()), 3)),
            ("  diversification ratio",
             fmt_num(ma.diversification_ratio(
                 np.full(len(names), 1 / len(names)), sigmas, corr), 3)),
        ]
        if basket is not None:
            port = basket.portfolio_paths[:, -1]
            rows += [
                ("", ""),
                ("EQUAL-WEIGHT BASKET", f"{len(basket.portfolio_paths):,} paths"),
                ("  median return", fmt_pct(float(np.median(port)) - 1)),
                ("  5th percentile", fmt_pct(float(np.percentile(port, 5)) - 1)),
                ("  95th percentile", fmt_pct(float(np.percentile(port, 95)) - 1)),
                ("  P(gain)", fmt_pct(float((port > 1).mean()))),
                ("  max corr repro error",
                 fmt_num(float(np.abs(basket.realised_corr - corr).max()), 4)),
            ]
        self.corr_table.set_rows(rows)
        self.basket_note.setText(
            f"{len(names)} assets, {len(frame):,} common bars. Gaussian "
            f"dependence: no tail correlation.")
        self.tabs.setCurrentIndex(5)
        self._status(f"Basket: {', '.join(names)}")

    # ==================================================================
    # export
    # ==================================================================
    def _default_name(self, suffix: str, ext: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self.config.last_export_dir or export_dir()
        return os.path.join(
            base, f"{self.config.ticker}_{self.config.model}_{suffix}_{stamp}.{ext}")

    def _remember_dir(self, path: str) -> None:
        self.config.last_export_dir = os.path.dirname(path)

    def _export_chart(self) -> None:
        widget = self.tabs.currentWidget()
        canvas = widget if hasattr(widget, "export_png") else None
        if canvas is None:  # tabs that are splitters hold the canvas inside
            for child in widget.findChildren(QWidget):
                if hasattr(child, "export_png"):
                    canvas = child
                    break
        if canvas is None:
            self._error("This tab has no chart to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save chart", self._default_name("chart", "png"),
            "PNG image (*.png)")
        if not path:
            return
        if canvas.export_png(path):
            self._remember_dir(path)
            self._status(f"Chart saved to {path}")
        else:
            self._error(f"Could not write {path}")

    def _export_tables(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save tables", self._default_name("tables", "csv"),
            "CSV file (*.csv)")
        if not path:
            return
        blocks = [
            ("Price estimate", self.estimate_table),
            ("Terminal distribution", self.stat_table),
            ("Risk", self.risk_table),
            ("Position sizing", self.kelly_table),
            ("Diagnostics", self.diag_table),
            ("Options", self.option_table),
            ("Basket", self.corr_table),
        ]
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["QuantMC export", self.config.ticker,
                                 datetime.now().isoformat(timespec="seconds")])
                writer.writerow(["MODELLING TOOL, NOT INVESTMENT ADVICE"])
                for title, table in blocks:
                    rows = table.to_csv_rows()
                    if not rows:
                        continue
                    writer.writerow([])
                    writer.writerow([f"# {title}"])
                    writer.writerows(rows)
            self._remember_dir(path)
            self._status(f"Tables saved to {path}")
        except OSError as exc:
            self._error(f"Could not write {path}: {exc}")

    def _export_run(self) -> None:
        if self.result is None or self.result.n_done == 0:
            self._error("Run a simulation before exporting it.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export run", self._default_name("run", "csv"),
            "CSV file (*.csv);;JSON file (*.json)")
        if not path:
            return
        rows = self.result.export_rows()
        rows.insert(0, ("exported_at", datetime.now().isoformat(timespec="seconds")))
        rows.insert(1, ("disclaimer",
                        "modelling output, not investment advice; conditional "
                        "on the model's assumptions"))
        try:
            if path.lower().endswith(".json"):
                payload = {}
                for key, value in rows:
                    payload[key] = (value.item() if hasattr(value, "item")
                                    else value)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=2, default=str)
            else:
                with open(path, "w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(["key", "value"])
                    writer.writerows(rows)
            self._remember_dir(path)
            self._status(f"Run exported to {path}")
        except OSError as exc:
            self._error(f"Could not write {path}: {exc}")

    # ==================================================================
    # lifecycle
    # ==================================================================
    def _reset(self) -> None:
        model = self._current_model()
        self.param_grid.set_values(pathmod.default_params(model))
        self.result = None
        self.progress.setValue(0)
        self.progress.setFormat("idle")
        self.fan_chart.placeholder("No simulation yet.\nPress Run to start.")
        self.dist_chart.placeholder("No simulation yet.\nPress Run to start.")
        for table in (self.estimate_table, self.stat_table,
                      self.risk_table, self.kelly_table):
            table.set_rows([])
        self.calib_note.setText("")
        self._clear_error()
        self._status("Reset to model defaults.")

    def _sync_config_from_ui(self) -> None:
        c = self.config
        c.ticker = self.ticker_edit.text().strip().upper() or c.ticker
        c.period = self.period_combo.currentText()
        c.interval = self.interval_combo.currentText()
        c.model = self._current_model()
        c.horizon_days = int(self.f_horizon.value(c.horizon_days))
        c.n_paths = int(self.f_paths.value(c.n_paths))
        c.seed = int(self.f_seed.value(c.seed))
        c.use_seed = self.chk_seed.isChecked()
        c.antithetic = self.chk_anti.isChecked()
        c.batch_size = int(self.f_batch.value(c.batch_size))
        c.fan_sample_paths = int(self.f_fan.value(c.fan_sample_paths))
        c.calibration_lookback = int(self.f_lookback.value(c.calibration_lookback))
        c.target_price = float(self.f_target.value(0.0))
        c.barrier = float(self.f_barrier.value(0.0))
        c.barrier_direction = self.barrier_dir.currentText()
        c.ruin_pct = float(self.f_ruin.value(c.ruin_pct))
        c.risk_free = float(self.f_rate.value(c.risk_free))
        c.opt_strike = float(self.f_strike.value(0.0))
        c.opt_days = int(self.f_opt_days.value(c.opt_days))
        c.opt_kind = self.opt_kind.currentText()
        c.opt_vol = float(self.f_opt_vol.value(c.opt_vol))
        c.opt_dividend = float(self.f_div.value(c.opt_dividend))
        c.opt_style = self.opt_style.currentText()
        c.opt_barrier = float(self.f_opt_barrier.value(0.0))
        c.opt_tree_steps = int(self.f_tree.value(c.opt_tree_steps))
        c.opt_mc_paths = int(self.f_opt_paths.value(c.opt_mc_paths))
        c.basket = [t.strip().upper() for t in self.basket_edit.text().split(",")
                    if t.strip()] or c.basket
        c.set_params_for(c.model, self.param_grid.values())
        geo = self.geometry()
        c.window_geometry = [geo.x(), geo.y(), geo.width(), geo.height()]

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Cancel any running work and persist settings before closing."""
        try:
            if self._sim is not None and self._sim.isRunning():
                self._sim.cancel()
                self._sim.wait(2500)
            for worker in self._workers:
                if worker.isRunning():
                    worker.wait(1200)
        except Exception:
            pass
        try:
            self._sync_config_from_ui()
            self.config.save()
        except Exception:
            pass  # never block the close on a settings write
        event.accept()


# --------------------------------------------------------------------------
def launch(config: Optional[AppConfig] = None,
           market: Optional[MarketData] = None,
           ticker: Optional[str] = None) -> int:
    """Create the QApplication and show the window.  Returns the exit code."""
    from ..config import cache_path
    from ..data import BarCache

    apply_mpl_theme()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("QuantMC")
    app.setStyleSheet(STYLESHEET)

    cfg = config or AppConfig.load()
    if ticker:
        cfg.ticker = ticker.upper()
    if market is None:
        cache = BarCache(cache_path())
        market = MarketData(
            provider=default_provider(), cache=cache,
            max_age_seconds=cfg.cache_max_age_minutes * 60.0,
            offline=cfg.offline, fallback_synthetic=cfg.allow_synthetic,
        )
    window = MainWindow(cfg, market)
    window.show()
    return app.exec()
