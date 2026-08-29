"""
Persistent application settings and standard file locations.

Settings are a flat JSON document in the user's app data directory, written
atomically (temp file + replace) so a crash mid-save cannot leave a truncated
file that would fail to parse on the next launch.  Any unreadable or partially
corrupt config falls back to defaults rather than blocking start-up.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

__all__ = ["app_dir", "config_path", "cache_path", "export_dir", "AppConfig"]

APP_NAME = "QuantMonteCarlo"


def app_dir() -> str:
    """Per-user application directory, created on first use.

    ``%LOCALAPPDATA%\\QuantMonteCarlo`` on Windows,
    ``~/Library/Application Support/QuantMonteCarlo`` on macOS,
    ``$XDG_CONFIG_HOME/quantmontecarlo`` (or ``~/.config/...``) elsewhere.
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_NAME)
    elif sys.platform == "darwin":
        path = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        path = os.path.join(base, APP_NAME.lower())
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    """Full path of the settings JSON file."""
    return os.path.join(app_dir(), "settings.json")


def cache_path() -> str:
    """Full path of the SQLite market-data cache."""
    return os.path.join(app_dir(), "market_cache.sqlite")


def export_dir() -> str:
    """Default directory for chart and table exports, created on first use."""
    path = os.path.join(app_dir(), "exports")
    os.makedirs(path, exist_ok=True)
    return path


@dataclass
class AppConfig:
    """Last-used settings, restored on launch.

    Only values a user would be annoyed to re-enter are persisted.  Anything
    derived (calibrated parameters, results, window contents) is recomputed,
    so a stale config can never put the app into an inconsistent state.
    """

    # --- data ---
    ticker: str = "AAPL"
    period: str = "2y"
    interval: str = "1d"
    offline: bool = False
    cache_max_age_minutes: float = 60.0
    allow_synthetic: bool = False
    """Permit generated fixture data when no real data can be had.

    Off by default: silently substituting plausible-looking generated numbers
    for a real ticker is worse than an honest error, because nothing
    downstream can tell they are fake.
    """

    # --- simulation ---
    model: str = "gbm"
    horizon_days: int = 252
    n_paths: int = 100_000
    seed: int = 42
    use_seed: bool = True
    antithetic: bool = False
    batch_size: int = 10_000
    update_every: int = 1
    max_fan_paths: int = 4_000
    fan_sample_paths: int = 150
    """How many individual paths to draw behind the percentile ribbons."""

    # --- per-model parameters, keyed by model name ---
    model_params: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # --- probability targets ---
    target_price: float = 0.0
    """0 means "use spot" -- resolved at run time so it follows the ticker."""
    barrier: float = 0.0
    barrier_direction: str = "up"
    ruin_pct: float = 50.0
    """Ruin level as a percentage of spot."""
    risk_free: float = 0.04

    # --- options ---
    opt_strike: float = 0.0
    opt_days: int = 30
    opt_kind: str = "call"
    opt_vol: float = 0.25
    opt_dividend: float = 0.0
    opt_style: str = "asian_arithmetic"
    opt_barrier: float = 0.0
    opt_tree_steps: int = 500
    opt_mc_paths: int = 100_000

    # --- analysis ---
    calibration_lookback: int = 504
    vol_window: int = 21
    ewma_lambda: float = 0.94
    hmm_states: int = 2
    basket: List[str] = field(default_factory=lambda: ["SPY", "QQQ", "TLT", "GLD"])
    basket_weights: List[float] = field(default_factory=list)

    # --- window ---
    window_geometry: List[int] = field(default_factory=lambda: [80, 60, 1680, 980])
    last_export_dir: str = ""

    # ------------------------------------------------------------------
    def params_for(self, model: str) -> Dict[str, float]:
        """Stored parameters for ``model``, falling back to the model defaults."""
        from .models.paths import default_params

        stored = self.model_params.get(model)
        out = default_params(model)
        if stored:
            out.update({k: v for k, v in stored.items() if k in out or k == "returns"})
        return out

    def set_params_for(self, model: str, params: Dict[str, float]) -> None:
        """Remember parameters for ``model`` (the return sample is never stored)."""
        self.model_params[model] = {
            k: float(v) for k, v in params.items()
            if k != "returns" and isinstance(v, (int, float))
        }

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """Build a config from a dict, ignoring unknown or wrongly typed keys.

        Being permissive here is deliberate: a settings file written by an older
        or newer build should degrade to defaults for the keys it cannot supply
        rather than refuse to load.
        """
        known = {f.name: f for f in fields(cls)}
        kwargs: Dict[str, Any] = {}
        for key, value in (data or {}).items():
            spec = known.get(key)
            if spec is None:
                continue
            try:
                if spec.type in ("int", int):
                    kwargs[key] = int(value)
                elif spec.type in ("float", float):
                    kwargs[key] = float(value)
                elif spec.type in ("bool", bool):
                    kwargs[key] = bool(value)
                elif spec.type in ("str", str):
                    kwargs[key] = str(value)
                else:
                    kwargs[key] = value
            except (TypeError, ValueError):
                continue
        return cls(**kwargs)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "AppConfig":
        """Load settings, returning defaults if the file is missing or corrupt."""
        p = path or config_path()
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return cls.from_dict(json.load(fh))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return cls()

    def save(self, path: Optional[str] = None) -> bool:
        """Write settings atomically.  Returns False on failure instead of raising.

        A settings save must never take the app down on exit, so every failure
        mode (read-only directory, disk full, permission denied) is swallowed
        and reported as a boolean.
        """
        p = path or config_path()
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
            os.replace(tmp, p)
            return True
        except Exception:
            try:
                if "tmp" in dir() and os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            return False
