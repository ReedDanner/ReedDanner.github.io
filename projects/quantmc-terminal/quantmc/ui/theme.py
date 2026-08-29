"""
Dark terminal theme: colour palette, Qt stylesheet and matplotlib defaults.

One palette drives both the widgets and the charts so the whole window reads as
a single surface.  The design targets a trading desk rather than a dashboard:
low-luminance background, high-contrast numerics, monospace everywhere a number
appears (so digits align in columns), and 2-4px padding instead of the 8-12px a
consumer app would use.
"""

from __future__ import annotations

from typing import Dict

__all__ = ["PALETTE", "MONO_FONT", "UI_FONT", "STYLESHEET", "apply_mpl_theme",
           "band_colors", "sign_color"]

#: Single source of truth for every colour in the app.
PALETTE: Dict[str, str] = {
    "bg":        "#0a0d12",   # window background
    "panel":     "#121722",   # docks, group boxes
    "panel_alt": "#171d2b",   # alternating rows, headers
    "raised":    "#1d2536",   # buttons, inputs
    "border":    "#28324a",
    "border_lt": "#3a4763",
    "fg":        "#d7dee9",   # primary text
    "fg_dim":    "#8592a8",   # labels, secondary text
    "fg_faint":  "#5d6982",   # axis ticks, disabled
    "accent":    "#f0b429",   # amber: primary action, focus
    "accent_dk": "#c8951f",
    "up":        "#22c55e",
    "down":      "#ef4444",
    "info":      "#38bdf8",
    "violet":    "#a78bfa",
    "teal":      "#2dd4bf",
    "pink":      "#f472b6",
    "warn":      "#fbbf24",
    "grid":      "#1e2637",
}

MONO_FONT = "Consolas, 'Cascadia Mono', 'DejaVu Sans Mono', monospace"
UI_FONT = "'Segoe UI', 'Inter', system-ui, sans-serif"

#: Fan-chart ribbon colours, from the outer band inward.
_BAND_COLORS = ("#1b3a5c", "#245785", "#2f77b0")


def band_colors(n: int):
    """Colours for ``n`` nested percentile ribbons, outermost first."""
    if n <= len(_BAND_COLORS):
        return list(_BAND_COLORS[:n])
    return list(_BAND_COLORS) + [_BAND_COLORS[-1]] * (n - len(_BAND_COLORS))


def sign_color(value: float) -> str:
    """Green for positive, red for negative, dim for zero or non-finite."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return PALETTE["fg_dim"]
    if v != v:  # nan
        return PALETTE["fg_dim"]
    if v > 0:
        return PALETTE["up"]
    if v < 0:
        return PALETTE["down"]
    return PALETTE["fg_dim"]


STYLESHEET = f"""
QWidget {{
    background: {PALETTE['bg']};
    color: {PALETTE['fg']};
    font-family: {UI_FONT};
    font-size: 12px;
}}
QMainWindow, QDialog {{ background: {PALETTE['bg']}; }}

QLabel {{ background: transparent; }}
QLabel[role="caption"] {{ color: {PALETTE['fg_dim']}; font-size: 11px; }}
QLabel[role="value"] {{
    font-family: {MONO_FONT};
    font-size: 13px;
    color: {PALETTE['fg']};
}}
QLabel[role="ticker"] {{
    font-family: {MONO_FONT};
    font-size: 20px;
    font-weight: 600;
    color: {PALETTE['accent']};
}}
QLabel[role="price"] {{
    font-family: {MONO_FONT};
    font-size: 20px;
    font-weight: 600;
}}
QLabel[role="section"] {{
    color: {PALETTE['fg_dim']};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}}

