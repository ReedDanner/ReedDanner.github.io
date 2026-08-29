"""
Reusable widgets: collapsible sections, numeric fields, stat tables, status LED.

The numeric input is a validated ``QLineEdit`` rather than a ``QDoubleSpinBox``
on purpose.  Model parameters span fourteen orders of magnitude -- a GARCH
``omega`` is 2e-6 while a horizon is 252 -- and a spin box forces a fixed
decimal count that is either useless for the small values or absurd for the
large ones.  A line edit accepts ``2e-6``, ``0.000002`` and ``252`` equally.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDoubleValidator, QFont, QPainter, QBrush, QPen
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QSizePolicy, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .theme import MONO_FONT, PALETTE, sign_color

__all__ = [
    "fmt_num", "fmt_pct", "fmt_money", "CollapsibleSection", "NumField",
    "ParamGrid", "StatTable", "StatusLED", "MetricStrip", "TabInfoBar", "with_info_bar",
]


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------
def fmt_num(value, decimals: int = 4) -> str:
    """Format a number compactly, switching to scientific notation when needed."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(v):
        return "--"
    a = abs(v)
    if a != 0 and (a < 1e-4 or a >= 1e7):
        return f"{v:.{max(2, decimals - 1)}e}"
    if a >= 1000:
        return f"{v:,.2f}"
    return f"{v:.{decimals}f}"


