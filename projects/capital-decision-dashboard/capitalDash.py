"""
Personal Capital Decision Dashboard
A premium financial decision assistant built with CustomTkinter.
"""

import customtkinter as ctk
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# ─── THEME CONSTANTS ─────────────────────────────────────────────────────────
BG_PRIMARY   = "#222831"
BG_SECONDARY = "#393E46"
ACCENT       = "#948979"
TEXT_PRIMARY  = "#DFD0B8"
TEXT_DIM      = "#8a8070"
CARD_BG      = "#2a3040"
SUCCESS      = "#6BCB77"
WARNING      = "#FFD93D"
DANGER       = "#FF6B6B"
CHART_COLORS = ["#948979", "#6BCB77", "#FFD93D", "#FF6B6B", "#4ECDC4",
                "#C47AFF", "#FF9A76", "#679BFF", "#FF78A2", "#A0E7E5"]

DATA_FILE = os.path.join(str(Path.home()), ".capital_dashboard_data.json")

# ─── DATA PERSISTENCE ────────────────────────────────────────────────────────
def load_data():
    default = {
        "net_worth": {"cash": 0, "investments": 0, "assets": 0, "debts": 0, "history": []},
        "expenses": [],
        "investment_plan": {"portfolio_value": 0, "monthly_contribution": 0, "expected_return": 8},
        "goals": [],
        "monthly_income": 0,
        "settings": {"currency_symbol": "$"},
    }
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                saved = json.load(f)
            for k, v in default.items():
                if k not in saved:
                    saved[k] = v
            return saved
        except Exception:
            return default
    return default


def save_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        print(f"Save error: {e}")


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def fmt_currency(val, symbol="$"):
    if val >= 1_000_000:
        return f"{symbol}{val/1_000_000:,.1f}M"
    if val >= 10_000:
        return f"{symbol}{val/1_000:,.1f}K"
    return f"{symbol}{val:,.0f}"


def future_value(pv, pmt, rate_pct, years):
    r = rate_pct / 100 / 12
    n = int(years * 12)
    if r == 0:
        return pv + pmt * n
    fv = pv * (1 + r) ** n + pmt * (((1 + r) ** n - 1) / r)
    return fv


def months_to_target(pv, pmt, rate_pct, target):
    if pv >= target:
        return 0
    r = rate_pct / 100 / 12
    bal = pv
    for m in range(1, 12 * 100):
        bal = bal * (1 + r) + pmt
        if bal >= target:
            return m
    return None


# ─── REUSABLE WIDGETS ────────────────────────────────────────────────────────
class CardFrame(ctk.CTkFrame):
    def __init__(self, master, title=None, **kw):
        super().__init__(master, fg_color=CARD_BG, corner_radius=18, **kw)
        if title:
            ctk.CTkLabel(
                self, text=title, font=ctk.CTkFont(size=15, weight="bold"),
                text_color=ACCENT, anchor="w"
            ).pack(fill="x", padx=20, pady=(16, 4))


class MetricCard(ctk.CTkFrame):
    def __init__(self, master, label, value, sub="", color=ACCENT, **kw):
        super().__init__(master, fg_color=CARD_BG, corner_radius=16, **kw)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self, text=label, font=ctk.CTkFont(size=12),
            text_color=TEXT_DIM, anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 0))
        self.val_label = ctk.CTkLabel(
            self, text=value, font=ctk.CTkFont(size=26, weight="bold"),
            text_color=color, anchor="w"
        )
        self.val_label.grid(row=1, column=0, sticky="w", padx=18, pady=(2, 0))
        if sub:
            ctk.CTkLabel(
                self, text=sub, font=ctk.CTkFont(size=11),
                text_color=TEXT_DIM, anchor="w"
            ).grid(row=2, column=0, sticky="w", padx=18, pady=(0, 14))
        else:
            self.val_label.grid_configure(pady=(2, 14))

    def update_value(self, value, sub=None, color=None):
        self.val_label.configure(text=value)
        if color:
            self.val_label.configure(text_color=color)


class LabeledEntry(ctk.CTkFrame):
    def __init__(self, master, label, default="", width=200, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        ctk.CTkLabel(
            self, text=label, font=ctk.CTkFont(size=12),
            text_color=TEXT_DIM, anchor="w"
        ).pack(fill="x")
        self.entry = ctk.CTkEntry(
            self, width=width, height=38, corner_radius=10,
            fg_color=BG_SECONDARY, border_color=ACCENT, border_width=1,
            text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=13)
        )
        self.entry.pack(fill="x", pady=(4, 0))
        if default:
            self.entry.insert(0, str(default))

    def get_float(self, fallback=0.0):
        try:
            return float(self.entry.get().replace(",", "").replace("$", ""))
        except ValueError:
            return fallback

    def get_text(self):
        return self.entry.get().strip()

    def set_text(self, txt):
        self.entry.delete(0, "end")
        self.entry.insert(0, str(txt))


class AccentButton(ctk.CTkButton):
    def __init__(self, master, **kw):
        defaults = dict(
            fg_color=ACCENT, hover_color="#7a7060", text_color=BG_PRIMARY,
            corner_radius=12, height=40, font=ctk.CTkFont(size=13, weight="bold"),
        )
        defaults.update(kw)
        super().__init__(master, **defaults)


def make_chart(master, fig):
    canvas = FigureCanvasTkAgg(fig, master)
    canvas.draw()
    widget = canvas.get_tk_widget()
    widget.configure(bg=BG_PRIMARY, highlightthickness=0)
    return widget, canvas