QGroupBox {{
    background: {PALETTE['panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 3px;
    margin-top: 14px;
    padding: 6px 4px 4px 4px;
    font-size: 10px;
    font-weight: 700;
    color: {PALETTE['fg_dim']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 7px;
    top: 1px;
    padding: 0 4px;
    letter-spacing: 1px;
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {PALETTE['raised']};
    border: 1px solid {PALETTE['border']};
    border-radius: 2px;
    padding: 2px 5px;
    font-family: {MONO_FONT};
    font-size: 12px;
    selection-background-color: {PALETTE['accent']};
    selection-color: #101010;
    min-height: 19px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {PALETTE['accent']};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled {{ color: {PALETTE['fg_faint']}; }}
QLineEdit[role="ticker"] {{
    font-size: 17px;
    font-weight: 700;
    color: {PALETTE['accent']};
    padding: 2px 8px;
    min-height: 25px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {PALETTE['panel_alt']};
    border: none;
    width: 13px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: none; border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid {PALETTE['fg_dim']};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none; border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {PALETTE['fg_dim']};
}}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox::down-arrow {{
    image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {PALETTE['fg_dim']};
    margin-right: 5px;
}}
QComboBox QAbstractItemView {{
    background: {PALETTE['raised']};
    border: 1px solid {PALETTE['border_lt']};
    selection-background-color: {PALETTE['accent']};
    selection-color: #101010;
    outline: none;
}}

QPushButton {{
    background: {PALETTE['raised']};
    border: 1px solid {PALETTE['border_lt']};
    border-radius: 2px;
    padding: 3px 11px;
    font-weight: 600;
    font-size: 11px;
    min-height: 20px;
}}
QPushButton:hover {{ background: {PALETTE['panel_alt']};
                     border-color: {PALETTE['accent']}; }}
QPushButton:pressed {{ background: {PALETTE['border']}; }}
QPushButton:disabled {{ color: {PALETTE['fg_faint']};
                        border-color: {PALETTE['border']}; }}
QPushButton[role="primary"] {{
    background: {PALETTE['accent']};
    color: #10141c;
    border: 1px solid {PALETTE['accent']};
}}
QPushButton[role="primary"]:hover {{ background: #ffc94d; }}
QPushButton[role="primary"]:disabled {{
    background: {PALETTE['raised']}; color: {PALETTE['fg_faint']};
    border-color: {PALETTE['border']};
}}
QPushButton[role="danger"] {{ color: {PALETTE['down']};
                              border-color: {PALETTE['down']}; }}
QPushButton[role="danger"]:hover {{ background: #2a1418; }}

QCheckBox {{ spacing: 5px; font-size: 11px; }}
QCheckBox::indicator {{
    width: 12px; height: 12px; border-radius: 2px;
    border: 1px solid {PALETTE['border_lt']};
    background: {PALETTE['raised']};
}}
QCheckBox::indicator:checked {{
    background: {PALETTE['accent']}; border-color: {PALETTE['accent']};
}}

QTabWidget::pane {{
    border: 1px solid {PALETTE['border']};
    background: {PALETTE['panel']};
    top: -1px;
}}
QTabBar::tab {{
    background: {PALETTE['bg']};
    color: {PALETTE['fg_dim']};
    padding: 5px 14px;
    border: 1px solid {PALETTE['border']};
    border-bottom: none;
    margin-right: 1px;
    font-size: 11px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background: {PALETTE['panel']};
    color: {PALETTE['accent']};
    border-top: 2px solid {PALETTE['accent']};
}}
QTabBar::tab:hover:!selected {{ color: {PALETTE['fg']}; }}

QTableWidget, QTableView {{
    background: {PALETTE['panel']};
    alternate-background-color: {PALETTE['panel_alt']};
    gridline-color: {PALETTE['border']};
    border: 1px solid {PALETTE['border']};
    font-family: {MONO_FONT};
    font-size: 11px;
    selection-background-color: {PALETTE['border_lt']};
    selection-color: {PALETTE['fg']};
}}
QHeaderView::section {{
    background: {PALETTE['panel_alt']};
    color: {PALETTE['fg_dim']};
    border: none;
    border-right: 1px solid {PALETTE['border']};
    border-bottom: 1px solid {PALETTE['border']};
    padding: 3px 5px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QTableCornerButton::section {{ background: {PALETTE['panel_alt']};
                               border: none; }}

QScrollBar:vertical {{ background: {PALETTE['bg']}; width: 9px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {PALETTE['border_lt']}; border-radius: 4px; min-height: 22px;
}}
QScrollBar::handle:vertical:hover {{ background: {PALETTE['fg_faint']}; }}
QScrollBar:horizontal {{ background: {PALETTE['bg']}; height: 9px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {PALETTE['border_lt']}; border-radius: 4px; min-width: 22px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{
    background: {PALETTE['raised']};
    border: 1px solid {PALETTE['border']};
    border-radius: 2px;
    text-align: center;
    font-family: {MONO_FONT};
    font-size: 10px;
    color: {PALETTE['fg']};
    max-height: 15px;
}}
QProgressBar::chunk {{ background: {PALETTE['accent']}; border-radius: 1px; }}

QSplitter::handle {{ background: {PALETTE['border']}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}

QToolTip {{
    background: {PALETTE['panel_alt']};
    color: {PALETTE['fg']};
    border: 1px solid {PALETTE['border_lt']};
    padding: 3px;
    font-size: 11px;
}}

QScrollArea {{ border: none; background: {PALETTE['bg']}; }}
QStatusBar {{
    background: {PALETTE['panel']};
    color: {PALETTE['fg_dim']};
    border-top: 1px solid {PALETTE['border']};
    font-family: {MONO_FONT};
    font-size: 11px;
}}
QMenu {{
    background: {PALETTE['panel_alt']};
    border: 1px solid {PALETTE['border_lt']};
}}
QMenu::item:selected {{ background: {PALETTE['accent']}; color: #10141c; }}
"""


def apply_mpl_theme() -> None:
    """Push the palette into matplotlib's global rcParams.

    Called once at start-up.  Every chart in the app then inherits the dark
    background, thin grid and monospace tick labels without repeating style
    code per figure.
    """
    import matplotlib as mpl

    mpl.rcParams.update({
        "figure.facecolor": PALETTE["panel"],
        "figure.edgecolor": PALETTE["panel"],
        "savefig.facecolor": PALETTE["panel"],
        "savefig.edgecolor": PALETTE["panel"],
        "axes.facecolor": PALETTE["panel"],
        "axes.edgecolor": PALETTE["border_lt"],
        "axes.labelcolor": PALETTE["fg_dim"],
        "axes.titlecolor": PALETTE["fg"],
        "axes.titlesize": 10,
        "axes.titleweight": "600",
        "axes.labelsize": 9,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": PALETTE["grid"],
        "grid.linewidth": 0.6,
        "grid.alpha": 0.9,
        "text.color": PALETTE["fg"],
        "xtick.color": PALETTE["fg_faint"],
        "ytick.color": PALETTE["fg_faint"],
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "font.family": "monospace",
        "font.monospace": ["Consolas", "DejaVu Sans Mono", "Courier New"],
        "legend.facecolor": PALETTE["panel_alt"],
        "legend.edgecolor": PALETTE["border"],
        "legend.fontsize": 8,
        "legend.framealpha": 0.92,
        "lines.linewidth": 1.2,
        "figure.autolayout": False,
        "path.simplify": True,
        "path.simplify_threshold": 1.0,
        "agg.path.chunksize": 20000,
    })