def fmt_pct(value, decimals: int = 2) -> str:
    """Format a fraction as a percentage."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return "--" if not np.isfinite(v) else f"{v*100:.{decimals}f}%"


def fmt_money(value, decimals: int = 2) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return "--" if not np.isfinite(v) else f"{v:,.{decimals}f}"


# --------------------------------------------------------------------------
# collapsible section
# --------------------------------------------------------------------------
class CollapsibleSection(QWidget):
    """A titled section whose body can be folded away.

    The left panel carries seven parameter groups; showing all of them at once
    needs about 1200 vertical pixels, which most screens do not have.  Folding
    lets the user keep open only the groups relevant to what they are doing.
    """

    toggled_open = pyqtSignal(bool)

    def __init__(self, title: str, parent=None, expanded: bool = True) -> None:
        super().__init__(parent)
        self._expanded = bool(expanded)

        self._button = QPushButton(self._label(title))
        self._title = title
        self._button.setCheckable(True)
        self._button.setChecked(self._expanded)
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                background: {PALETTE['panel_alt']};
                border: 1px solid {PALETTE['border']};
                border-radius: 2px;
                padding: 4px 7px;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
                color: {PALETTE['fg_dim']};
            }}
            QPushButton:hover {{ color: {PALETTE['accent']};
                                 border-color: {PALETTE['border_lt']}; }}
            QPushButton:checked {{ color: {PALETTE['accent']}; }}
        """)
        self._button.clicked.connect(self._on_click)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(6, 4, 4, 6)
        self.body_layout.setSpacing(4)
        self.body.setVisible(self._expanded)
        self.body.setStyleSheet(
            f"background: {PALETTE['panel']}; border: 1px solid "
            f"{PALETTE['border']}; border-top: none;"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 3)
        outer.setSpacing(0)
        outer.addWidget(self._button)
        outer.addWidget(self.body)

    def _label(self, title: str) -> str:
        return ("▾  " if self._expanded else "▸  ") + title.upper()

    def _on_click(self) -> None:
        self._expanded = self._button.isChecked()
        self.body.setVisible(self._expanded)
        self._button.setText(self._label(self._title))
        self.toggled_open.emit(self._expanded)

    def add(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.body_layout.addLayout(layout)

    def set_expanded(self, on: bool) -> None:
        self._button.setChecked(bool(on))
        self._on_click()


# --------------------------------------------------------------------------
# numeric field
# --------------------------------------------------------------------------
class NumField(QWidget):
    """Label + validated numeric line edit, laid out on one tight row."""

    value_changed = pyqtSignal()

    def __init__(self, label: str, value: float = 0.0, tooltip: str = "",
                 decimals: int = 6, parent=None, label_width: int = 96) -> None:
        super().__init__(parent)
        self._label_text = label
        self.label = QLabel(label)
        self.label.setProperty("role", "caption")
        self.label.setFixedWidth(label_width)
        if tooltip:
            self.label.setToolTip(tooltip)

        self.edit = QLineEdit()
        self.edit.setValidator(QDoubleValidator(-1e15, 1e15, decimals))
        self.edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        if tooltip:
            self.edit.setToolTip(tooltip)
        self.set_value(value)
        self.edit.editingFinished.connect(self.value_changed.emit)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        row.addWidget(self.label)
        row.addWidget(self.edit, 1)

    def value(self, default: float = 0.0) -> float:
        """Current value, or ``default`` if the box does not parse."""
        try:
            return float(self.edit.text().strip().replace(",", ""))
        except (TypeError, ValueError):
            return float(default)

    def set_value(self, value: float) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            self.edit.setText("")
            return
        if not np.isfinite(v):
            self.edit.setText("")
        elif v != 0 and (abs(v) < 1e-4 or abs(v) >= 1e7):
            self.edit.setText(f"{v:.6g}")
        else:
            self.edit.setText(f"{v:g}")

    def set_enabled(self, on: bool) -> None:
        self.edit.setEnabled(bool(on))
        self.label.setEnabled(bool(on))


# --------------------------------------------------------------------------
# dynamic parameter grid
# --------------------------------------------------------------------------
class ParamGrid(QWidget):
    """Fields for the selected model's parameters, rebuilt when it changes."""

    changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fields: Dict[str, NumField] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(3)
        self._note = QLabel("")
        self._note.setProperty("role", "caption")
        self._note.setWordWrap(True)
        self._note.setStyleSheet(f"color: {PALETTE['fg_faint']}; font-size: 10px;")

    def build(self, specs: Sequence[Tuple[str, float, str]],
              values: Optional[Dict[str, float]] = None, note: str = "") -> None:
        """Replace the current fields with those for a new model."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._note:
                w.setParent(None)
        self._fields.clear()
        vals = values or {}
        for name, default, tip in specs:
            field = NumField(name, vals.get(name, default), tip)
            field.value_changed.connect(self.changed.emit)
            self._fields[name] = field
            self._layout.addWidget(field)
        self._note.setText(note)
        self._note.setVisible(bool(note))
        self._layout.addWidget(self._note)

    def values(self) -> Dict[str, float]:
        return {name: f.value() for name, f in self._fields.items()}

    def set_values(self, values: Dict[str, float]) -> None:
        for name, field in self._fields.items():
            if name in values:
                field.set_value(values[name])

    def field_names(self) -> List[str]:
        return list(self._fields)


# --------------------------------------------------------------------------
# statistics table
# --------------------------------------------------------------------------
class StatTable(QTableWidget):
    """Two-column key/value readout with optional per-row colouring."""

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["Metric", title or "Value"])
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setDefaultSectionSize(18)
        self._rows: List[Tuple[str, str]] = []

    def set_rows(self, rows: Sequence[Tuple[str, str]],
                 colors: Optional[Dict[int, str]] = None) -> None:
        """Replace every row.  ``colors`` maps a row index to a value colour."""
        colors = colors or {}
        self.setUpdatesEnabled(False)
        try:
            self.setRowCount(len(rows))
            for i, (key, value) in enumerate(rows):
                k = QTableWidgetItem(str(key))
                k.setForeground(QColor(PALETTE["fg_dim"]))
                v = QTableWidgetItem(str(value))
                v.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter)
                v.setForeground(QColor(colors.get(i, PALETTE["fg"])))
                font = QFont("Consolas")
                font.setPointSize(9)
                v.setFont(font)
                self.setItem(i, 0, k)
                self.setItem(i, 1, v)
            self._rows = [(str(a), str(b)) for a, b in rows]
        finally:
            self.setUpdatesEnabled(True)

    def to_csv_rows(self) -> List[Tuple[str, str]]:
        """The table's contents, for the CSV export."""
        return list(self._rows)

    def set_headers(self, key_header: str, value_header: str) -> None:
        self.setHorizontalHeaderLabels([key_header, value_header])


# --------------------------------------------------------------------------
# status LED
# --------------------------------------------------------------------------
class StatusLED(QWidget):
    """Coloured dot plus a short label, used for data-source health."""

    _COLORS = {
        "live": PALETTE["up"],
        "cached": PALETTE["warn"],
        "stale": PALETTE["warn"],
        "synthetic": PALETTE["info"],
        "error": PALETTE["down"],
        "idle": PALETTE["fg_faint"],
        "busy": PALETTE["accent"],
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._text = "idle"
        self.setFixedHeight(20)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)

    def set_state(self, state: str, text: str = "", tooltip: str = "") -> None:
        self._state = str(state).lower()
        self._text = text or state
        self.setToolTip(tooltip or text)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(self._COLORS.get(self._state, PALETTE["fg_faint"]))

        glow = QColor(colour)
        glow.setAlpha(55)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(1, 5, 14, 14)
        painter.setBrush(QBrush(colour))
        painter.drawEllipse(4, 8, 8, 8)

        painter.setPen(QPen(QColor(PALETTE["fg_dim"])))
        font = QFont("Consolas")
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(20, 15, self._text)
        painter.end()


# --------------------------------------------------------------------------
# per-tab explainer
# --------------------------------------------------------------------------
class TabInfoBar(QWidget):
    """A one-line "About this tab" strip that expands into a short explainer.

    Deliberately unobtrusive: it sits at the bottom of a tab as a single dim
    row, starts collapsed, and takes ~18px until clicked.  The point is that
    the explanation is *available* without competing with the chart for
    attention -- a permanent paragraph would be noise for anyone who already
    knows what a fan chart is.
    """

    def __init__(self, title: str, body: str, parent=None) -> None:
        super().__init__(parent)
        self._body_text = body
        self._open = False

        # QPushButton reads a single "&" as a mnemonic accelerator and hides it,
        # so "Price & Technicals" would render as "Price  Technicals".
        self.header = QPushButton(
            f"ⓘ  About this tab  —  {title.replace('&', '&&')}")
        self.header.setCheckable(True)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                background: transparent;
                border: none;
                border-top: 1px solid {PALETTE['border']};
                padding: 3px 6px;
                font-size: 10px;
                color: {PALETTE['fg_faint']};
            }}
            QPushButton:hover {{ color: {PALETTE['accent']}; }}
            QPushButton:checked {{ color: {PALETTE['accent']}; }}
        """)
        self.header.clicked.connect(self._toggle)

        self.body = QLabel(body)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setStyleSheet(f"""
            QLabel {{
                background: {PALETTE['panel_alt']};
                border: 1px solid {PALETTE['border']};
                border-top: none;
                color: {PALETTE['fg_dim']};
                font-size: 11px;
                padding: 7px 10px;
            }}
        """)
        self.body.setVisible(False)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.header)
        col.addWidget(self.body)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Maximum)

    def _toggle(self) -> None:
        self._open = self.header.isChecked()
        self.body.setVisible(self._open)

    def set_open(self, on: bool) -> None:
        self.header.setChecked(bool(on))
        self._toggle()


def with_info_bar(content: QWidget, title: str, body: str) -> QWidget:
    """Wrap ``content`` in a column with a :class:`TabInfoBar` beneath it."""
    box = QWidget()
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(0)
    col.addWidget(content, 1)
    col.addWidget(TabInfoBar(title, body))
    return box


# --------------------------------------------------------------------------
# metric strip
# --------------------------------------------------------------------------
class MetricStrip(QWidget):
    """A row of caption/value pairs for the headline numbers in the top bar."""

    def __init__(self, keys: Sequence[str], parent=None) -> None:
        super().__init__(parent)
        self._values: Dict[str, QLabel] = {}
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        for key in keys:
            cell = QWidget()
            col = QVBoxLayout(cell)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)
            cap = QLabel(key.upper())
            cap.setProperty("role", "section")
            val = QLabel("--")
            val.setProperty("role", "value")
            val.setStyleSheet(f"font-family: {MONO_FONT}; font-size: 13px;")
            col.addWidget(cap)
            col.addWidget(val)
            row.addWidget(cell)
            self._values[key] = val
        row.addStretch(1)

    def set(self, key: str, text: str, color: Optional[str] = None) -> None:
        label = self._values.get(key)
        if label is None:
            return
        label.setText(text)
        label.setStyleSheet(
            f"font-family: {MONO_FONT}; font-size: 13px; "
            f"color: {color or PALETTE['fg']};"
        )

    def set_signed(self, key: str, value: float, text: str) -> None:
        self.set(key, text, sign_color(value))

    def clear(self) -> None:
        for label in self._values.values():
            label.setText("--")
            label.setStyleSheet(
                f"font-family: {MONO_FONT}; font-size: 13px; "
                f"color: {PALETTE['fg']};")
