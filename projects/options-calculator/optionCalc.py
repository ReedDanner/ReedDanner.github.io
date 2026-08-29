"""
╔══════════════════════════════════════════════════════════════════════════╗
║                  PROFESSIONAL OPTIONS CALCULATOR                        ║
║                                                                         ║
║  Black-Scholes pricing, full Greeks suite, probability analysis,        ║
║  payoff diagrams, and probability distribution curves.                  ║
║                                                                         ║
║  Built with customtkinter (dark theme) + matplotlib                     ║
╚══════════════════════════════════════════════════════════════════════════╝

Requirements:
    pip install customtkinter matplotlib numpy scipy
"""

import math
import numpy as np
from scipy.stats import norm
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import FuncFormatter
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — BLACK-SCHOLES ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class BlackScholesEngine:
    """
    Core analytical engine for European option pricing.
    Implements Black-Scholes-Merton model with continuous dividend yield.
    """

    def __init__(self, S, K, T, r, sigma, q=0.0):
        """
        Parameters
        ----------
        S     : float – Current underlying price
        K     : float – Strike price
        T     : float – Time to expiration in years
        r     : float – Risk-free interest rate (decimal)
        sigma : float – Implied volatility (decimal)
        q     : float – Continuous dividend yield (decimal)
        """
        self.S = S
        self.K = K
        self.T = max(T, 1e-10)  # Avoid division by zero
        self.r = r
        self.sigma = sigma
        self.q = q
        self._compute_d1_d2()

    def _compute_d1_d2(self):
        """Pre-compute d1 and d2 used across all formulas."""
        S, K, T, r, sigma, q = self.S, self.K, self.T, self.r, self.sigma, self.q
        sqrt_T = math.sqrt(T)
        self.d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
        self.d2 = self.d1 - sigma * sqrt_T

    # ── Pricing ──────────────────────────────────────────────────────────

    def call_price(self):
        """Theoretical call option price."""
        S, K, T, r, q = self.S, self.K, self.T, self.r, self.q
        return S * math.exp(-q * T) * norm.cdf(self.d1) - K * math.exp(-r * T) * norm.cdf(self.d2)

    def put_price(self):
        """Theoretical put option price."""
        S, K, T, r, q = self.S, self.K, self.T, self.r, self.q
        return K * math.exp(-r * T) * norm.cdf(-self.d2) - S * math.exp(-q * T) * norm.cdf(-self.d1)

    # ── Greeks ───────────────────────────────────────────────────────────

    def delta(self, option_type="call"):
        exp_qT = math.exp(-self.q * self.T)
        if option_type == "call":
            return exp_qT * norm.cdf(self.d1)
        else:
            return exp_qT * (norm.cdf(self.d1) - 1.0)

    def gamma(self):
        """Gamma is the same for calls and puts."""
        S, T, sigma, q = self.S, self.T, self.sigma, self.q
        return (math.exp(-q * T) * norm.pdf(self.d1)) / (S * sigma * math.sqrt(T))

    def theta(self, option_type="call"):
        """Theta in dollars per calendar day."""
        S, K, T, r, sigma, q = self.S, self.K, self.T, self.r, self.sigma, self.q
        sqrt_T = math.sqrt(T)
        common = -(S * sigma * math.exp(-q * T) * norm.pdf(self.d1)) / (2.0 * sqrt_T)
        if option_type == "call":
            theta_annual = (common
                            + q * S * math.exp(-q * T) * norm.cdf(self.d1)
                            - r * K * math.exp(-r * T) * norm.cdf(self.d2))
        else:
            theta_annual = (common
                            - q * S * math.exp(-q * T) * norm.cdf(-self.d1)
                            + r * K * math.exp(-r * T) * norm.cdf(-self.d2))
        return theta_annual / 365.0

    def vega(self):
        """Vega per 1% change in IV. Same for calls and puts."""
        S, T, q = self.S, self.T, self.q
        return S * math.exp(-q * T) * norm.pdf(self.d1) * math.sqrt(T) * 0.01

    def rho(self, option_type="call"):
        """Rho per 1% change in interest rate."""
        K, T, r = self.K, self.T, self.r
        if option_type == "call":
            return K * T * math.exp(-r * T) * norm.cdf(self.d2) * 0.01
        else:
            return -K * T * math.exp(-r * T) * norm.cdf(-self.d2) * 0.01

    # ── Probabilities ────────────────────────────────────────────────────

    def prob_itm(self, option_type="call"):
        """Probability of expiring in-the-money (risk-neutral)."""
        if option_type == "call":
            return norm.cdf(self.d2)
        else:
            return norm.cdf(-self.d2)

    def prob_otm(self, option_type="call"):
        return 1.0 - self.prob_itm(option_type)

    def prob_above(self, price_level):
        """Probability that underlying finishes above a given price level."""
        S, T, r, sigma, q = self.S, self.T, self.r, self.sigma, self.q
        if price_level <= 0:
            return 1.0
        d = (math.log(S / price_level) + (r - q - 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        return norm.cdf(d)

    def prob_below(self, price_level):
        return 1.0 - self.prob_above(price_level)

    # ── Distribution helper ──────────────────────────────────────────────

    def price_distribution(self, num_points=500, num_std=4):
        """
        Generate lognormal price distribution at expiration.
        Returns (prices, pdf_values).
        """
        S, T, r, sigma, q = self.S, self.T, self.r, self.sigma, self.q
        mu = math.log(S) + (r - q - 0.5 * sigma ** 2) * T
        std = sigma * math.sqrt(T)
        log_low = mu - num_std * std
        log_high = mu + num_std * std
        prices = np.linspace(max(np.exp(log_low), 0.01), np.exp(log_high), num_points)
        pdf_vals = (1.0 / (prices * std * math.sqrt(2 * math.pi))) * \
                   np.exp(-0.5 * ((np.log(prices) - mu) / std) ** 2)
        return prices, pdf_vals

    def expected_move_1std(self):
        """1 standard deviation expected move."""
        return self.S * self.sigma * math.sqrt(self.T)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — TRADE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

class TradeAnalysis:
    """
    Wraps the BSM engine with trade-specific logic:
    premium, position direction, contract multiplier, and payoff curves.
    """

    MULTIPLIER = 100  # Standard equity option: 100 shares per contract

    def __init__(self, S, K, premium, dte, iv, r, q,
                 option_type, position_type, num_contracts,
                 expected_move=None, price_range=None):
        self.S = S
        self.K = K
        self.premium = premium
        self.dte = dte
        self.T = dte / 365.0
        self.iv = iv / 100.0      # Convert percentage to decimal
        self.r = r / 100.0
        self.q = q / 100.0
        self.option_type = option_type.lower()   # "call" or "put"
        self.position_type = position_type.lower()  # "long" or "short"
        self.num_contracts = num_contracts
        self.expected_move = expected_move
        self.price_range = price_range

        self.engine = BlackScholesEngine(S, K, self.T, self.r, self.iv, self.q)
        self._analyze()

    # ── Core metrics ─────────────────────────────────────────────────────

    def _analyze(self):
        ot = self.option_type
        pt = self.position_type
        S, K, prem = self.S, self.K, self.premium
        mult = self.MULTIPLIER
        n = self.num_contracts

        # Theoretical price
        self.bs_price = self.engine.call_price() if ot == "call" else self.engine.put_price()

        # Intrinsic / extrinsic
        if ot == "call":
            self.intrinsic = max(S - K, 0.0)
        else:
            self.intrinsic = max(K - S, 0.0)
        self.extrinsic = max(prem - self.intrinsic, 0.0)

        # Break-even
        if ot == "call":
            self.breakeven = K + prem
        else:
            self.breakeven = K - prem

        # Max profit / loss (per-contract dollar amounts)
        if pt == "long":
            self.max_loss = prem * mult * n
            if ot == "call":
                self.max_profit = float("inf")
            else:
                self.max_profit = max((K - prem) * mult * n, 0.0)
        else:  # short
            self.max_profit = prem * mult * n
            if ot == "call":
                self.max_loss = float("inf")
            else:
                self.max_loss = max((K - prem) * mult * n, 0.0)

        # Greeks
        self.delta = self.engine.delta(ot)
        self.gamma = self.engine.gamma()
        self.theta = self.engine.theta(ot)
        self.vega = self.engine.vega()
        self.rho = self.engine.rho(ot)

        # Adjust delta sign for short positions
        self.pos_delta = self.delta * (1 if pt == "long" else -1) * n * mult
        self.pos_gamma = self.gamma * (1 if pt == "long" else -1) * n * mult
        self.pos_theta = self.theta * (1 if pt == "long" else -1) * n * mult
        self.pos_vega = self.vega * (1 if pt == "long" else -1) * n * mult
        self.pos_rho = self.rho * (1 if pt == "long" else -1) * n * mult

        # Probabilities
        self.prob_itm = self.engine.prob_itm(ot)
        self.prob_otm = self.engine.prob_otm(ot)

        # Probability of profit depends on position and break-even
        if pt == "long":
            if ot == "call":
                self.prob_profit = self.engine.prob_above(self.breakeven)
            else:
                self.prob_profit = self.engine.prob_below(self.breakeven)
        else:
            if ot == "call":
                self.prob_profit = self.engine.prob_below(self.breakeven)
            else:
                self.prob_profit = self.engine.prob_above(self.breakeven)

        # Expected value estimate (simplified)
        # EV = ProbProfit * AvgWin – ProbLoss * AvgLoss
        # We approximate avg win/loss from the distribution
        self._compute_expected_value()

        # Risk-reward ratio
        if self.max_profit == float("inf") or self.max_loss == float("inf"):
            self.risk_reward = None
        elif self.max_loss == 0:
            self.risk_reward = float("inf")
        else:
            self.risk_reward = self.max_profit / self.max_loss

        # 1-sigma expected move
        self.expected_move_1std = self.engine.expected_move_1std()

    def _compute_expected_value(self):
        """
        Analytical expected value using Black-Scholes risk-neutral pricing.

        Under the risk-neutral measure the discounted expected payoff of an
        option equals its BS price, so the *undiscounted* expected payoff at
        expiration is:

            E[max(S_T − K, 0)]  =  BS_price × e^(rT)       (for a call)
            E[max(K − S_T, 0)]  =  BS_price × e^(rT)       (for a put)

        Expected P/L is then the difference between that expected payoff and
        the premium actually paid (or received), scaled by the contract
        multiplier and number of contracts.

        The old numerical-integration approach (trapezoidal rule over a
        linearly-spaced price grid) introduced a right-tail bias for calls
        that inflated EV.  This analytical version is exact.
        """
        r, T = self.engine.r, self.engine.T
        mult = self.MULTIPLIER
        n = self.num_contracts

        # Undiscounted expected option payoff at expiration
        if self.option_type == "call":
            bs = self.engine.call_price()
        else:
            bs = self.engine.put_price()
        expected_payoff_per_share = bs * math.exp(r * T)

        # Long pays premium, short receives it
        if self.position_type == "long":
            self.expected_value = (expected_payoff_per_share - self.premium) * mult * n
        else:
            self.expected_value = (self.premium - expected_payoff_per_share) * mult * n

    def _payoff_at_prices(self, price_array):
        """Vectorized payoff at expiration for an array of underlying prices."""
        ot, pt = self.option_type, self.position_type
        K, prem = self.K, self.premium
        mult = self.MULTIPLIER
        n = self.num_contracts

        if ot == "call":
            intrinsic = np.maximum(price_array - K, 0.0)
        else:
            intrinsic = np.maximum(K - price_array, 0.0)

        if pt == "long":
            payoff = (intrinsic - prem) * mult * n
        else:
            payoff = (prem - intrinsic) * mult * n
        return payoff

    # ── Graph data generators ────────────────────────────────────────────

    def payoff_curve(self, num_points=500):
        """Returns (prices, payoffs) for the payoff diagram."""
        if self.price_range:
            lo, hi = self.price_range
        else:
            spread = max(self.S * 0.30, abs(self.S - self.K) * 2.5, 10)
            lo = max(self.S - spread, 0.01)
            hi = self.S + spread
        prices = np.linspace(lo, hi, num_points)
        payoffs = self._payoff_at_prices(prices)
        return prices, payoffs

    def probability_distribution(self, num_points=500):
        return self.engine.price_distribution(num_points)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — MATPLOTLIB GRAPHING
# ═══════════════════════════════════════════════════════════════════════════

# Dark professional color palette
COLORS = {
    "bg":           "#1a1a2e",
    "panel":        "#16213e",
    "grid":         "#2a2a4a",
    "text":         "#e0e0e0",
    "accent":       "#00d4ff",
    "profit":       "#00e676",
    "loss":         "#ff5252",
    "strike":       "#ffc107",
    "breakeven":    "#ab47bc",
    "current":      "#00d4ff",
    "dist_fill":    "#4fc3f7",
    "profit_shade": "#00e67640",
    "loss_shade":   "#ff525230",
    "sigma_shade":  "#ffffff15",
}


def create_graph_window(analysis: TradeAnalysis):
    """Open a new top-level window with payoff + probability graphs."""

    # Build the figure
    fig = plt.figure(figsize=(16, 9), facecolor=COLORS["bg"])
    gs = gridspec.GridSpec(2, 2, height_ratios=[1.1, 1], width_ratios=[1.1, 1],
                           hspace=0.35, wspace=0.30,
                           left=0.07, right=0.96, top=0.93, bottom=0.07)

    ax_payoff = fig.add_subplot(gs[0, :])  # Payoff spans full top row
    ax_dist   = fig.add_subplot(gs[1, 0])  # Probability distribution bottom-left
    ax_info   = fig.add_subplot(gs[1, 1])  # Summary info panel bottom-right

    for ax in [ax_payoff, ax_dist, ax_info]:
        ax.set_facecolor(COLORS["panel"])
        ax.tick_params(colors=COLORS["text"], labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(COLORS["grid"])

    # ── 1. Payoff Diagram ────────────────────────────────────────────────

    prices, payoffs = analysis.payoff_curve()
    profit_mask = payoffs >= 0
    loss_mask = payoffs < 0

    ax_payoff.fill_between(prices, payoffs, 0, where=profit_mask,
                           color=COLORS["profit"], alpha=0.18, interpolate=True)
    ax_payoff.fill_between(prices, payoffs, 0, where=loss_mask,
                           color=COLORS["loss"], alpha=0.18, interpolate=True)
    ax_payoff.plot(prices, payoffs, color=COLORS["accent"], linewidth=2.2, zorder=5)
    ax_payoff.axhline(y=0, color=COLORS["text"], linewidth=0.6, alpha=0.4)

    # Mark strike price
    ax_payoff.axvline(x=analysis.K, color=COLORS["strike"], linewidth=1.2,
                      linestyle="--", alpha=0.85, label=f"Strike ${analysis.K:,.2f}")

    # Mark break-even
    ax_payoff.axvline(x=analysis.breakeven, color=COLORS["breakeven"], linewidth=1.2,
                      linestyle="--", alpha=0.85, label=f"Break-even ${analysis.breakeven:,.2f}")

    # Mark current price
    ax_payoff.axvline(x=analysis.S, color=COLORS["current"], linewidth=1.0,
                      linestyle=":", alpha=0.7, label=f"Current ${analysis.S:,.2f}")

    # Max profit / max loss annotations
    if analysis.max_profit != float("inf"):
        mp_y = analysis.max_profit
        ax_payoff.axhline(y=mp_y, color=COLORS["profit"], linewidth=0.8,
                          linestyle=":", alpha=0.5)
        ax_payoff.annotate(f"Max Profit ${mp_y:,.0f}",
                           xy=(prices[-1], mp_y), fontsize=8,
                           color=COLORS["profit"], ha="right", va="bottom")

    if analysis.max_loss != float("inf"):
        ml_y = -analysis.max_loss
        ax_payoff.axhline(y=ml_y, color=COLORS["loss"], linewidth=0.8,
                          linestyle=":", alpha=0.5)
        ax_payoff.annotate(f"Max Loss ${analysis.max_loss:,.0f}",
                           xy=(prices[-1], ml_y), fontsize=8,
                           color=COLORS["loss"], ha="right", va="top")

    ax_payoff.set_title("PAYOFF DIAGRAM AT EXPIRATION",
                        color=COLORS["text"], fontsize=13, fontweight="bold", pad=12)
    ax_payoff.set_xlabel("Underlying Price at Expiration ($)", color=COLORS["text"], fontsize=10)
    ax_payoff.set_ylabel("Profit / Loss ($)", color=COLORS["text"], fontsize=10)
    ax_payoff.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax_payoff.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax_payoff.legend(loc="upper left", fontsize=8, facecolor=COLORS["panel"],
                     edgecolor=COLORS["grid"], labelcolor=COLORS["text"])
    ax_payoff.grid(True, color=COLORS["grid"], linewidth=0.4, alpha=0.6)

    # ── 2. Probability Distribution ──────────────────────────────────────

    dist_prices, dist_pdf = analysis.probability_distribution()

    # Shade profitable region
    if analysis.position_type == "long":
        if analysis.option_type == "call":
            profit_region = dist_prices >= analysis.breakeven
        else:
            profit_region = dist_prices <= analysis.breakeven
    else:
        if analysis.option_type == "call":
            profit_region = dist_prices <= analysis.breakeven
        else:
            profit_region = dist_prices >= analysis.breakeven

    loss_region = ~profit_region

    ax_dist.fill_between(dist_prices, dist_pdf, 0, where=profit_region,
                         color=COLORS["profit"], alpha=0.30, label="Profitable Region")
    ax_dist.fill_between(dist_prices, dist_pdf, 0, where=loss_region,
                         color=COLORS["loss"], alpha=0.20, label="Loss Region")
    ax_dist.plot(dist_prices, dist_pdf, color=COLORS["dist_fill"], linewidth=1.8)

    # 1-sigma shading
    sigma_move = analysis.expected_move_1std
    lo_1s = analysis.S - sigma_move
    hi_1s = analysis.S + sigma_move
    sigma_mask = (dist_prices >= lo_1s) & (dist_prices <= hi_1s)
    ax_dist.fill_between(dist_prices, dist_pdf, 0, where=sigma_mask,
                         color="white", alpha=0.06, label="±1σ Range")

    # Vertical markers
    ax_dist.axvline(x=analysis.S, color=COLORS["current"], linewidth=1.2,
                    linestyle=":", alpha=0.8, label=f"Current ${analysis.S:,.2f}")
    ax_dist.axvline(x=analysis.K, color=COLORS["strike"], linewidth=1.2,
                    linestyle="--", alpha=0.8, label=f"Strike ${analysis.K:,.2f}")
    ax_dist.axvline(x=analysis.breakeven, color=COLORS["breakeven"], linewidth=1.2,
                    linestyle="--", alpha=0.8, label=f"BE ${analysis.breakeven:,.2f}")

    # 1-sigma boundaries
    ax_dist.axvline(x=lo_1s, color=COLORS["text"], linewidth=0.7,
                    linestyle=":", alpha=0.4)
    ax_dist.axvline(x=hi_1s, color=COLORS["text"], linewidth=0.7,
                    linestyle=":", alpha=0.4)
    ax_dist.annotate(f"-1σ\n${lo_1s:,.1f}", xy=(lo_1s, 0), fontsize=7,
                     color=COLORS["text"], alpha=0.6, ha="center", va="bottom",
                     xytext=(0, 4), textcoords="offset points")
    ax_dist.annotate(f"+1σ\n${hi_1s:,.1f}", xy=(hi_1s, 0), fontsize=7,
                     color=COLORS["text"], alpha=0.6, ha="center", va="bottom",
                     xytext=(0, 4), textcoords="offset points")

    ax_dist.set_title("PROBABILITY DISTRIBUTION AT EXPIRATION",
                      color=COLORS["text"], fontsize=11, fontweight="bold", pad=10)
    ax_dist.set_xlabel("Underlying Price ($)", color=COLORS["text"], fontsize=9)
    ax_dist.set_ylabel("Probability Density", color=COLORS["text"], fontsize=9)
    ax_dist.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax_dist.legend(loc="upper right", fontsize=7, facecolor=COLORS["panel"],
                   edgecolor=COLORS["grid"], labelcolor=COLORS["text"])
    ax_dist.grid(True, color=COLORS["grid"], linewidth=0.3, alpha=0.5)

    # ── 3. Summary Info Panel ────────────────────────────────────────────

    ax_info.axis("off")
    pos_label = f"{'LONG' if analysis.position_type == 'long' else 'SHORT'} {analysis.option_type.upper()}"
    summary_lines = [
        ("TRADE SETUP", "", True),
        ("Position", pos_label),
        ("Contracts", f"{analysis.num_contracts}"),
        ("Underlying", f"${analysis.S:,.2f}"),
        ("Strike", f"${analysis.K:,.2f}"),
        ("Premium", f"${analysis.premium:,.2f}"),
        ("DTE", f"{analysis.dte} days"),
        ("IV", f"{analysis.iv * 100:.1f}%"),
        ("", ""),
        ("KEY METRICS", "", True),
        ("BS Price", f"${analysis.bs_price:,.4f}"),
        ("Intrinsic", f"${analysis.intrinsic:,.2f}"),
        ("Extrinsic", f"${analysis.extrinsic:,.2f}"),
        ("Break-even", f"${analysis.breakeven:,.2f}"),
        ("Max Profit", f"${analysis.max_profit:,.0f}" if analysis.max_profit != float("inf") else "Unlimited"),
        ("Max Loss", f"${analysis.max_loss:,.0f}" if analysis.max_loss != float("inf") else "Unlimited"),
        ("", ""),
        ("PROBABILITIES", "", True),
        ("P(Profit)", f"{analysis.prob_profit * 100:.1f}%"),
        ("P(ITM)", f"{analysis.prob_itm * 100:.1f}%"),
        ("P(OTM)", f"{analysis.prob_otm * 100:.1f}%"),
        ("±1σ Move", f"${analysis.expected_move_1std:,.2f}"),
        ("Exp. Value", f"${analysis.expected_value:,.2f}"),
        ("Risk/Reward",
         f"{analysis.risk_reward:.2f}" if analysis.risk_reward is not None else "N/A"),
    ]

    y_pos = 0.97
    for item in summary_lines:
        if len(item) == 3 and item[2] is True:
            # Section header
            ax_info.text(0.5, y_pos, item[0], transform=ax_info.transAxes,
                         fontsize=10, fontweight="bold", color=COLORS["accent"],
                         ha="center", va="top",
                         fontfamily="monospace")
            y_pos -= 0.050
        elif item[0] == "" and item[1] == "":
            y_pos -= 0.025  # Spacer
        else:
            ax_info.text(0.08, y_pos, item[0], transform=ax_info.transAxes,
                         fontsize=8.5, color=COLORS["text"], alpha=0.7,
                         va="top", fontfamily="monospace")
            color = COLORS["text"]
            if "Profit" in item[0] and "%" in item[1]:
                pct = analysis.prob_profit * 100
                color = COLORS["profit"] if pct >= 50 else COLORS["loss"]
            ax_info.text(0.92, y_pos, item[1], transform=ax_info.transAxes,
                         fontsize=8.5, color=color, va="top",
                         ha="right", fontfamily="monospace")
            y_pos -= 0.038

    # ── Show in new window ───────────────────────────────────────────────

    graph_win = ctk.CTkToplevel()
    graph_win.title("Options Analysis — Graphs")
    graph_win.geometry("1380x780")
    graph_win.configure(fg_color=COLORS["bg"])

    canvas = FigureCanvasTkAgg(fig, master=graph_win)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)

    graph_win.after(100, lambda: graph_win.lift())
    graph_win.after(100, lambda: graph_win.focus_force())


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — GUI APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

class OptionsCalculatorApp(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # ── Window setup ─────────────────────────────────────────────────
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Professional Options Calculator")
        self.geometry("1180x920")
        self.minsize(1000, 750)
        self.configure(fg_color="#0f0f1e")

        self._build_ui()

    # ── UI Construction ──────────────────────────────────────────────────

    def _build_ui(self):
        # Title bar
        title_frame = ctk.CTkFrame(self, fg_color="#0f0f1e", height=50)
        title_frame.pack(fill="x", padx=20, pady=(14, 4))
        ctk.CTkLabel(title_frame, text="⬡  OPTIONS CALCULATOR",
                     font=ctk.CTkFont(family="Helvetica", size=22, weight="bold"),
                     text_color="#00d4ff").pack(side="left")
        ctk.CTkLabel(title_frame, text="Black-Scholes Pricing & Analytics",
                     font=ctk.CTkFont(size=12), text_color="#808090").pack(side="left", padx=(12, 0))

        # Main horizontal layout
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=(4, 14))

        # Left panel — inputs
        left = ctk.CTkFrame(main, fg_color="#161628", corner_radius=12, width=420)
        left.pack(side="left", fill="y", padx=(0, 10), pady=0)
        left.pack_propagate(False)

        # Right panel — results
        right = ctk.CTkFrame(main, fg_color="#161628", corner_radius=12)
        right.pack(side="left", fill="both", expand=True, pady=0)

        self._build_inputs(left)
        self._build_results(right)

    def _build_inputs(self, parent):
        """Construct all input fields inside the left panel."""

        # Scrollable frame for inputs
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                        scrollbar_button_color="#2a2a4a")
        scroll.pack(fill="both", expand=True, padx=12, pady=12)

        # Helper to create a labeled entry
        self.entries = {}

        def add_entry(parent_frame, label, key, default="", row=0, width=160):
            ctk.CTkLabel(parent_frame, text=label,
                         font=ctk.CTkFont(size=12),
                         text_color="#b0b0c0").grid(row=row, column=0,
                                                     sticky="w", padx=(8, 4), pady=4)
            entry = ctk.CTkEntry(parent_frame, width=width,
                                 fg_color="#1e1e38", border_color="#2a2a5a",
                                 text_color="#e0e0e0",
                                 font=ctk.CTkFont(size=13))
            entry.grid(row=row, column=1, sticky="e", padx=(4, 8), pady=4)
            entry.insert(0, default)
            self.entries[key] = entry
            return entry

        def section_header(parent_frame, text):
            hdr = ctk.CTkLabel(parent_frame, text=text,
                               font=ctk.CTkFont(size=13, weight="bold"),
                               text_color="#00d4ff")
            hdr.pack(anchor="w", padx=8, pady=(12, 4))
            sep = ctk.CTkFrame(parent_frame, height=1, fg_color="#2a2a5a")
            sep.pack(fill="x", padx=8, pady=(0, 6))

        # ── Market Data section ──────────────────────────────────────────
        section_header(scroll, "MARKET DATA")
        frame_market = ctk.CTkFrame(scroll, fg_color="transparent")
        frame_market.pack(fill="x")
        frame_market.columnconfigure(1, weight=1)

        add_entry(frame_market, "Underlying Price ($)", "S", "100.00", row=0)
        add_entry(frame_market, "Strike Price ($)", "K", "105.00", row=1)
        add_entry(frame_market, "Premium ($)", "premium", "3.50", row=2)
        add_entry(frame_market, "Days to Expiration", "dte", "30", row=3)
        add_entry(frame_market, "Implied Volatility (%)", "iv", "25.0", row=4)
        add_entry(frame_market, "Risk-Free Rate (%)", "r", "5.0", row=5)
        add_entry(frame_market, "Dividend Yield (%)", "q", "0.0", row=6)

        # ── Position section ─────────────────────────────────────────────
        section_header(scroll, "POSITION")
        frame_pos = ctk.CTkFrame(scroll, fg_color="transparent")
        frame_pos.pack(fill="x")
        frame_pos.columnconfigure(1, weight=1)

        # Option type radio
        ctk.CTkLabel(frame_pos, text="Option Type",
                     font=ctk.CTkFont(size=12),
                     text_color="#b0b0c0").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=4)
        self.option_type_var = ctk.StringVar(value="Call")
        ot_frame = ctk.CTkFrame(frame_pos, fg_color="transparent")
        ot_frame.grid(row=0, column=1, sticky="e", padx=(4, 8), pady=4)
        ctk.CTkRadioButton(ot_frame, text="Call", variable=self.option_type_var,
                           value="Call", font=ctk.CTkFont(size=12),
                           text_color="#e0e0e0", fg_color="#00d4ff",
                           hover_color="#0099cc").pack(side="left", padx=(0, 10))
        ctk.CTkRadioButton(ot_frame, text="Put", variable=self.option_type_var,
                           value="Put", font=ctk.CTkFont(size=12),
                           text_color="#e0e0e0", fg_color="#00d4ff",
                           hover_color="#0099cc").pack(side="left")

        # Position type radio
        ctk.CTkLabel(frame_pos, text="Position Type",
                     font=ctk.CTkFont(size=12),
                     text_color="#b0b0c0").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=4)
        self.position_type_var = ctk.StringVar(value="Long")
        pt_frame = ctk.CTkFrame(frame_pos, fg_color="transparent")
        pt_frame.grid(row=1, column=1, sticky="e", padx=(4, 8), pady=4)
        ctk.CTkRadioButton(pt_frame, text="Long", variable=self.position_type_var,
                           value="Long", font=ctk.CTkFont(size=12),
                           text_color="#e0e0e0", fg_color="#00d4ff",
                           hover_color="#0099cc").pack(side="left", padx=(0, 10))
        ctk.CTkRadioButton(pt_frame, text="Short", variable=self.position_type_var,
                           value="Short", font=ctk.CTkFont(size=12),
                           text_color="#e0e0e0", fg_color="#00d4ff",
                           hover_color="#0099cc").pack(side="left")

        # Number of contracts
        add_entry(frame_pos, "# Contracts", "contracts", "1", row=2)

        # ── Optional section ─────────────────────────────────────────────
        section_header(scroll, "OPTIONAL")
        frame_opt = ctk.CTkFrame(scroll, fg_color="transparent")
        frame_opt.pack(fill="x")
        frame_opt.columnconfigure(1, weight=1)

        add_entry(frame_opt, "Expected Move ($)", "expected_move", "", row=0)
        add_entry(frame_opt, "Graph Low Price ($)", "range_low", "", row=1)
        add_entry(frame_opt, "Graph High Price ($)", "range_high", "", row=2)

        # Tooltip for expected move
        ctk.CTkLabel(frame_opt, text="   Leave blank for auto-calculated values",
                     font=ctk.CTkFont(size=10, slant="italic"),
                     text_color="#606080").grid(row=3, column=0, columnspan=2,
                                                sticky="w", padx=8, pady=(0, 4))

        # ── Buttons ──────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(16, 4))

        ctk.CTkButton(btn_frame, text="⚡  CALCULATE",
                      font=ctk.CTkFont(size=15, weight="bold"),
                      fg_color="#00d4ff", hover_color="#0099bb",
                      text_color="#0f0f1e", height=44, corner_radius=8,
                      command=self._on_calculate).pack(fill="x", padx=8, pady=(0, 6))

        ctk.CTkButton(btn_frame, text="📊  SHOW GRAPHS",
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color="#1e1e48", hover_color="#2a2a6a",
                      text_color="#00d4ff", height=40, corner_radius=8,
                      border_width=1, border_color="#00d4ff",
                      command=self._on_show_graph).pack(fill="x", padx=8, pady=(0, 6))

        ctk.CTkButton(btn_frame, text="↺  RESET",
                      font=ctk.CTkFont(size=13),
                      fg_color="#2a1a1a", hover_color="#3a2020",
                      text_color="#ff5252", height=36, corner_radius=8,
                      command=self._on_reset).pack(fill="x", padx=8)

    def _build_results(self, parent):
        """Construct the results display panel on the right."""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                        scrollbar_button_color="#2a2a4a")
        scroll.pack(fill="both", expand=True, padx=12, pady=12)

        self.results_frame = scroll
        self._show_placeholder()

    def _show_placeholder(self):
        """Show placeholder text before first calculation."""
        for widget in self.results_frame.winfo_children():
            widget.destroy()
        ph = ctk.CTkLabel(self.results_frame,
                          text="\n\n\n⬡\n\nEnter your trade parameters\nand click CALCULATE\n\n"
                               "Results will appear here with\nfull Greeks, probabilities,\n"
                               "and trade metrics.",
                          font=ctk.CTkFont(size=14),
                          text_color="#404060", justify="center")
        ph.pack(expand=True, fill="both", pady=40)

    # ── Input parsing ────────────────────────────────────────────────────

    def _parse_inputs(self):
        """Validate and parse all input fields. Returns dict or raises ValueError."""
        def get_float(key, allow_empty=False, positive=True):
            val = self.entries[key].get().strip()
            if val == "":
                if allow_empty:
                    return None
                raise ValueError(f"'{key}' cannot be empty.")
            v = float(val)
            if positive and v < 0:
                raise ValueError(f"'{key}' must be non-negative.")
            return v

        def get_int(key):
            val = self.entries[key].get().strip()
            v = int(val)
            if v < 1:
                raise ValueError(f"'{key}' must be at least 1.")
            return v

        S = get_float("S")
        K = get_float("K")
        premium = get_float("premium")
        dte = get_float("dte")
        iv = get_float("iv")
        r = get_float("r", positive=False)
        q = get_float("q")
        contracts = get_int("contracts")
        expected_move = get_float("expected_move", allow_empty=True)
        range_low = get_float("range_low", allow_empty=True)
        range_high = get_float("range_high", allow_empty=True)

        if S <= 0:
            raise ValueError("Underlying price must be positive.")
        if K <= 0:
            raise ValueError("Strike price must be positive.")
        if dte <= 0:
            raise ValueError("Days to expiration must be positive.")
        if iv <= 0:
            raise ValueError("Implied volatility must be positive.")

        price_range = None
        if range_low is not None and range_high is not None:
            if range_low >= range_high:
                raise ValueError("Graph low price must be less than high price.")
            price_range = (range_low, range_high)

        return {
            "S": S, "K": K, "premium": premium, "dte": dte,
            "iv": iv, "r": r, "q": q,
            "option_type": self.option_type_var.get(),
            "position_type": self.position_type_var.get(),
            "num_contracts": contracts,
            "expected_move": expected_move,
            "price_range": price_range,
        }

    # ── Calculation ──────────────────────────────────────────────────────

    def _run_analysis(self, params):
        self.last_analysis = TradeAnalysis(
            S=params["S"], K=params["K"], premium=params["premium"],
            dte=params["dte"], iv=params["iv"], r=params["r"], q=params["q"],
            option_type=params["option_type"],
            position_type=params["position_type"],
            num_contracts=params["num_contracts"],
            expected_move=params["expected_move"],
            price_range=params["price_range"],
        )
        return self.last_analysis

    def _on_calculate(self):
        try:
            params = self._parse_inputs()
        except (ValueError, Exception) as e:
            messagebox.showerror("Input Error", str(e))
            return

        try:
            analysis = self._run_analysis(params)
        except Exception as e:
            messagebox.showerror("Calculation Error", f"An error occurred:\n{e}")
            return

        self._display_results(analysis)

    def _on_show_graph(self):
        if not hasattr(self, "last_analysis"):
            messagebox.showinfo("No Data", "Please click CALCULATE first.")
            return
        try:
            create_graph_window(self.last_analysis)
        except Exception as e:
            messagebox.showerror("Graph Error", f"Could not create graphs:\n{e}")

    def _on_reset(self):
        defaults = {
            "S": "100.00", "K": "105.00", "premium": "3.50",
            "dte": "30", "iv": "25.0", "r": "5.0", "q": "0.0",
            "contracts": "1", "expected_move": "",
            "range_low": "", "range_high": "",
        }
        for key, val in defaults.items():
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, val)
        self.option_type_var.set("Call")
        self.position_type_var.set("Long")
        if hasattr(self, "last_analysis"):
            del self.last_analysis
        self._show_placeholder()

    # ── Results display ──────────────────────────────────────────────────

    def _display_results(self, a: TradeAnalysis):
        """Populate the right panel with calculated results."""
        frame = self.results_frame
        for widget in frame.winfo_children():
            widget.destroy()

        def section(title):
            f = ctk.CTkFrame(frame, fg_color="#1a1a35", corner_radius=8)
            f.pack(fill="x", pady=(8, 2), padx=4)
            ctk.CTkLabel(f, text=title,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color="#00d4ff").pack(anchor="w", padx=12, pady=(8, 2))
            sep = ctk.CTkFrame(f, height=1, fg_color="#2a2a5a")
            sep.pack(fill="x", padx=10, pady=(2, 6))
            return f

        def row(parent, label, value, color="#e0e0e0", tooltip=""):
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=1)
            lbl = ctk.CTkLabel(r, text=label,
                               font=ctk.CTkFont(size=12),
                               text_color="#9090a8")
            lbl.pack(side="left")
            if tooltip:
                tip = ctk.CTkLabel(r, text=" ⓘ",
                                   font=ctk.CTkFont(size=10),
                                   text_color="#505070")
                tip.pack(side="left")
                # Bind hover tooltip
                self._add_tooltip(tip, tooltip)
            ctk.CTkLabel(r, text=value,
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=color).pack(side="right")

        # ── Trade Summary ────────────────────────────────────────────────
        s = section(f"{'▲' if a.position_type == 'long' else '▼'}  "
                    f"{a.position_type.upper()} {a.option_type.upper()}  —  "
                    f"{a.num_contracts} Contract{'s' if a.num_contracts > 1 else ''}")
        row(s, "Underlying", f"${a.S:,.2f}")
        row(s, "Strike", f"${a.K:,.2f}")
        row(s, "Premium", f"${a.premium:,.2f}  (${a.premium * 100 * a.num_contracts:,.0f} total)")
        row(s, "DTE", f"{a.dte} days")
        row(s, "IV", f"{a.iv * 100:.1f}%")
        # Spacer
        ctk.CTkFrame(s, height=4, fg_color="transparent").pack()

        # ── Pricing ──────────────────────────────────────────────────────
        s = section("PRICING")
        row(s, "BS Theoretical Price", f"${a.bs_price:,.4f}",
            tooltip="Black-Scholes model fair value for this option")
        diff = a.premium - a.bs_price
        diff_color = "#00e676" if diff <= 0 else "#ff5252"
        row(s, "Premium vs BS Price",
            f"{'Overpaying' if diff > 0 else 'Underpaying'} by ${abs(diff):,.4f}",
            color=diff_color)
        row(s, "Intrinsic Value", f"${a.intrinsic:,.2f}",
            tooltip="Value if exercised now: max(S-K, 0) for calls, max(K-S, 0) for puts")
        row(s, "Extrinsic Value", f"${a.extrinsic:,.2f}",
            tooltip="Time value = Premium – Intrinsic")
        ctk.CTkFrame(s, height=4, fg_color="transparent").pack()

        # ── Risk Metrics ─────────────────────────────────────────────────
        s = section("RISK / REWARD")
        row(s, "Break-even", f"${a.breakeven:,.2f}")
        mp_str = f"${a.max_profit:,.2f}" if a.max_profit != float("inf") else "Unlimited"
        ml_str = f"${a.max_loss:,.2f}" if a.max_loss != float("inf") else "Unlimited"
        row(s, "Max Profit", mp_str, color="#00e676")
        row(s, "Max Loss", ml_str, color="#ff5252")
        rr = f"{a.risk_reward:.2f}" if a.risk_reward is not None else "N/A"
        row(s, "Risk/Reward Ratio", rr,
            tooltip="Max Profit / Max Loss")
        row(s, "Expected Value", f"${a.expected_value:,.2f}",
            color="#00e676" if a.expected_value > 0 else "#ff5252",
            tooltip="Probability-weighted average P/L across all outcomes")
        ctk.CTkFrame(s, height=4, fg_color="transparent").pack()

        # ── Probabilities ────────────────────────────────────────────────
        s = section("PROBABILITIES")
        pp_color = "#00e676" if a.prob_profit >= 0.5 else "#ff5252"
        row(s, "Probability of Profit", f"{a.prob_profit * 100:.1f}%", color=pp_color,
            tooltip="Chance the position is profitable at expiration")
        row(s, "Probability ITM", f"{a.prob_itm * 100:.1f}%",
            tooltip="Chance option expires in-the-money")
        row(s, "Probability OTM", f"{a.prob_otm * 100:.1f}%",
            tooltip="Chance option expires out-of-the-money")
        row(s, "±1σ Expected Move", f"${a.expected_move_1std:,.2f}",
            tooltip="68% of the time the price will move less than this")
        row(s, "1σ Range",
            f"${a.S - a.expected_move_1std:,.2f} – ${a.S + a.expected_move_1std:,.2f}")
        ctk.CTkFrame(s, height=4, fg_color="transparent").pack()

        # ── Greeks ───────────────────────────────────────────────────────
        s = section("GREEKS  (per-option)")
        row(s, "Delta", f"{a.delta:+.4f}",
            tooltip="Rate of change of option price per $1 move in the underlying")
        row(s, "Gamma", f"{a.gamma:+.4f}",
            tooltip="Rate of change of Delta per $1 move in the underlying")
        row(s, "Theta", f"{a.theta:+.4f}  /day",
            tooltip="Daily time decay – how much the option loses per calendar day")
        row(s, "Vega", f"{a.vega:+.4f}  /1% IV",
            tooltip="Option price change per 1% change in implied volatility")
        row(s, "Rho", f"{a.rho:+.4f}  /1% rate",
            tooltip="Option price change per 1% change in interest rate")
        ctk.CTkFrame(s, height=4, fg_color="transparent").pack()

        # ── Position Greeks ──────────────────────────────────────────────
        s = section("POSITION GREEKS  (total)")
        sign = "+" if a.position_type == "long" else "–"
        row(s, "Position Delta", f"{a.pos_delta:+,.2f}",
            tooltip="Equivalent stock exposure in shares")
        row(s, "Position Gamma", f"{a.pos_gamma:+,.4f}")
        row(s, "Position Theta", f"{a.pos_theta:+,.2f}  /day",
            color="#00e676" if a.pos_theta > 0 else "#ff5252",
            tooltip="Total daily P/L from time decay")
        row(s, "Position Vega", f"{a.pos_vega:+,.2f}  /1% IV")
        row(s, "Position Rho", f"{a.pos_rho:+,.4f}  /1% rate")
        ctk.CTkFrame(s, height=4, fg_color="transparent").pack()

        # ── Strategy Summary ─────────────────────────────────────────────
        s = section("STRATEGY NOTES")
        notes = self._generate_strategy_notes(a)
        for note in notes:
            r = ctk.CTkFrame(s, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(r, text=note,
                         font=ctk.CTkFont(size=11),
                         text_color="#b0b0c0",
                         wraplength=460, justify="left").pack(anchor="w")
        ctk.CTkFrame(s, height=8, fg_color="transparent").pack()

    def _generate_strategy_notes(self, a: TradeAnalysis):
        """Generate contextual strategy commentary."""
        notes = []
        ot = a.option_type
        pt = a.position_type

        # Directional bias
        if pt == "long":
            if ot == "call":
                notes.append("• Bullish position — profits when the underlying rises above break-even.")
            else:
                notes.append("• Bearish position — profits when the underlying falls below break-even.")
        else:
            if ot == "call":
                notes.append("• Bearish/neutral position — profits if underlying stays below break-even.")
            else:
                notes.append("• Bullish/neutral position — profits if underlying stays above break-even.")

        # IV assessment
        if a.premium > a.bs_price * 1.05:
            notes.append("• Premium is above BS fair value — option may be relatively expensive.")
        elif a.premium < a.bs_price * 0.95:
            notes.append("• Premium is below BS fair value — option may be relatively cheap.")
        else:
            notes.append("• Premium is roughly in line with BS theoretical value.")

        # Time decay
        if pt == "long":
            notes.append(f"• Time decay works against you: ~${abs(a.pos_theta):,.2f}/day lost to theta.")
        else:
            notes.append(f"• Time decay works in your favor: ~${abs(a.pos_theta):,.2f}/day earned from theta.")

        # Probability of profit
        if a.prob_profit >= 0.6:
            notes.append(f"• Favorable probability profile: {a.prob_profit * 100:.0f}% chance of profit.")
        elif a.prob_profit <= 0.35:
            notes.append(f"• Low probability of profit ({a.prob_profit * 100:.0f}%) — consider risk carefully.")

        # Expected value
        if a.expected_value > 0:
            notes.append(f"• Positive expected value (${a.expected_value:,.2f}) suggests a statistically favorable trade.")
        else:
            notes.append(f"• Negative expected value (${a.expected_value:,.2f}) — the odds slightly favor the other side.")

        return notes

    def _add_tooltip(self, widget, text):
        """Bind a hover tooltip to a widget."""
        tip_window = [None]

        def show(event):
            if tip_window[0]:
                return
            tw = tk.Toplevel(widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{event.x_root + 12}+{event.y_root - 8}")
            tw.configure(bg="#1a1a35")
            label = tk.Label(tw, text=text, bg="#1a1a35", fg="#c0c0d0",
                             font=("Helvetica", 10), padx=8, pady=4,
                             relief="solid", borderwidth=1, highlightbackground="#2a2a5a")
            label.pack()
            tip_window[0] = tw

        def hide(event):
            if tip_window[0]:
                tip_window[0].destroy()
                tip_window[0] = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = OptionsCalculatorApp()
    app.mainloop()