# ─── MAIN APPLICATION ────────────────────────────────────────────────────────
class CapitalDashboardApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Capital Decision Dashboard")
        self.geometry("1180x780")
        self.minsize(1060, 700)
        self.configure(fg_color=BG_PRIMARY)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.data = load_data()
        self._build_ui()
        self.show_page("dashboard")

    # ── Sidebar ───────────────────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        sidebar = ctk.CTkFrame(self, fg_color=BG_SECONDARY, width=220, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        # Logo area
        logo_frame = ctk.CTkFrame(sidebar, fg_color="transparent", height=90)
        logo_frame.pack(fill="x", pady=(10, 0))
        logo_frame.pack_propagate(False)
        ctk.CTkLabel(
            logo_frame, text="◆", font=ctk.CTkFont(size=32), text_color=ACCENT
        ).pack(pady=(14, 0))
        ctk.CTkLabel(
            logo_frame, text="CAPITAL", font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY, anchor="center"
        ).pack()

        sep = ctk.CTkFrame(sidebar, fg_color=ACCENT, height=1)
        sep.pack(fill="x", padx=24, pady=(10, 18))

        nav_items = [
            ("dashboard",  "📊  Dashboard"),
            ("spending",   "💳  Spending"),
            ("investing",  "📈  Investing"),
            ("goals",      "🎯  Goals"),
            ("decisions",  "🧠  Decisions"),
        ]
        self.nav_buttons = {}
        for key, label in nav_items:
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w",
                fg_color="transparent", hover_color="#4a5060",
                text_color=TEXT_DIM, font=ctk.CTkFont(size=14),
                corner_radius=12, height=44,
                command=lambda k=key: self.show_page(k),
            )
            btn.pack(fill="x", padx=14, pady=2)
            self.nav_buttons[key] = btn

        # Bottom info
        bottom = ctk.CTkFrame(sidebar, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=18, pady=18)
        ctk.CTkLabel(
            bottom, text="All data stored locally",
            font=ctk.CTkFont(size=10), text_color=TEXT_DIM
        ).pack()

        # Content area
        self.content = ctk.CTkFrame(self, fg_color=BG_PRIMARY, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages = {}

    def show_page(self, name):
        for k, btn in self.nav_buttons.items():
            if k == name:
                btn.configure(fg_color=ACCENT, text_color=BG_PRIMARY)
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_DIM)

        for w in self.content.winfo_children():
            w.destroy()
        self.pages.clear()

        builder = {
            "dashboard": self._build_dashboard,
            "spending":  self._build_spending,
            "investing": self._build_investing,
            "goals":     self._build_goals,
            "decisions": self._build_decisions,
        }
        builder[name]()

    # ══════════════════════════════════════════════════════════════════════
    #  PAGE 1 — DASHBOARD
    # ══════════════════════════════════════════════════════════════════════
    def _build_dashboard(self):
        scroll = ctk.CTkScrollableFrame(
            self.content, fg_color=BG_PRIMARY, corner_radius=0,
            scrollbar_button_color=BG_SECONDARY, scrollbar_button_hover_color=ACCENT
        )
        scroll.pack(fill="both", expand=True, padx=0, pady=0)
        scroll.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(22, 4))
        ctk.CTkLabel(
            header, text="Net Worth Dashboard",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT_PRIMARY
        ).pack(side="left")
        ctk.CTkLabel(
            header, text=datetime.now().strftime("%B %d, %Y"),
            font=ctk.CTkFont(size=13), text_color=TEXT_DIM
        ).pack(side="right")

        # Metric cards row
        nw = self.data["net_worth"]
        total = nw["cash"] + nw["investments"] + nw["assets"] - nw["debts"]
        hist = nw.get("history", [])
        change = 0
        if len(hist) >= 2:
            change = hist[-1].get("total", 0) - hist[-2].get("total", 0)
        change_txt = f"{'▲' if change >= 0 else '▼'} {fmt_currency(abs(change))} since last update"

        metrics_row = ctk.CTkFrame(scroll, fg_color="transparent")
        metrics_row.pack(fill="x", padx=28, pady=(10, 6))
        for i in range(4):
            metrics_row.grid_columnconfigure(i, weight=1)

        cards_data = [
            ("Net Worth", fmt_currency(total), change_txt, SUCCESS if total >= 0 else DANGER),
            ("Cash", fmt_currency(nw["cash"]), "Liquid assets", TEXT_PRIMARY),
            ("Investments", fmt_currency(nw["investments"]), "Portfolio value", ACCENT),
            ("Debts", fmt_currency(nw["debts"]), "Total liabilities", DANGER if nw["debts"] > 0 else TEXT_DIM),
        ]
        for i, (lbl, val, sub, clr) in enumerate(cards_data):
            mc = MetricCard(metrics_row, lbl, val, sub, clr)
            mc.grid(row=0, column=i, sticky="nsew", padx=6, pady=4)

        # Input + Chart row
        mid_row = ctk.CTkFrame(scroll, fg_color="transparent")
        mid_row.pack(fill="x", padx=28, pady=(10, 6))
        mid_row.grid_columnconfigure(0, weight=1)
        mid_row.grid_columnconfigure(1, weight=1)

        # Input card
        inp_card = CardFrame(mid_row, title="Update Net Worth")
        inp_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)

        fields_frame = ctk.CTkFrame(inp_card, fg_color="transparent")
        fields_frame.pack(fill="x", padx=20, pady=(6, 4))
        fields_frame.grid_columnconfigure(0, weight=1)
        fields_frame.grid_columnconfigure(1, weight=1)

        self.nw_cash = LabeledEntry(fields_frame, "Cash", nw["cash"])
        self.nw_cash.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=4)
        self.nw_inv = LabeledEntry(fields_frame, "Investments", nw["investments"])
        self.nw_inv.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=4)
        self.nw_assets = LabeledEntry(fields_frame, "Assets", nw["assets"])
        self.nw_assets.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=4)
        self.nw_debts = LabeledEntry(fields_frame, "Debts", nw["debts"])
        self.nw_debts.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=4)

        AccentButton(
            inp_card, text="Save & Update", command=self._save_net_worth
        ).pack(padx=20, pady=(8, 18), fill="x")

        # Chart card
        chart_card = CardFrame(mid_row, title="Breakdown")
        chart_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)
        self._draw_nw_pie(chart_card, nw)

        # Daily Insights + Savings Rate row
        bot_row = ctk.CTkFrame(scroll, fg_color="transparent")
        bot_row.pack(fill="x", padx=28, pady=(10, 20))
        bot_row.grid_columnconfigure(0, weight=2)
        bot_row.grid_columnconfigure(1, weight=1)

        # Daily insights
        insight_card = CardFrame(bot_row, title="Daily Financial Insights")
        insight_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)
        insights = self._generate_insights()
        for ins in insights:
            row = ctk.CTkFrame(insight_card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=3)
            ctk.CTkLabel(row, text="•", text_color=ACCENT, font=ctk.CTkFont(size=14)).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                row, text=ins, font=ctk.CTkFont(size=13), text_color=TEXT_PRIMARY,
                wraplength=360, anchor="w", justify="left"
            ).pack(side="left", fill="x", expand=True)
        pad = ctk.CTkFrame(insight_card, fg_color="transparent", height=12)
        pad.pack()

        # Savings rate
        sr_card = CardFrame(bot_row, title="Savings Rate")
        sr_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)
        self._draw_savings_rate(sr_card)

    def _draw_nw_pie(self, parent, nw):
        vals = [max(nw["cash"], 0), max(nw["investments"], 0), max(nw["assets"], 0)]
        labels = ["Cash", "Invest", "Assets"]
        nonzero = [(v, l) for v, l in zip(vals, labels) if v > 0]
        if not nonzero:
            ctk.CTkLabel(
                parent, text="No data yet — enter your figures",
                font=ctk.CTkFont(size=13), text_color=TEXT_DIM
            ).pack(pady=40)
            return
        vals_f, labels_f = zip(*nonzero)
        fig = Figure(figsize=(3.4, 2.8), dpi=100, facecolor=CARD_BG)
        ax = fig.add_subplot(111)
        colors = CHART_COLORS[:len(vals_f)]
        wedges, texts, autotexts = ax.pie(
            vals_f, labels=labels_f, autopct="%1.0f%%", startangle=140,
            colors=colors, textprops={"color": TEXT_PRIMARY, "fontsize": 9},
            wedgeprops={"linewidth": 2, "edgecolor": CARD_BG}
        )
        for at in autotexts:
            at.set_fontsize(8)
            at.set_color(TEXT_PRIMARY)
        ax.set_facecolor(CARD_BG)
        fig.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.05)
        widget, _ = make_chart(parent, fig)
        widget.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _save_net_worth(self):
        nw = self.data["net_worth"]
        nw["cash"] = self.nw_cash.get_float()
        nw["investments"] = self.nw_inv.get_float()
        nw["assets"] = self.nw_assets.get_float()
        nw["debts"] = self.nw_debts.get_float()
        total = nw["cash"] + nw["investments"] + nw["assets"] - nw["debts"]
        nw["history"].append({"date": str(datetime.now().date()), "total": total})
        if len(nw["history"]) > 365:
            nw["history"] = nw["history"][-365:]
        save_data(self.data)
        self.show_page("dashboard")

    def _generate_insights(self):
        insights = []
        nw = self.data["net_worth"]
        total = nw["cash"] + nw["investments"] + nw["assets"] - nw["debts"]
        income = self.data.get("monthly_income", 0)
        expenses = self.data.get("expenses", [])
        goals = self.data.get("goals", [])

        now = datetime.now()
        month_expenses = [
            e for e in expenses
            if datetime.strptime(e["date"], "%Y-%m-%d").month == now.month
            and datetime.strptime(e["date"], "%Y-%m-%d").year == now.year
        ]
        total_month = sum(e["amount"] for e in month_expenses)

        if income > 0:
            sr = max(0, (income - total_month) / income * 100)
            if sr >= 40:
                insights.append(f"Your savings rate is {sr:.0f}% — outstanding performance!")
            elif sr >= 20:
                insights.append(f"Your savings rate is {sr:.0f}% — solid and consistent.")
            elif total_month > 0:
                insights.append(f"Your savings rate is {sr:.0f}% — consider reducing discretionary spending.")

        if len(nw.get("history", [])) >= 2:
            last_two = nw["history"][-2:]
            delta = last_two[1]["total"] - last_two[0]["total"]
            if delta > 0:
                insights.append(f"Net worth grew {fmt_currency(delta)} since last update — keep it up!")
            elif delta < 0:
                insights.append(f"Net worth decreased {fmt_currency(abs(delta))} — review recent spending.")

        if total_month > 0 and income > 0 and total_month > income * 0.8:
            insights.append("You've spent over 80% of your income already this month.")

        for g in goals:
            prog = min(g.get("current", 0) / max(g["target"], 1) * 100, 100)
            if prog >= 90:
                insights.append(f"Almost there! \"{g['name']}\" is {prog:.0f}% complete.")

        if nw["debts"] > 0 and nw["debts"] > nw["cash"]:
            insights.append("Your debts exceed your cash — prioritize paying down high-interest debt.")

        if total > 0 and nw["investments"] / max(total, 1) < 0.2:
            insights.append("Less than 20% of your net worth is invested — consider allocating more.")

        if not insights:
            insights.append("Welcome! Start by entering your net worth data above.")
            insights.append("Add expenses, goals, and income to unlock personalized insights.")
        return insights[:6]

    def _draw_savings_rate(self, parent):
        income = self.data.get("monthly_income", 0)
        now = datetime.now()
        month_exp = sum(
            e["amount"] for e in self.data.get("expenses", [])
            if datetime.strptime(e["date"], "%Y-%m-%d").month == now.month
            and datetime.strptime(e["date"], "%Y-%m-%d").year == now.year
        )
        if income <= 0:
            inner = ctk.CTkFrame(parent, fg_color="transparent")
            inner.pack(fill="x", padx=20, pady=(6, 18))
            ctk.CTkLabel(inner, text="Set income in", font=ctk.CTkFont(size=12), text_color=TEXT_DIM).pack()
            ctk.CTkLabel(inner, text="Spending page", font=ctk.CTkFont(size=12), text_color=ACCENT).pack()
            return
        sr = max(0, min((income - month_exp) / income * 100, 100))
        tiers = [("Elite 60%+", 60, SUCCESS), ("Strong 40%", 40, ACCENT), ("Good 20%", 20, WARNING)]

        inner = ctk.CTkFrame(parent, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=(6, 18))

        color = DANGER
        tier_name = "Needs Work"
        for name, threshold, clr in tiers:
            if sr >= threshold:
                color = clr
                tier_name = name.split()[0]
                break

        ctk.CTkLabel(
            inner, text=f"{sr:.0f}%",
            font=ctk.CTkFont(size=36, weight="bold"), text_color=color
        ).pack(pady=(4, 0))
        ctk.CTkLabel(
            inner, text=tier_name,
            font=ctk.CTkFont(size=14, weight="bold"), text_color=color
        ).pack()

        bar_bg = ctk.CTkFrame(inner, fg_color=BG_SECONDARY, height=14, corner_radius=7)
        bar_bg.pack(fill="x", pady=(10, 4))
        bar_bg.pack_propagate(False)
        fill_w = max(sr / 100, 0.02)
        bar_fill = ctk.CTkFrame(bar_bg, fg_color=color, corner_radius=7)
        bar_fill.place(relx=0, rely=0, relwidth=fill_w, relheight=1)

        for name, threshold, clr in tiers:
            row = ctk.CTkFrame(inner, fg_color="transparent")
            row.pack(fill="x", pady=1)
            dot = ctk.CTkFrame(row, fg_color=clr, width=8, height=8, corner_radius=4)
            dot.pack(side="left", padx=(0, 6))
            ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=11), text_color=TEXT_DIM).pack(side="left")

    # ══════════════════════════════════════════════════════════════════════
    #  PAGE 2 — SPENDING
    # ══════════════════════════════════════════════════════════════════════
    def _build_spending(self):
        scroll = ctk.CTkScrollableFrame(
            self.content, fg_color=BG_PRIMARY, corner_radius=0,
            scrollbar_button_color=BG_SECONDARY, scrollbar_button_hover_color=ACCENT
        )
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(
            scroll, text="Smart Spending Tracker",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT_PRIMARY
        ).pack(anchor="w", padx=28, pady=(22, 4))

        top_row = ctk.CTkFrame(scroll, fg_color="transparent")
        top_row.pack(fill="x", padx=28, pady=(10, 6))
        top_row.grid_columnconfigure(0, weight=1)
        top_row.grid_columnconfigure(1, weight=1)

        # Income + Add expense
        left_card = CardFrame(top_row, title="Log Expense")
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)

        inc_frame = ctk.CTkFrame(left_card, fg_color="transparent")
        inc_frame.pack(fill="x", padx=20, pady=(6, 2))
        self.income_entry = LabeledEntry(inc_frame, "Monthly Income", self.data.get("monthly_income", 0))
        self.income_entry.pack(fill="x")
        AccentButton(
            inc_frame, text="Set Income", height=32, command=self._save_income
        ).pack(fill="x", pady=(6, 4))

        sep2 = ctk.CTkFrame(left_card, fg_color=ACCENT, height=1)
        sep2.pack(fill="x", padx=20, pady=8)

        exp_fields = ctk.CTkFrame(left_card, fg_color="transparent")
        exp_fields.pack(fill="x", padx=20, pady=(0, 4))
        self.exp_amount = LabeledEntry(exp_fields, "Amount")
        self.exp_amount.pack(fill="x", pady=2)
        ctk.CTkLabel(
            exp_fields, text="Category", font=ctk.CTkFont(size=12), text_color=TEXT_DIM, anchor="w"
        ).pack(fill="x", pady=(4, 0))
        self.exp_cat = ctk.CTkOptionMenu(
            exp_fields, values=[
                "Food & Dining", "Shopping", "Transport", "Entertainment",
                "Health & Gym", "Bills & Utilities", "Education", "Subscriptions", "Other"
            ],
            fg_color=BG_SECONDARY, button_color=ACCENT, button_hover_color="#7a7060",
            text_color=TEXT_PRIMARY, corner_radius=10, height=38,
            font=ctk.CTkFont(size=13)
        )
        self.exp_cat.pack(fill="x", pady=(4, 0))
        self.exp_note = LabeledEntry(exp_fields, "Note (optional)")
        self.exp_note.pack(fill="x", pady=2)
        AccentButton(
            left_card, text="Add Expense", command=self._add_expense
        ).pack(padx=20, pady=(6, 18), fill="x")

        # Chart
        chart_card = CardFrame(top_row, title="Monthly Breakdown")
        chart_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)
        self._draw_spending_chart(chart_card)

        # Expense list
        list_card = CardFrame(scroll, title="Recent Expenses")
        list_card.pack(fill="x", padx=28, pady=(10, 20))

        expenses = sorted(self.data.get("expenses", []), key=lambda e: e["date"], reverse=True)[:20]
        if not expenses:
            ctk.CTkLabel(
                list_card, text="No expenses logged yet", font=ctk.CTkFont(size=13),
                text_color=TEXT_DIM
            ).pack(pady=20)
        else:
            # Header
            hdr = ctk.CTkFrame(list_card, fg_color="transparent")
            hdr.pack(fill="x", padx=20, pady=(10, 4))
            for txt, w in [("Date", 100), ("Category", 160), ("Amount", 100), ("Note", 180)]:
                ctk.CTkLabel(
                    hdr, text=txt, font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=TEXT_DIM, width=w, anchor="w"
                ).pack(side="left")

            for exp in expenses:
                row = ctk.CTkFrame(list_card, fg_color="transparent")
                row.pack(fill="x", padx=20, pady=2)
                ctk.CTkLabel(row, text=exp["date"], font=ctk.CTkFont(size=12), text_color=TEXT_DIM, width=100, anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=exp.get("category", ""), font=ctk.CTkFont(size=12), text_color=TEXT_PRIMARY, width=160, anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=fmt_currency(exp["amount"]), font=ctk.CTkFont(size=12), text_color=DANGER, width=100, anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=exp.get("note", ""), font=ctk.CTkFont(size=12), text_color=TEXT_DIM, width=180, anchor="w").pack(side="left")
            pad = ctk.CTkFrame(list_card, fg_color="transparent", height=14)
            pad.pack()

    def _save_income(self):
        self.data["monthly_income"] = self.income_entry.get_float()
        save_data(self.data)

    def _add_expense(self):
        amt = self.exp_amount.get_float()
        if amt <= 0:
            return
        self.data["expenses"].append({
            "date": str(datetime.now().date()),
            "amount": amt,
            "category": self.exp_cat.get(),
            "note": self.exp_note.get_text()
        })
        save_data(self.data)
        self.show_page("spending")

    def _draw_spending_chart(self, parent):
        now = datetime.now()
        month_exp = [
            e for e in self.data.get("expenses", [])
            if datetime.strptime(e["date"], "%Y-%m-%d").month == now.month
            and datetime.strptime(e["date"], "%Y-%m-%d").year == now.year
        ]
        if not month_exp:
            ctk.CTkLabel(parent, text="No data this month", font=ctk.CTkFont(size=13), text_color=TEXT_DIM).pack(pady=50)
            return

        cats = {}
        for e in month_exp:
            c = e.get("category", "Other")
            cats[c] = cats.get(c, 0) + e["amount"]

        total = sum(cats.values())
        unnecessary_cats = {"Shopping", "Entertainment", "Subscriptions"}
        unnecessary = sum(v for k, v in cats.items() if k in unnecessary_cats)

        labels = list(cats.keys())
        values = list(cats.values())

        fig = Figure(figsize=(3.6, 2.8), dpi=100, facecolor=CARD_BG)
        ax = fig.add_subplot(111)
        colors = CHART_COLORS[:len(labels)]
        bars = ax.barh(labels, values, color=colors, height=0.6, edgecolor=CARD_BG, linewidth=1)
        ax.set_facecolor(CARD_BG)
        ax.tick_params(colors=TEXT_DIM, labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color(TEXT_DIM)
        ax.spines["left"].set_color(TEXT_DIM)
        for b in bars:
            ax.text(b.get_width() + total * 0.02, b.get_y() + b.get_height() / 2,
                    fmt_currency(b.get_width()), va="center", fontsize=8, color=TEXT_PRIMARY)
        ax.set_xlim(0, max(values) * 1.25)
        fig.subplots_adjust(left=0.32, right=0.92, top=0.92, bottom=0.10)
        widget, _ = make_chart(parent, fig)
        widget.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        info = ctk.CTkFrame(parent, fg_color="transparent")
        info.pack(fill="x", padx=20, pady=(0, 14))
        ctk.CTkLabel(info, text=f"Total: {fmt_currency(total)}", font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_PRIMARY).pack(anchor="w")
        if unnecessary > 0:
            ctk.CTkLabel(
                info, text=f"Discretionary: ~{fmt_currency(unnecessary)} ({unnecessary/total*100:.0f}%)",
                font=ctk.CTkFont(size=12), text_color=WARNING
            ).pack(anchor="w")

    # ══════════════════════════════════════════════════════════════════════
    #  PAGE 3 — INVESTING
    # ══════════════════════════════════════════════════════════════════════
    def _build_investing(self):
        scroll = ctk.CTkScrollableFrame(
            self.content, fg_color=BG_PRIMARY, corner_radius=0,
            scrollbar_button_color=BG_SECONDARY, scrollbar_button_hover_color=ACCENT
        )
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(
            scroll, text="Investment Planner",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT_PRIMARY
        ).pack(anchor="w", padx=28, pady=(22, 4))

        top_row = ctk.CTkFrame(scroll, fg_color="transparent")
        top_row.pack(fill="x", padx=28, pady=(10, 6))
        top_row.grid_columnconfigure(0, weight=1)
        top_row.grid_columnconfigure(1, weight=2)

        # Inputs
        inp_card = CardFrame(top_row, title="Portfolio Settings")
        inp_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)

        ip = self.data["investment_plan"]
        fields = ctk.CTkFrame(inp_card, fg_color="transparent")
        fields.pack(fill="x", padx=20, pady=(6, 4))
        self.inv_portfolio = LabeledEntry(fields, "Current Portfolio Value ($)", ip["portfolio_value"])
        self.inv_portfolio.pack(fill="x", pady=4)
        self.inv_monthly = LabeledEntry(fields, "Monthly Contribution ($)", ip["monthly_contribution"])
        self.inv_monthly.pack(fill="x", pady=4)
        self.inv_return = LabeledEntry(fields, "Expected Annual Return (%)", ip["expected_return"])
        self.inv_return.pack(fill="x", pady=4)
        AccentButton(
            inp_card, text="Calculate Projections", command=self._calc_investing
        ).pack(padx=20, pady=(10, 18), fill="x")

        # Results
        self.inv_results = CardFrame(top_row, title="Growth Projections")
        self.inv_results.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)
        self._show_inv_projections(self.inv_results, ip)

        # Life impact calculator
        impact_card = CardFrame(scroll, title="Life Impact Calculator — What Could Your Money Become?")
        impact_card.pack(fill="x", padx=28, pady=(10, 20))

        imp_row = ctk.CTkFrame(impact_card, fg_color="transparent")
        imp_row.pack(fill="x", padx=20, pady=(6, 4))
        imp_row.grid_columnconfigure(0, weight=1)
        imp_row.grid_columnconfigure(1, weight=1)
        imp_row.grid_columnconfigure(2, weight=1)

        self.impact_amt = LabeledEntry(imp_row, "Amount ($)", "200")
        self.impact_amt.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=4)
        self.impact_rate = LabeledEntry(imp_row, "Growth Rate (%)", "10")
        self.impact_rate.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        btn_frame = ctk.CTkFrame(imp_row, fg_color="transparent")
        btn_frame.grid(row=0, column=2, sticky="sew", padx=(6, 0), pady=4)
        AccentButton(btn_frame, text="Calculate Impact", command=self._calc_impact).pack(fill="x", pady=(18, 0))

        self.impact_result = ctk.CTkLabel(
            impact_card, text="", font=ctk.CTkFont(size=14), text_color=TEXT_PRIMARY,
            wraplength=700, justify="left"
        )
        self.impact_result.pack(fill="x", padx=20, pady=(6, 18))
        self._calc_impact()

    def _show_inv_projections(self, parent, ip):
        for w in parent.winfo_children():
            if not isinstance(w, ctk.CTkLabel) or w.cget("text") != "Growth Projections":
                w.destroy()

        pv = ip["portfolio_value"]
        pmt = ip["monthly_contribution"]
        rate = ip["expected_return"]

        years = [1, 3, 5, 10, 20, 30]
        vals = [future_value(pv, pmt, rate, y) for y in years]

        # Chart
        fig = Figure(figsize=(5.2, 2.6), dpi=100, facecolor=CARD_BG)
        ax = fig.add_subplot(111)
        ax.set_facecolor(CARD_BG)
        months = np.arange(0, 361)
        r = rate / 100 / 12
        if r == 0:
            proj = pv + pmt * months
        else:
            proj = pv * (1 + r) ** months + pmt * (((1 + r) ** months - 1) / r)
        contrib = pv + pmt * months

        ax.fill_between(months / 12, contrib, alpha=0.3, color=TEXT_DIM, label="Contributions")
        ax.fill_between(months / 12, proj, contrib, alpha=0.4, color=ACCENT, label="Growth")
        ax.plot(months / 12, proj, color=ACCENT, linewidth=2)
        ax.set_xlabel("Years", fontsize=9, color=TEXT_DIM)
        ax.set_ylabel("Value", fontsize=9, color=TEXT_DIM)
        ax.tick_params(colors=TEXT_DIM, labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color(TEXT_DIM)
        ax.spines["left"].set_color(TEXT_DIM)
        ax.legend(fontsize=8, facecolor=CARD_BG, edgecolor=TEXT_DIM, labelcolor=TEXT_PRIMARY)
        fig.subplots_adjust(left=0.14, right=0.96, top=0.94, bottom=0.16)
        widget, _ = make_chart(parent, fig)
        widget.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        # Milestones
        milestones_frame = ctk.CTkFrame(parent, fg_color="transparent")
        milestones_frame.pack(fill="x", padx=20, pady=(4, 6))

        proj_row = ctk.CTkFrame(milestones_frame, fg_color="transparent")
        proj_row.pack(fill="x")
        for y, v in zip(years[:4], vals[:4]):
            ctk.CTkLabel(
                proj_row, text=f"{y}yr: {fmt_currency(v)}",
                font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_PRIMARY, width=120
            ).pack(side="left", padx=4)

        targets = [10_000, 50_000, 100_000, 500_000, 1_000_000]
        mile_row = ctk.CTkFrame(milestones_frame, fg_color="transparent")
        mile_row.pack(fill="x", pady=(6, 10))
        ctk.CTkLabel(mile_row, text="Milestones:", font=ctk.CTkFont(size=11, weight="bold"), text_color=ACCENT).pack(anchor="w")
        for t in targets:
            m = months_to_target(pv, pmt, rate, t)
            if m is not None and m > 0:
                yrs = m // 12
                mos = m % 12
                time_str = f"{yrs}y {mos}m" if yrs > 0 else f"{mos}m"
                ctk.CTkLabel(
                    mile_row, text=f"  {fmt_currency(t)} → {time_str}",
                    font=ctk.CTkFont(size=12), text_color=TEXT_PRIMARY
                ).pack(anchor="w")

    def _calc_investing(self):
        ip = self.data["investment_plan"]
        ip["portfolio_value"] = self.inv_portfolio.get_float()
        ip["monthly_contribution"] = self.inv_monthly.get_float()
        ip["expected_return"] = self.inv_return.get_float(8)
        save_data(self.data)
        self.show_page("investing")

    def _calc_impact(self):
        amt = self.impact_amt.get_float(200)
        rate = self.impact_rate.get_float(10)
        results = []
        for y in [1, 5, 10, 20]:
            fv = amt * (1 + rate / 100) ** y
            results.append(f"{y}yr → {fmt_currency(fv)}")
        fv10 = amt * (1 + rate / 100) ** 10
        self.impact_result.configure(
            text=f"That {fmt_currency(amt)} could become:  {'  |  '.join(results)}\n"
                 f"Every dollar you invest today is worth {fmt_currency(fv10/max(amt,1))} in 10 years at {rate:.0f}% return."
        )

    # ══════════════════════════════════════════════════════════════════════
    #  PAGE 4 — GOALS
    # ══════════════════════════════════════════════════════════════════════
    def _build_goals(self):
        scroll = ctk.CTkScrollableFrame(
            self.content, fg_color=BG_PRIMARY, corner_radius=0,
            scrollbar_button_color=BG_SECONDARY, scrollbar_button_hover_color=ACCENT
        )
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(
            scroll, text="Financial Goals Tracker",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT_PRIMARY
        ).pack(anchor="w", padx=28, pady=(22, 4))

        # Add goal
        add_card = CardFrame(scroll, title="Add New Goal")
        add_card.pack(fill="x", padx=28, pady=(10, 6))

        fields = ctk.CTkFrame(add_card, fg_color="transparent")
        fields.pack(fill="x", padx=20, pady=(6, 4))
        fields.grid_columnconfigure(0, weight=2)
        fields.grid_columnconfigure(1, weight=1)
        fields.grid_columnconfigure(2, weight=1)
        fields.grid_columnconfigure(3, weight=1)

        self.goal_name = LabeledEntry(fields, "Goal Name")
        self.goal_name.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=4)
        self.goal_target = LabeledEntry(fields, "Target ($)")
        self.goal_target.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        self.goal_current = LabeledEntry(fields, "Saved So Far ($)")
        self.goal_current.grid(row=0, column=2, sticky="ew", padx=6, pady=4)
        self.goal_deadline = LabeledEntry(fields, "Deadline (YYYY-MM-DD)")
        self.goal_deadline.grid(row=0, column=3, sticky="ew", padx=(6, 0), pady=4)

        AccentButton(add_card, text="Add Goal", command=self._add_goal).pack(padx=20, pady=(8, 18), fill="x")

        # Goals list
        goals = self.data.get("goals", [])
        if not goals:
            ctk.CTkLabel(
                scroll, text="No goals set yet — add one above to start tracking!",
                font=ctk.CTkFont(size=14), text_color=TEXT_DIM
            ).pack(pady=30)
        else:
            for i, g in enumerate(goals):
                self._draw_goal_card(scroll, g, i)

    def _draw_goal_card(self, parent, goal, idx):
        card = CardFrame(parent)
        card.pack(fill="x", padx=28, pady=6)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 4))

        target = max(goal["target"], 1)
        current = goal.get("current", 0)
        progress = min(current / target * 100, 100)

        ctk.CTkLabel(
            top, text=goal["name"],
            font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT_PRIMARY
        ).pack(side="left")

        # Status
        deadline_str = goal.get("deadline", "")
        status_color = SUCCESS
        status_text = "On Track"
        monthly_needed = 0
        if deadline_str:
            try:
                deadline = datetime.strptime(deadline_str, "%Y-%m-%d")
                months_left = max((deadline - datetime.now()).days / 30.44, 0.1)
                remaining = target - current
                if remaining > 0:
                    monthly_needed = remaining / months_left
                income = self.data.get("monthly_income", 0)
                if income > 0 and monthly_needed > income * 0.5:
                    status_color = DANGER
                    status_text = "At Risk"
                elif income > 0 and monthly_needed > income * 0.25:
                    status_color = WARNING
                    status_text = "Tight"
            except ValueError:
                pass

        ctk.CTkLabel(
            top, text=status_text,
            font=ctk.CTkFont(size=13, weight="bold"), text_color=status_color
        ).pack(side="right")

        # Progress bar
        bar_frame = ctk.CTkFrame(card, fg_color="transparent")
        bar_frame.pack(fill="x", padx=20, pady=(6, 4))

        bar_bg = ctk.CTkFrame(bar_frame, fg_color=BG_SECONDARY, height=18, corner_radius=9)
        bar_bg.pack(fill="x")
        bar_bg.pack_propagate(False)
        fill_w = max(progress / 100, 0.015)
        color = SUCCESS if progress >= 75 else (ACCENT if progress >= 40 else WARNING)
        bar_fill = ctk.CTkFrame(bar_bg, fg_color=color, corner_radius=9)
        bar_fill.place(relx=0, rely=0, relwidth=fill_w, relheight=1)

        # Info row
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(fill="x", padx=20, pady=(4, 4))
        ctk.CTkLabel(info, text=f"{fmt_currency(current)} / {fmt_currency(target)} ({progress:.0f}%)",
                     font=ctk.CTkFont(size=13), text_color=TEXT_PRIMARY).pack(side="left")
        if deadline_str:
            ctk.CTkLabel(info, text=f"Deadline: {deadline_str}", font=ctk.CTkFont(size=12), text_color=TEXT_DIM).pack(side="right")

        if monthly_needed > 0:
            ctk.CTkLabel(
                card, text=f"Need to save {fmt_currency(monthly_needed)}/month to stay on track",
                font=ctk.CTkFont(size=12), text_color=TEXT_DIM, anchor="w"
            ).pack(fill="x", padx=20, pady=(0, 2))

        # Update / Delete buttons
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(4, 14))

        self._goal_update_entries = getattr(self, "_goal_update_entries", {})
        upd_entry = ctk.CTkEntry(
            btn_row, width=120, height=32, corner_radius=8,
            fg_color=BG_SECONDARY, border_color=ACCENT, border_width=1,
            text_color=TEXT_PRIMARY, placeholder_text="New saved $", font=ctk.CTkFont(size=12)
        )
        upd_entry.pack(side="left", padx=(0, 6))
        self._goal_update_entries[idx] = upd_entry

        AccentButton(
            btn_row, text="Update", height=32, width=80,
            command=lambda i=idx: self._update_goal(i)
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row, text="Delete", height=32, width=80,
            fg_color=DANGER, hover_color="#cc5555", text_color=BG_PRIMARY,
            corner_radius=8, font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda i=idx: self._delete_goal(i)
        ).pack(side="left", padx=4)

    def _add_goal(self):
        name = self.goal_name.get_text()
        target = self.goal_target.get_float()
        if not name or target <= 0:
            return
        self.data["goals"].append({
            "name": name,
            "target": target,
            "current": self.goal_current.get_float(),
            "deadline": self.goal_deadline.get_text(),
            "created": str(datetime.now().date())
        })
        save_data(self.data)
        self.show_page("goals")

    def _update_goal(self, idx):
        entry = self._goal_update_entries.get(idx)
        if entry:
            try:
                val = float(entry.get().replace(",", "").replace("$", ""))
                self.data["goals"][idx]["current"] = val
                save_data(self.data)
                self.show_page("goals")
            except (ValueError, IndexError):
                pass

    def _delete_goal(self, idx):
        if 0 <= idx < len(self.data["goals"]):
            self.data["goals"].pop(idx)
            save_data(self.data)
            self.show_page("goals")

    # ══════════════════════════════════════════════════════════════════════
    #  PAGE 5 — DECISIONS
    # ══════════════════════════════════════════════════════════════════════
    def _build_decisions(self):
        scroll = ctk.CTkScrollableFrame(
            self.content, fg_color=BG_PRIMARY, corner_radius=0,
            scrollbar_button_color=BG_SECONDARY, scrollbar_button_hover_color=ACCENT
        )
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(
            scroll, text="Decision Tools",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT_PRIMARY
        ).pack(anchor="w", padx=28, pady=(22, 4))

        top_row = ctk.CTkFrame(scroll, fg_color="transparent")
        top_row.pack(fill="x", padx=28, pady=(10, 6))
        top_row.grid_columnconfigure(0, weight=1)
        top_row.grid_columnconfigure(1, weight=1)

        # "Should I Buy This?" Tool
        buy_card = CardFrame(top_row, title='🧠 "Should I Buy This?"')
        buy_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)

        bf = ctk.CTkFrame(buy_card, fg_color="transparent")
        bf.pack(fill="x", padx=20, pady=(6, 4))
        self.buy_item = LabeledEntry(bf, "Item Name")
        self.buy_item.pack(fill="x", pady=3)
        self.buy_price = LabeledEntry(bf, "Price ($)")
        self.buy_price.pack(fill="x", pady=3)
        self.buy_income = LabeledEntry(bf, "Monthly Income ($)", self.data.get("monthly_income", 0))
        self.buy_income.pack(fill="x", pady=3)
        self.buy_savings = LabeledEntry(bf, "Current Savings ($)", self.data["net_worth"]["cash"])
        self.buy_savings.pack(fill="x", pady=3)

        ctk.CTkLabel(bf, text="Importance (1 = low, 10 = critical)", font=ctk.CTkFont(size=12), text_color=TEXT_DIM).pack(anchor="w", pady=(4, 0))
        self.buy_importance = ctk.CTkSlider(
            bf, from_=1, to=10, number_of_steps=9,
            fg_color=BG_SECONDARY, progress_color=ACCENT, button_color=TEXT_PRIMARY,
            button_hover_color=ACCENT
        )
        self.buy_importance.set(5)
        self.buy_importance.pack(fill="x", pady=(2, 0))
        self.buy_imp_label = ctk.CTkLabel(bf, text="5", font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT)
        self.buy_imp_label.pack()
        self.buy_importance.configure(command=lambda v: self.buy_imp_label.configure(text=f"{int(v)}"))

        AccentButton(buy_card, text="Analyze Purchase", command=self._analyze_purchase).pack(padx=20, pady=(8, 18), fill="x")

        # Result card
        self.decision_result_card = CardFrame(top_row, title="Recommendation")
        self.decision_result_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)
        ctk.CTkLabel(
            self.decision_result_card, text="Enter a purchase to analyze",
            font=ctk.CTkFont(size=14), text_color=TEXT_DIM
        ).pack(pady=60)

        # Quick decision helpers
        quick_card = CardFrame(scroll, title="Quick Decision Metrics")
        quick_card.pack(fill="x", padx=28, pady=(10, 20))
        self.quick_frame = ctk.CTkFrame(quick_card, fg_color="transparent")
        self.quick_frame.pack(fill="x", padx=20, pady=(6, 18))

        income = self.data.get("monthly_income", 0)
        nw = self.data["net_worth"]
        total_nw = nw["cash"] + nw["investments"] + nw["assets"] - nw["debts"]
        emergency = nw["cash"] / max(income, 1) if income > 0 else 0

        metrics = [
            ("Emergency Fund", f"{emergency:.1f} months", "Aim for 3-6 months" if emergency < 6 else "Well covered!",
             WARNING if emergency < 3 else (ACCENT if emergency < 6 else SUCCESS)),
            ("Debt-to-Asset Ratio", f"{nw['debts']/max(nw['assets']+nw['investments'], 1)*100:.0f}%",
             "Lower is better", SUCCESS if nw["debts"] < (nw["assets"] + nw["investments"]) * 0.3 else WARNING),
            ("Investment Ratio", f"{nw['investments']/max(total_nw, 1)*100:.0f}%",
             "Of net worth", ACCENT),
        ]

        for i, (label, value, sub, color) in enumerate(metrics):
            mc = MetricCard(self.quick_frame, label, value, sub, color)
            mc.pack(side="left", fill="both", expand=True, padx=6, pady=4)

    def _analyze_purchase(self):
        price = self.buy_price.get_float()
        income = self.buy_income.get_float()
        savings = self.buy_savings.get_float()
        importance = int(self.buy_importance.get())
        item = self.buy_item.get_text() or "This item"

        if price <= 0 or income <= 0:
            return

        # Clear old results
        for w in self.decision_result_card.winfo_children():
            if not isinstance(w, ctk.CTkLabel) or w.cget("text") != "Recommendation":
                w.destroy()

        rf = ctk.CTkFrame(self.decision_result_card, fg_color="transparent")
        rf.pack(fill="x", padx=20, pady=(6, 18))

        income_pct = price / income * 100
        savings_pct = price / max(savings, 1) * 100
        fv_10 = price * (1.10) ** 10

        # Decision logic
        score = 0
        reasons = []

        # Income percentage factor
        if income_pct <= 5:
            score += 3
            reasons.append(f"Only {income_pct:.1f}% of your monthly income — very affordable.")
        elif income_pct <= 15:
            score += 1
            reasons.append(f"This is {income_pct:.1f}% of your monthly income — manageable.")
        elif income_pct <= 30:
            score -= 1
            reasons.append(f"This is {income_pct:.1f}% of your monthly income — significant.")
        else:
            score -= 3
            reasons.append(f"This is {income_pct:.1f}% of your monthly income — very expensive.")

        # Savings impact
        if savings_pct <= 10:
            score += 2
            reasons.append(f"Only {savings_pct:.1f}% of your savings — minimal impact.")
        elif savings_pct <= 30:
            score += 0
            reasons.append(f"Takes {savings_pct:.1f}% of your savings — noticeable but okay.")
        else:
            score -= 2
            reasons.append(f"Takes {savings_pct:.1f}% of your savings — risky for your safety net.")

        # Importance factor
        if importance >= 8:
            score += 2
            reasons.append(f"Importance: {importance}/10 — high priority for you.")
        elif importance >= 5:
            score += 0
            reasons.append(f"Importance: {importance}/10 — moderate priority.")
        else:
            score -= 2
            reasons.append(f"Importance: {importance}/10 — consider if this is truly needed.")

        # Goal impact
        goals = self.data.get("goals", [])
        for g in goals:
            remaining = g["target"] - g.get("current", 0)
            if remaining > 0 and income > 0:
                months_delay = price / max(income * 0.2, 1)
                if months_delay >= 1:
                    reasons.append(f'Delays your "{g["name"]}" goal by ~{months_delay:.0f} month(s).')
                    break

        # Opportunity cost
        reasons.append(f"Opportunity cost: {fmt_currency(price)} invested could become {fmt_currency(fv_10)} in 10 years.")

        # Verdict
        if score >= 3:
            verdict = "BUY"
            verdict_color = SUCCESS
            emoji = "✅"
            desc = "This purchase aligns well with your financial situation."
        elif score >= 0:
            verdict = "WAIT"
            verdict_color = WARNING
            emoji = "⏳"
            desc = "Consider waiting or finding a better deal."
        else:
            verdict = "DON'T BUY"
            verdict_color = DANGER
            emoji = "🚫"
            desc = "This purchase could strain your finances."

        # Display
        ctk.CTkLabel(
            rf, text=f"{emoji}  {verdict}",
            font=ctk.CTkFont(size=28, weight="bold"), text_color=verdict_color
        ).pack(pady=(10, 2))
        ctk.CTkLabel(
            rf, text=desc, font=ctk.CTkFont(size=13), text_color=TEXT_DIM
        ).pack(pady=(0, 10))

        sep = ctk.CTkFrame(rf, fg_color=ACCENT, height=1)
        sep.pack(fill="x", pady=6)

        ctk.CTkLabel(
            rf, text="Analysis", font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT
        ).pack(anchor="w", pady=(6, 4))

        for reason in reasons:
            row = ctk.CTkFrame(rf, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text="→", text_color=ACCENT, font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                row, text=reason, font=ctk.CTkFont(size=12), text_color=TEXT_PRIMARY,
                wraplength=320, anchor="w", justify="left"
            ).pack(side="left", fill="x", expand=True)


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = CapitalDashboardApp()
    app.mainloop()