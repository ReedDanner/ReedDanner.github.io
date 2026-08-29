import os
import sys
import json
import time
import math
import queue
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

import customtkinter as ctk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ML is optional depending on history; app still works without it (but best to install)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor, RandomForestClassifier
from sklearn.metrics import mean_squared_error, mean_absolute_percentage_error, roc_auc_score


# ============================================================
# CONFIG / THEME (same feel as previous program)
# ============================================================
BG = "#0b0f14"
PANEL = "#111827"
GRID = "#1f2937"
TEXT = "#d1d5db"
DIM = "#9ca3af"
ACCENT = "#22c55e"
WARN = "#f59e0b"
BAD = "#ef4444"

MARKETSTACK_EOD_URL = "http://api.marketstack.com/v1/eod"


# ============================================================
# Helpers
# ============================================================
def run_in_thread(fn, on_error=None):
    def runner():
        try:
            fn()
        except Exception as e:
            if on_error:
                on_error(e)
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t


def log_returns(px: pd.Series) -> pd.Series:
    return np.log(px).diff()


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0)
    down = (-d).clip(lower=0)
    ru = up.ewm(alpha=1/period, adjust=False).mean()
    rd = down.ewm(alpha=1/period, adjust=False).mean()
    rs = ru / (rd.replace(0, np.nan))
    return 100 - (100 / (1 + rs))


def macd(s: pd.Series, fast=12, slow=26, signal=9):
    m = ema(s, fast) - ema(s, slow)
    sig = ema(m, signal)
    hist = m - sig
    return m, sig, hist


def ann_vol(px: pd.Series) -> float:
    r = log_returns(px).dropna()
    if len(r) < 10:
        return float("nan")
    return float(r.std() * np.sqrt(252))


def ann_drift(px: pd.Series) -> float:
    r = log_returns(px).dropna()
    if len(r) < 10:
        return float("nan")
    return float(r.mean() * 252)


def max_drawdown(px: pd.Series) -> float:
    roll = px.cummax()
    dd = (px / roll) - 1.0
    return float(dd.min())


def sharpe(px: pd.Series) -> float:
    r = log_returns(px).dropna()
    if len(r) < 10 or r.std() == 0:
        return float("nan")
    return float((r.mean() / r.std()) * np.sqrt(252))


def beta_and_corr(asset_rets: pd.Series, bench_rets: pd.Series):
    df = pd.concat([asset_rets, bench_rets], axis=1).dropna()
    if df.shape[0] < 30:
        return float("nan"), float("nan")
    a = df.iloc[:, 0].values
    b = df.iloc[:, 1].values
    cov = np.cov(a, b)[0, 1]
    var = np.var(b)
    beta = cov / var if var > 0 else float("nan")
    corr = float(np.corrcoef(a, b)[0, 1])
    return float(beta), float(corr)


def hurst_exponent(px: pd.Series) -> float:
    s = px.dropna().astype(float).values
    if len(s) < 80:
        return float("nan")
    lags = np.array([5, 10, 20, 40])
    tau = []
    for lag in lags:
        if len(s) <= lag + 2:
            continue
        diff = s[lag:] - s[:-lag]
        tau.append(np.sqrt(np.std(diff)))
    tau = np.array(tau)
    if len(tau) < 3 or np.any(tau <= 0):
        return float("nan")
    poly = np.polyfit(np.log(lags[:len(tau)]), np.log(tau), 1)
    return float(2.0 * poly[0])


# ============================================================
# MarketStack: pagination (max history your plan allows)
# ============================================================
def fetch_eod_marketstack(symbol: str, start_date: str, end_date: str, limit: int = 1000) -> pd.DataFrame:
    key = os.getenv("MARKETSTACK_API_KEY")
    if not key:
        raise RuntimeError("MARKETSTACK_API_KEY env var not set.")

    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("Ticker is empty.")

    all_rows = []
    offset = 0
    max_pages = 100  # safety cap

    for _ in range(max_pages):
        params = {
            "access_key": key,
            "symbols": symbol,
            "date_from": start_date,
            "date_to": end_date,
            "limit": limit,
            "offset": offset,
            "sort": "ASC",
        }

        r = requests.get(MARKETSTACK_EOD_URL, params=params, timeout=25)
        if r.status_code == 429:
            raise RuntimeError("MarketStack rate limit (HTTP 429). Try again later.")
        r.raise_for_status()

        payload = r.json()
        data = payload.get("data", [])
        if not data:
            break

        all_rows.extend(data)
        offset += len(data)

        if len(data) < limit:
            break

    if not all_rows:
        raise RuntimeError(f"No data returned for {symbol}. Check symbol/date range/plan.")

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.sort_values("date").reset_index(drop=True)

    required = ["open", "high", "low", "close", "volume"]
    for c in required:
        if c not in df.columns:
            raise RuntimeError(f"MarketStack response missing: {c}")

    if "adj_close" in df.columns and df["adj_close"].notna().any():
        df["px"] = df["adj_close"].astype(float)
        df["px_note"] = "Using MarketStack adjusted close (adj_close)."
        df["adj_method"] = "adj_close"
    else:
        df["px"] = df["close"].astype(float)
        df["px_note"] = "Adjusted close not available; using close + split heuristic (best-effort)."
        df["adj_method"] = "close"

    out = df[["date", "open", "high", "low", "close", "volume", "px", "px_note", "adj_method"]].copy()
    return out


# ============================================================
# Split heuristic fallback (if adj_close missing)
# ============================================================
def _nearest_split_ratio(x: float):
    common = [2, 3, 4, 5, 10]
    candidates = common + [1/c for c in common]
    best, best_err = None, 1e9
    for r in candidates:
        err = abs(x - r)
        if err < best_err:
            best_err = err
            best = r
    return best, best_err


def adjust_splits_to_post_scale(df: pd.DataFrame, price_col="px") -> pd.DataFrame:
    out = df.copy()
    px = out[price_col].astype(float).values
    if len(px) < 20:
        out["px_adj"] = px
        out["split_note"] = "Too little data to detect splits; left unadjusted."
        return out

    daily_ratio = px[1:] / np.maximum(px[:-1], 1e-12)
    adj = px.copy()
    events = []

    for i, rr in enumerate(daily_ratio, start=1):
        if rr > 1.35 or rr < 0.74:
            nearest, err = _nearest_split_ratio(rr)
            if err < 0.18:
                f = float(nearest)
                adj[:i] *= f
                events.append((out["date"].iloc[i], f, float(rr)))

    out["px_adj"] = adj
    if events:
        out["split_note"] = "Heuristic split adjustment detected:\n" + "\n".join(
            [f"- {d.date()} factor≈{f:.3f} (raw ratio {raw:.3f})" for d, f, raw in events]
        )
    else:
        out["split_note"] = "No split-like jumps detected by heuristic."
    return out


# ============================================================
# Forecasting: ALWAYS works for >=10 days (auto-adaptive)
# ============================================================
@dataclass
class ForecastOutput:
    estimated_price: float
    up_probability: float
    confidence: float
    model: str
    notes: str
    rmse: float = float("nan")
    mape: float = float("nan")
    hit_rate: float = float("nan")
    auc: float = float("nan")


def _confidence_from_history(n: int):
    if n < 20:
        return 0.10
    if n < 60:
        return 0.18
    if n < 180:
        return 0.28
    if n < 500:
        return 0.45
    return 0.60


def _forecast_bootstrap(px: pd.Series, horizon_days: int, n_sims: int = 6000) -> ForecastOutput:
    s0 = float(px.iloc[-1])
    r = log_returns(px).dropna().values
    n = len(px)

    sims = np.random.choice(r, size=(n_sims, horizon_days), replace=True)
    paths = np.exp(np.cumsum(sims, axis=1)) * s0
    terminal = paths[:, -1]

    est = float(np.median(terminal))
    up_prob = float((terminal > s0).mean())
    conf = _confidence_from_history(n) * 0.75

    return ForecastOutput(
        estimated_price=est,
        up_probability=up_prob,
        confidence=conf,
        model="BOOTSTRAP_RETURNS",
        notes="Short-history bootstrap on log returns. Runs with >=10 days; uncertainty is wide."
    )


def _forecast_drift_vol(px: pd.Series, horizon_days: int, n_sims: int = 12000) -> ForecastOutput:
    s0 = float(px.iloc[-1])
    r = log_returns(px).dropna()
    n = len(px)

    mu = float(r.mean()) if len(r) else 0.0
    sig = float(r.std()) if float(r.std()) > 0 else 0.02

    Z = np.random.randn(n_sims, horizon_days)
    inc = (mu - 0.5 * sig * sig) + sig * Z
    terminal = s0 * np.exp(np.sum(inc, axis=1))

    est = float(np.median(terminal))
    up_prob = float((terminal > s0).mean())
    conf = _confidence_from_history(n) * 0.85

    return ForecastOutput(
        estimated_price=est,
        up_probability=up_prob,
        confidence=conf,
        model="GBM_DRIFT_VOL",
        notes="Medium-history GBM using sample drift/vol. No walk-forward ML."
    )


def build_features(df: pd.DataFrame, price_col: str) -> pd.DataFrame:
    x = df.copy()
    px = x[price_col].astype(float)

    x["lr1"] = np.log(px).diff()
    x["lr5"] = np.log(px).diff(5)
    x["vol10"] = x["lr1"].rolling(10).std()
    x["vol20"] = x["lr1"].rolling(20).std()

    x["sma20"] = px.rolling(20).mean()
    x["sma50"] = px.rolling(50).mean()
    x["ema20"] = ema(px, 20)
    x["rsi14"] = rsi(px, 14)

    m, s, h = macd(px)
    x["macd"] = m
    x["macd_sig"] = s
    x["macd_hist"] = h

    x["volchg"] = x["volume"].pct_change()
    x["px_sma20"] = (px / x["sma20"]) - 1
    x["px_sma50"] = (px / x["sma50"]) - 1

    x["dow"] = x["date"].dt.dayofweek
    x["month"] = x["date"].dt.month

    x = x.dropna().reset_index(drop=True)
    return x


def make_targets(feat: pd.DataFrame, price_col: str, horizon: int) -> pd.DataFrame:
    y = feat.copy()
    px = y[price_col].astype(float).values
    if len(px) <= horizon + 5:
        return pd.DataFrame()
    fwd_lr = np.log(px[horizon:] / px[:-horizon])
    y = y.iloc[:-horizon].copy()
    y["y_lr"] = fwd_lr
    y["y_up"] = (y["y_lr"] > 0).astype(int)
    return y


def _safe_auc(y_true, y_score):
    try:
        if len(np.unique(y_true)) < 2:
            return float("nan")
        return float(roc_auc_score(y_true, y_score))
    except Exception:
        return float("nan")


def _walk_forward_ensemble(X: np.ndarray, y_lr: np.ndarray, y_up: np.ndarray):
    n = len(X)
    n_splits = 5 if n > 700 else 4 if n > 420 else 3
    tscv = TimeSeriesSplit(n_splits=n_splits)

    scaler = StandardScaler()

    reg_models = {
        "Ridge": Ridge(alpha=1.0),
        "GBR": GradientBoostingRegressor(random_state=7),
        "RF": RandomForestRegressor(n_estimators=250, random_state=7, n_jobs=-1),
    }
    clf_models = {
        "Logit": LogisticRegression(max_iter=2000),
        "RFc": RandomForestClassifier(n_estimators=250, random_state=7, n_jobs=-1),
    }

    reg_rmse, reg_mape, hit_rates, aucs = [], [], [], []
    can_classify = (len(np.unique(y_up)) >= 2)

    for tr, te in tscv.split(X):
        Xtr, Xte = X[tr], X[te]
        ytr_lr, yte_lr = y_lr[tr], y_lr[te]
        ytr_up, yte_up = y_up[tr], y_up[te]

        Xtr_s = scaler.fit_transform(Xtr)
        Xte_s = scaler.transform(Xte)

        preds = []
        for m in reg_models.values():
            m.fit(Xtr_s, ytr_lr)
            preds.append(m.predict(Xte_s))
        pred_lr = np.mean(np.vstack(preds), axis=0)

        rmse = math.sqrt(mean_squared_error(yte_lr, pred_lr))
        reg_rmse.append(rmse)

        true_ratio = np.exp(yte_lr)
        pred_ratio = np.exp(pred_lr)
        try:
            reg_mape.append(float(mean_absolute_percentage_error(true_ratio, pred_ratio)))
        except Exception:
            reg_mape.append(float("nan"))

        if can_classify and len(np.unique(ytr_up)) >= 2:
            probas = []
            for cm in clf_models.values():
                cm.fit(Xtr_s, ytr_up)
                probas.append(cm.predict_proba(Xte_s)[:, 1])
            p_up = np.mean(np.vstack(probas), axis=0)
            pred_up = (p_up >= 0.5).astype(int)
            hit_rates.append(float((pred_up == yte_up).mean()))
            aucs.append(_safe_auc(yte_up, p_up))
        else:
            hit_rates.append(float("nan"))
            aucs.append(float("nan"))

    Xs = scaler.fit_transform(X)
    for m in reg_models.values():
        m.fit(Xs, y_lr)
    for cm in clf_models.values():
        if can_classify:
            cm.fit(Xs, y_up)

    return {
        "scaler": scaler,
        "reg_models": reg_models,
        "clf_models": clf_models,
        "can_classify": can_classify,
        "rmse": float(np.nanmean(reg_rmse)),
        "mape": float(np.nanmean(reg_mape)),
        "hit_rate": float(np.nanmean(hit_rates)),
        "auc": float(np.nanmean(aucs)),
    }


def _confidence_from_metrics(n, rmse, auc, hit_rate, can_classify: bool):
    base = _confidence_from_history(n)
    rmse_score = float(np.clip(1.0 - (rmse / 0.30), 0.05, 0.95)) if np.isfinite(rmse) else 0.35
    auc_score = float(np.clip((auc - 0.5) / 0.5, 0.0, 1.0)) if (can_classify and np.isfinite(auc)) else 0.50
    hit_score = float(np.clip((hit_rate - 0.5) / 0.5, 0.0, 1.0)) if (can_classify and np.isfinite(hit_rate)) else 0.50
    conf = base * (0.55 * rmse_score + 0.25 * auc_score + 0.20 * hit_score)
    return float(np.clip(conf, 0.05, 0.85))


def forecast_any_history(df: pd.DataFrame, price_col: str) -> dict:
    px = df[price_col].astype(float)
    n = len(px)
    if n < 10:
        return {"error": f"Need at least 10 trading days. Loaded: {n}."}

    last_price = float(px.iloc[-1])
    horizons = {"2 months": 42, "6 months": 126, "12 months": 252}

    out = {"last_price": last_price, "history_days_loaded": int(n), "horizons": {}, "notes": []}

    feat = None
    if n >= 80:
        try:
            feat = build_features(df, price_col)
        except Exception:
            feat = None

    for name, h in horizons.items():
        if n < 60:
            fo = _forecast_bootstrap(px, h)
            out["horizons"][name] = fo.__dict__
            continue

        if n < 180:
            fo = _forecast_drift_vol(px, h)
            out["horizons"][name] = fo.__dict__
            continue

        # try ML; fallback gracefully
        if feat is None or len(feat) < 40:
            fo = _forecast_drift_vol(px, h)
            fo.notes += " (ML unavailable; used GBM fallback.)"
            out["horizons"][name] = fo.__dict__
            continue

        ydf = make_targets(feat, price_col, h)
        if ydf.empty or len(ydf) < 25:
            fo = _forecast_drift_vol(px, h)
            fo.notes += " (Not enough targets for ML; used GBM fallback.)"
            out["horizons"][name] = fo.__dict__
            continue

        feature_cols = ["lr1","lr5","vol10","vol20","px_sma20","px_sma50","rsi14","macd","macd_sig","macd_hist","volchg","dow","month"]
        X = ydf[feature_cols].values.astype(float)
        y_lr = ydf["y_lr"].values.astype(float)
        y_up = ydf["y_up"].values.astype(int)

        try:
            met = _walk_forward_ensemble(X, y_lr, y_up)
            scaler = met["scaler"]
            X_last = feat[feature_cols].iloc[[-1]].values.astype(float)
            X_last_s = scaler.transform(X_last)

            reg_preds = [m.predict(X_last_s)[0] for m in met["reg_models"].values()]
            pred_lr = float(np.mean(reg_preds))
            est_price = last_price * float(np.exp(pred_lr))

            can_classify = met["can_classify"]
            if can_classify:
                probs = [cm.predict_proba(X_last_s)[0, 1] for cm in met["clf_models"].values()]
                up_prob = float(np.mean(probs))
            else:
                up_prob = float(np.clip(np.mean(y_up), 0.05, 0.95))

            conf = _confidence_from_metrics(n, met["rmse"], met["auc"], met["hit_rate"], can_classify)

            fo = ForecastOutput(
                estimated_price=est_price,
                up_probability=up_prob,
                confidence=conf,
                model="ENSEMBLE_ML_WF",
                notes="Ensemble ML with walk-forward validation metrics shown.",
                rmse=met["rmse"],
                mape=met["mape"],
                hit_rate=met["hit_rate"],
                auc=met["auc"],
            )
            out["horizons"][name] = fo.__dict__
        except Exception:
            fo = _forecast_drift_vol(px, h)
            fo.notes += " (ML failed; used GBM fallback.)"
            out["horizons"][name] = fo.__dict__

    out["notes"].append("Forecasting always runs for >=10 days; model adapts to available history.")
    return out


# ============================================================
# Monte Carlo live loop (same behavior as previous, slowed)
# ============================================================
class MonteCarloLiveLoop:
    def __init__(self, ax, canvas, status_cb=None):
        self.ax = ax
        self.canvas = canvas
        self.status_cb = status_cb

        self.running = False
        self._after_id = None

        self.duration_sec = 10.0
        self.n_paths = 300
        self.horizon_days = 252

        self.paths = None
        self.lines = []
        self.s0 = None
        self.mu = None
        self.sigma = None
        self.start_time = None
        self.current_line = None

    def _status(self, msg):
        if self.status_cb:
            self.status_cb(msg)

    def configure(self, n_paths, horizon_days, duration_sec):
        self.n_paths = int(max(20, min(1500, n_paths)))
        self.horizon_days = int(max(30, min(2000, horizon_days)))
        self.duration_sec = float(max(3.0, min(45.0, duration_sec)))

    def _estimate(self, px: pd.Series):
        r = log_returns(px).dropna()
        if len(r) < 10:
            raise RuntimeError("Need >=10 trading days for Monte Carlo.")
        self.mu = float(r.mean())
        self.sigma = float(r.std()) if float(r.std()) > 0 else 1e-6
        self.s0 = float(px.iloc[-1])

    def _generate_paths(self):
        T = self.horizon_days
        N = self.n_paths
        Z = np.random.randn(T, N)
        inc = (self.mu - 0.5 * self.sigma * self.sigma) + self.sigma * Z

        logS = np.zeros((T, N), dtype=float)
        logS[0, :] = np.log(self.s0)
        if T > 1:
            logS[1:, :] = logS[0, :] + np.cumsum(inc[1:, :], axis=0)
        self.paths = np.exp(logS)

    def _init_plot(self):
        self.ax.clear()
        self.ax.set_title("MONTE CARLO • LIVE LOOP", loc="left")
        self.ax.set_xlabel("Days")
        self.ax.set_ylabel("Price")
        self.current_line = self.ax.axhline(self.s0, linestyle="--", linewidth=1.3, alpha=0.9)
        self.lines = [self.ax.plot([], [], alpha=0.10, linewidth=1.0)[0] for _ in range(self.n_paths)]
        self.canvas.draw_idle()

    def start(self, px: pd.Series):
        if self.running:
            return
        self.running = True
        self._status("Monte Carlo: generating paths...")
        self._estimate(px)
        self._generate_paths()
        self._init_plot()
        self.start_time = time.perf_counter()
        self._status("Monte Carlo: running.")
        self._schedule()

    def pause(self):
        self.running = False
        if self._after_id:
            try:
                self.canvas.get_tk_widget().after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = None
        self._status("Monte Carlo: paused.")

    def _schedule(self):
        self._after_id = self.canvas.get_tk_widget().after(55, self._tick)

    def _tick(self):
        if not self.running:
            return

        elapsed = time.perf_counter() - self.start_time
        frac = elapsed / self.duration_sec

        if frac >= 1.0:
            self._status("Monte Carlo: reset...")
            self._generate_paths()
            self._init_plot()
            self.start_time = time.perf_counter()
            self._status("Monte Carlo: running.")
            self._schedule()
            return

        T = self.horizon_days
        k = max(2, int(frac * T))
        x = np.arange(k)

        for i, line in enumerate(self.lines):
            line.set_data(x, self.paths[:k, i])
        if self.current_line is not None:
            self.current_line.set_ydata([self.s0, self.s0])

        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()
        self._schedule()


# ============================================================
# OpenAI Fundamentals Analyzer (separate tab + GOOD/OK/BAD key)
# ============================================================
def openai_fundamentals_analyze(ticker: str, fundamentals_text: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "error": "OPENAI_API_KEY not set. Fundamentals analysis unavailable.",
            "key": "OK",
            "6_sentence_summary": "Set OPENAI_API_KEY to enable fundamentals analysis.",
            "bullets_good": [],
            "bullets_bad": [],
            "watch_items": [],
            "questions_to_verify": []
        }

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        prompt = f"""
You are a strict equity research fundamentals analyst.

Ticker: {ticker}

The user pasted fundamentals below (may include metrics like revenue, margins, FCF, debt, EPS, guidance, valuation multiples, etc).

Tasks:
1) Extract the most important fundamentals and restate them cleanly.
2) Grade fundamentals using a KEY:
   - GOOD: strong growth/profitability/FCF balance sheet and valuation not extreme for growth
   - OK: mixed signals, decent but with notable risks
   - BAD: weak profitability/FCF, deteriorating balance sheet, heavy dilution, extreme leverage, collapsing growth
3) Output JSON with fields:
   key (GOOD/OK/BAD),
   bullets_good (list),
   bullets_bad (list),
   watch_items (list),
   questions_to_verify (list),
   6_sentence_summary (string).

Hard rules:
- Only use the pasted fundamentals. Do not invent figures or claim things not present.
- If critical data is missing, explicitly say what's missing and downgrade certainty.

Fundamentals pasted:
{fundamentals_text}
""".strip()

        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        text = resp.choices[0].message.content.strip()

        try:
            data = json.loads(text)
        except Exception:
            data = {
                "key": "OK",
                "bullets_good": [],
                "bullets_bad": [],
                "watch_items": [],
                "questions_to_verify": ["AI returned non-JSON. Paste more structured fundamentals with numbers + time periods."],
                "6_sentence_summary": text
            }

        key = (data.get("key") or "OK").upper().strip()
        if key not in ["GOOD", "OK", "BAD"]:
            data["key"] = "OK"
        else:
            data["key"] = key
        return data

    except Exception as e:
        return {
            "error": f"OpenAI error: {e}",
            "key": "OK",
            "6_sentence_summary": "OpenAI request failed.",
            "bullets_good": [],
            "bullets_bad": [],
            "watch_items": [],
            "questions_to_verify": [str(e)]
        }


# ============================================================
# APP UI (matches previous layout)
# ============================================================
class TerminalStockApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Terminal • Advanced Stock Analytics")
        self.geometry("1560x940")
        self.minsize(1280, 800)
        self.configure(fg_color=BG)

        self.uiq = queue.Queue()

        self.df = None
        self.ticker = None
        self.price_col = None
        self.spy_df = None
        self.spy_price_col = None

        self._build_ui()
        self.after(60, self._poll)

    def _poll(self):
        try:
            while True:
                fn, payload = self.uiq.get_nowait()
                fn(payload)
        except queue.Empty:
            pass
        self.after(60, self._poll)

    def _ui(self, fn, payload=None):
        self.uiq.put((fn, payload))

    def set_status(self, msg, color=TEXT):
        self.status_var.set(msg)
        self.status_label.configure(text_color=color)

    def _module_header(self, parent, title):
        bar = ctk.CTkFrame(parent, fg_color=GRID, corner_radius=8, height=28)
        bar.pack(fill="x", padx=10, pady=(10, 6))
        lab = ctk.CTkLabel(bar, text=title, text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"))
        lab.pack(side="left", padx=10)
        return bar

    def _styled_fig(self, w=8.8, h=4.6):
        fig, ax = plt.subplots(figsize=(w, h))
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(BG)
        ax.tick_params(colors=DIM)
        for sp in ax.spines.values():
            sp.set_color(GRID)
        return fig, ax

    def _build_ui(self):
        # Top bar (same as previous)
        top = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=12)
        top.pack(fill="x", padx=10, pady=(10, 8))
        top.grid_columnconfigure(10, weight=1)

        self.brand = ctk.CTkLabel(top, text="TERMINAL", text_color=ACCENT, font=ctk.CTkFont(size=16, weight="bold"))
        self.brand.grid(row=0, column=0, padx=(14, 10), pady=10, sticky="w")

        ctk.CTkLabel(top, text="TICKER", text_color=DIM).grid(row=0, column=1, padx=(0, 6), pady=10, sticky="w")
        self.ticker_var = ctk.StringVar(value="AAPL")
        self.ticker_entry = ctk.CTkEntry(top, textvariable=self.ticker_var, width=120, height=34, corner_radius=10)
        self.ticker_entry.grid(row=0, column=2, padx=(0, 14), pady=10, sticky="w")

        ctk.CTkLabel(top, text="HISTORY(D)", text_color=DIM).grid(row=0, column=3, padx=(0, 6), pady=10, sticky="w")
        self.days_var = ctk.StringVar(value="1800")
        self.days_entry = ctk.CTkEntry(top, textvariable=self.days_var, width=110, height=34, corner_radius=10)
        self.days_entry.grid(row=0, column=4, padx=(0, 14), pady=10, sticky="w")

        self.fetch_btn = ctk.CTkButton(top, text="FETCH", corner_radius=10, height=34, command=self.fetch_data)
        self.fetch_btn.grid(row=0, column=5, padx=(0, 8), pady=10, sticky="w")

        self.run_btn = ctk.CTkButton(top, text="RUN", corner_radius=10, height=34, command=self.run_analysis)
        self.run_btn.grid(row=0, column=6, padx=(0, 14), pady=10, sticky="w")

        self.status_var = ctk.StringVar(value="Ready.")
        self.status_label = ctk.CTkLabel(top, textvariable=self.status_var, text_color=TEXT)
        self.status_label.grid(row=0, column=10, padx=10, pady=10, sticky="w")

        # Main layout: Left monitor + Right tabs
        main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        main.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        # LEFT (same structure as previous)
        left = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=12, width=390)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 10), pady=0)
        left.grid_propagate(False)
        left.grid_rowconfigure(99, weight=1)

        self._module_header(left, "QUOTE MONITOR • WATCHLIST")
        self.watch = ctk.CTkTextbox(left, height=140, fg_color=BG, text_color=TEXT, corner_radius=10)
        self.watch.pack(fill="x", padx=10, pady=(0, 10))
        self.watch.insert("1.0", "AAPL\nMSFT\nNVDA\nAVGO\nSPY\n")

        self._module_header(left, "SIMULATION • MONTE CARLO INPUTS")
        form = ctk.CTkFrame(left, fg_color=PANEL, corner_radius=10)
        form.pack(fill="x", padx=10, pady=(0, 10))
        form.grid_columnconfigure(1, weight=1)

        self.mc_paths = ctk.StringVar(value="300")
        self.mc_horizon = ctk.StringVar(value="252")
        self.mc_loop = ctk.StringVar(value="10")

        self._kv(form, 0, "Paths", self.mc_paths, "e.g. 300")
        self._kv(form, 1, "Horizon", self.mc_horizon, "e.g. 252")
        self._kv(form, 2, "Loop(s)", self.mc_loop, "e.g. 10")

        self.mc_btn = ctk.CTkButton(left, text="START/PAUSE MONTE", corner_radius=10, height=36, command=self.toggle_monte)
        self.mc_btn.pack(fill="x", padx=10, pady=(0, 10))

        self._module_header(left, "SNAPSHOT • METRICS")
        self.snapshot = ctk.CTkTextbox(left, height=220, fg_color=BG, text_color=TEXT, corner_radius=10, wrap="word")
        self.snapshot.pack(fill="x", padx=10, pady=(0, 10))

        self._module_header(left, "ACTIONS")
        actions = ctk.CTkFrame(left, fg_color=PANEL, corner_radius=10)
        actions.pack(fill="x", padx=10, pady=(0, 10))
        actions.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(actions, text="EXPORT TXT", corner_radius=10, command=self.export_txt).grid(row=0, column=0, padx=6, pady=8, sticky="ew")
        ctk.CTkButton(actions, text="RESET", corner_radius=10, command=self.reset_all).grid(row=0, column=1, padx=6, pady=8, sticky="ew")

        # RIGHT tabs (same as previous + Fundamentals tab added)
        right = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(right, fg_color=PANEL, corner_radius=12)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        self.tab_dashboard = self.tabs.add("DASH")
        self.tab_tech = self.tabs.add("TECH")
        self.tab_risk = self.tabs.add("RISK")
        self.tab_regime = self.tabs.add("REGIME")
        self.tab_season = self.tabs.add("SEASON")
        self.tab_forecast = self.tabs.add("FORECAST")
        self.tab_monte = self.tabs.add("MONTE")
        self.tab_fund = self.tabs.add("FUNDAMENTALS (AI)")
        self.tab_logs = self.tabs.add("LOGS")

        self._build_tabs()

        # shortcuts
        self.bind("<Return>", lambda e: self.run_analysis())
        self.bind("<Control-r>", lambda e: self.fetch_data())

    def _kv(self, parent, row, label, var, placeholder):
        ctk.CTkLabel(parent, text=label, text_color=DIM).grid(row=row, column=0, padx=8, pady=6, sticky="w")
        ent = ctk.CTkEntry(parent, textvariable=var, height=30, corner_radius=10)
        ent.grid(row=row, column=1, padx=8, pady=6, sticky="ew")
        ent.configure(placeholder_text=placeholder)

    def _build_tabs(self):
        # DASH
        self.dash_fig, self.dash_ax = self._styled_fig(9.2, 4.4)
        self.dash_canvas = FigureCanvasTkAgg(self.dash_fig, master=self.tab_dashboard)
        self.dash_canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(10, 6))
        self.dash_text = ctk.CTkTextbox(self.tab_dashboard, height=180, fg_color=BG, text_color=TEXT, corner_radius=10, wrap="word")
        self.dash_text.pack(fill="x", padx=10, pady=(0, 10))

        # TECH
        self.tech_fig, self.tech_ax = self._styled_fig(9.2, 4.4)
        self.tech_canvas = FigureCanvasTkAgg(self.tech_fig, master=self.tab_tech)
        self.tech_canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(10, 6))
        self.tech_text = ctk.CTkTextbox(self.tab_tech, height=180, fg_color=BG, text_color=TEXT, corner_radius=10, wrap="word")
        self.tech_text.pack(fill="x", padx=10, pady=(0, 10))

        # RISK/REGIME/SEASON/FORECAST
        self.risk_text = ctk.CTkTextbox(self.tab_risk, fg_color=BG, text_color=TEXT, corner_radius=10, wrap="word")
        self.risk_text.pack(fill="both", expand=True, padx=10, pady=10)

        self.regime_text = ctk.CTkTextbox(self.tab_regime, fg_color=BG, text_color=TEXT, corner_radius=10, wrap="word")
        self.regime_text.pack(fill="both", expand=True, padx=10, pady=10)

        self.season_text = ctk.CTkTextbox(self.tab_season, fg_color=BG, text_color=TEXT, corner_radius=10, wrap="word")
        self.season_text.pack(fill="both", expand=True, padx=10, pady=10)

        self.forecast_text = ctk.CTkTextbox(self.tab_forecast, fg_color=BG, text_color=TEXT, corner_radius=10, wrap="word")
        self.forecast_text.pack(fill="both", expand=True, padx=10, pady=10)

        # MONTE chart (same as previous)
        self.mc_fig, self.mc_ax = self._styled_fig(9.2, 4.4)
        self.mc_canvas = FigureCanvasTkAgg(self.mc_fig, master=self.tab_monte)
        self.mc_canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
        self.mc_engine = MonteCarloLiveLoop(self.mc_ax, self.mc_canvas, status_cb=self.set_status)

        # FUNDAMENTALS tab UI (new, but styled consistent)
        self._build_fundamentals_tab()

        # LOGS
        self.logs = ctk.CTkTextbox(self.tab_logs, fg_color=BG, text_color=TEXT, corner_radius=10, wrap="none")
        self.logs.pack(fill="both", expand=True, padx=10, pady=10)
        self.logs.insert("1.0", "Logs:\n")

    def _build_fundamentals_tab(self):
        header = ctk.CTkFrame(self.tab_fund, fg_color=GRID, corner_radius=10)
        header.pack(fill="x", padx=10, pady=(10, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Paste key fundamentals (numbers + time periods) then analyze with OpenAI.",
            text_color=TEXT,
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, padx=10, pady=10, sticky="w")

        self.fund_btn = ctk.CTkButton(header, text="ANALYZE", corner_radius=10, height=34, command=self.run_fundamentals)
        self.fund_btn.grid(row=0, column=1, padx=10, pady=10, sticky="e")

        self.fund_input = ctk.CTkTextbox(self.tab_fund, height=230, fg_color=BG, text_color=TEXT, corner_radius=10, wrap="word")
        self.fund_input.pack(fill="x", padx=10, pady=(0, 10))
        self.fund_input.insert(
            "1.0",
            "Example paste:\n"
            "- Revenue (TTM): ...\n"
            "- Revenue growth (YoY): ...\n"
            "- Gross margin: ...\n"
            "- Operating margin: ...\n"
            "- FCF (TTM): ...\n"
            "- Net debt / cash: ...\n"
            "- EPS growth (YoY): ...\n"
            "- Forward P/E: ...\n"
            "- Guidance: ...\n"
        )

        keybar = ctk.CTkFrame(self.tab_fund, fg_color=GRID, corner_radius=10)
        keybar.pack(fill="x", padx=10, pady=(0, 8))
        self.fund_key_var = ctk.StringVar(value="KEY: —")
        self.fund_key_label = ctk.CTkLabel(keybar, textvariable=self.fund_key_var, text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold"))
        self.fund_key_label.pack(side="left", padx=10, pady=8)

        self.fund_out = ctk.CTkTextbox(self.tab_fund, fg_color=BG, text_color=TEXT, corner_radius=10, wrap="word")
        self.fund_out.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.logs.insert("end", f"[{ts}] {msg}\n")
        self.logs.see("end")

    # ---------------- DATA ----------------
    def fetch_data(self):
        sym = self.ticker_var.get().strip().upper()
        try:
            days = max(int(self.days_var.get().strip()), 2000)
        except Exception:
            self.set_status("Invalid HISTORY days.", BAD)
            return

        end = datetime.today().date()
        start = end - timedelta(days=days)

        self.fetch_btn.configure(state="disabled")
        self.run_btn.configure(state="disabled")
        self.set_status(f"Fetching {sym}...", TEXT)
        self.log(f"FETCH {sym} {start}→{end}")

        def task():
            df = fetch_eod_marketstack(sym, str(start), str(end), limit=1000)

            if df["adj_method"].iloc[-1] == "adj_close":
                df["px_adj"] = df["px"]
                df["split_note"] = ""
                price_col = "px"
            else:
                df = adjust_splits_to_post_scale(df, "px")
                price_col = "px_adj"

            # fetch SPY for beta/corr (best-effort)
            spy = fetch_eod_marketstack("SPY", str(start), str(end), limit=1000)
            if spy["adj_method"].iloc[-1] == "adj_close":
                spy["px_adj"] = spy["px"]
                spy["split_note"] = ""
                spy_col = "px"
            else:
                spy = adjust_splits_to_post_scale(spy, "px")
                spy_col = "px_adj"

            self._ui(self._on_loaded, {"sym": sym, "df": df, "price_col": price_col, "spy": spy, "spy_col": spy_col})

        def on_err(e):
            self._ui(self._on_error, f"Fetch failed: {e}")

        run_in_thread(task, on_error=on_err)

    def _on_loaded(self, p):
        self.fetch_btn.configure(state="normal")
        self.run_btn.configure(state="normal")

        self.ticker = p["sym"]
        self.df = p["df"]
        self.price_col = p["price_col"]
        self.spy_df = p["spy"]
        self.spy_price_col = p["spy_col"]

        n = len(self.df)
        d0 = self.df["date"].iloc[0].date()
        d1 = self.df["date"].iloc[-1].date()

        self.set_status(f"Loaded {self.ticker} • {n} rows • {d0}→{d1}", ACCENT)
        self.log(f"LOADED {self.ticker} rows={n} range={d0}→{d1}")

        self._render_snapshot()
        self._render_price_chart()

    def _on_error(self, msg):
        self.fetch_btn.configure(state="normal")
        self.run_btn.configure(state="normal")
        self.set_status(str(msg), BAD)
        self.log(str(msg))

    # ---------------- RENDER ----------------
    def _render_snapshot(self):
        if self.df is None:
            return
        px = self.df[self.price_col].astype(float)

        txt = []
        txt.append(f"TICKER: {self.ticker}")
        txt.append(f"AS OF: {self.df['date'].iloc[-1].date()}")
        txt.append(f"ROWS: {len(self.df)}  RANGE: {self.df['date'].iloc[0].date()}→{self.df['date'].iloc[-1].date()}")
        txt.append(f"LAST: ${px.iloc[-1]:,.2f}")
        txt.append(f"VOL(ann): {ann_vol(px):.2%}")
        txt.append(f"DRIFT(ann): {ann_drift(px):.2%}")
        txt.append(f"MAX DD: {max_drawdown(px):.2%}")
        txt.append(f"SHARPE: {sharpe(px):.2f}")
        txt.append("")
        txt.append(self.df["px_note"].iloc[-1])
        if "split_note" in self.df.columns and self.df["split_note"].iloc[-1]:
            txt.append(self.df["split_note"].iloc[-1].splitlines()[0])

        self.snapshot.delete("1.0", "end")
        self.snapshot.insert("end", "\n".join(txt))

    def _render_price_chart(self):
        if self.df is None:
            return
        px = self.df[self.price_col].astype(float)
        self.dash_ax.clear()
        self.dash_ax.plot(self.df["date"], px, linewidth=1.8)
        self.dash_ax.set_title(f"{self.ticker} • PRICE (SPLIT-ADJUSTED SCALE)", loc="left", color=TEXT)
        self.dash_ax.tick_params(colors=DIM)
        for sp in self.dash_ax.spines.values():
            sp.set_color(GRID)
        self.dash_fig.tight_layout()
        self.dash_canvas.draw_idle()

        self.dash_text.delete("1.0", "end")
        self.dash_text.insert("end", "Fetch complete. Press RUN (or Enter) for full terminal stack.\n")

    def _render_tech_chart(self):
        if self.df is None:
            return
        px = self.df[self.price_col].astype(float)
        self.tech_ax.clear()
        self.tech_ax.plot(self.df["date"], px, linewidth=1.6)
        self.tech_ax.plot(self.df["date"], px.rolling(20).mean(), linewidth=1.2)
        self.tech_ax.plot(self.df["date"], px.rolling(50).mean(), linewidth=1.2)
        self.tech_ax.set_title(f"{self.ticker} • PRICE + SMA20/SMA50", loc="left", color=TEXT)
        self.tech_ax.tick_params(colors=DIM)
        for sp in self.tech_ax.spines.values():
            sp.set_color(GRID)
        self.tech_fig.tight_layout()
        self.tech_canvas.draw_idle()

    # ---------------- ANALYSIS ----------------
    def run_analysis(self):
        if self.df is None:
            self.set_status("Load data first (FETCH).", WARN)
            return

        self.run_btn.configure(state="disabled")
        self.set_status("Running analysis stack (forecast always works >=10 days)...", TEXT)
        self.log("RUN analysis start")

        def task():
            df = self.df.copy()
            px = df[self.price_col].astype(float)

            # TECH metrics
            sma20 = float(px.rolling(20).mean().iloc[-1]) if len(px) >= 20 else float("nan")
            sma50 = float(px.rolling(50).mean().iloc[-1]) if len(px) >= 50 else float("nan")
            rsi14v = float(rsi(px, 14).iloc[-1]) if len(px) >= 15 else float("nan")
            m, s, _h = macd(px)
            macd_last = float(m.iloc[-1]) if len(m) else float("nan")
            sig_last = float(s.iloc[-1]) if len(s) else float("nan")

            # RISK + SPY sensitivity
            a = log_returns(px).dropna()
            spy_px = self.spy_df[self.spy_price_col].astype(float)
            b = log_returns(spy_px).dropna()

            beta, corr = beta_and_corr(a.tail(252), b.tail(252))

            # REGIME
            hurst = hurst_exponent(px)
            rv20 = float(a.rolling(20).std().iloc[-1] * np.sqrt(252)) if len(a) >= 25 else float("nan")
            rv120 = float(a.rolling(120).std().iloc[-1] * np.sqrt(252)) if len(a) >= 130 else float("nan")
            if np.isfinite(rv120) and np.isfinite(rv20) and rv20 > rv120 * 1.15:
                vol_regime = "HIGH"
            else:
                vol_regime = "NORMAL/LOW"

            # SEASONALITY (only if we have enough data)
            season_text = self._fmt_season(df, self.price_col)

            # FORECAST (always works >=10)
            forecasts = forecast_any_history(df, self.price_col)

            computed = {
                "ticker": self.ticker,
                "as_of": str(df["date"].iloc[-1].date()),
                "rows": int(len(df)),
                "range": f"{df['date'].iloc[0].date()}→{df['date'].iloc[-1].date()}",
                "last": float(px.iloc[-1]),
                "vol_ann": ann_vol(px),
                "drift_ann": ann_drift(px),
                "maxdd": max_drawdown(px),
                "sharpe": sharpe(px),
                "sma20": sma20,
                "sma50": sma50,
                "rsi14": rsi14v,
                "macd": macd_last,
                "macd_sig": sig_last,
                "beta_1y": beta,
                "corr_1y": corr,
                "hurst": hurst,
                "rv20": rv20,
                "rv120": rv120,
                "vol_regime": vol_regime,
                "forecasts": forecasts,
                "data_note": df["px_note"].iloc[-1],
                "split_note": df["split_note"].iloc[-1] if "split_note" in df.columns else "",
            }

            panels = {
                "dash": self._fmt_dash(computed),
                "tech": self._fmt_tech(computed),
                "risk": self._fmt_risk(computed),
                "regime": self._fmt_regime(computed),
                "season": season_text,
                "forecast": self._fmt_forecast(computed),
            }
            self._ui(self._on_analysis_done, panels)

        def on_err(e):
            self._ui(self._on_error, f"Analysis failed: {e}")

        run_in_thread(task, on_error=on_err)

    def _on_analysis_done(self, p):
        self.run_btn.configure(state="normal")
        self.set_status("Analysis complete.", ACCENT)
        self.log("RUN analysis done")

        self.dash_text.delete("1.0", "end")
        self.dash_text.insert("end", p["dash"])

        self.tech_text.delete("1.0", "end")
        self.tech_text.insert("end", p["tech"])

        self.risk_text.delete("1.0", "end")
        self.risk_text.insert("end", p["risk"])

        self.regime_text.delete("1.0", "end")
        self.regime_text.insert("end", p["regime"])

        self.season_text.delete("1.0", "end")
        self.season_text.insert("end", p["season"])

        self.forecast_text.delete("1.0", "end")
        self.forecast_text.insert("end", p["forecast"])

        self._render_snapshot()
        self._render_tech_chart()

    # ---------------- FORECAST/SEASON FORMATTERS ----------------
    def _fmt_dash(self, c):
        f = c["forecasts"]
        lines = []
        lines.append(f"{c['ticker']} • DASH • {c['as_of']}")
        lines.append("")
        lines.append(f"Rows: {c['rows']}  Range: {c['range']}")
        lines.append(f"Last: ${c['last']:,.2f} | Vol(ann): {c['vol_ann']:.2%} | Drift(ann): {c['drift_ann']:.2%}")
        lines.append(f"Sharpe: {c['sharpe']:.2f} | MaxDD: {c['maxdd']:.2%} | Beta(1y): {c['beta_1y']:.2f} | Corr(1y): {c['corr_1y']:.2f}")
        lines.append("")
        lines.append("Forecast snapshot (always runs with >=10 days):")
        if "error" in f:
            lines.append(f"  {f['error']}")
        else:
            for k, v in f["horizons"].items():
                lines.append(f"  {k}: est ${v['estimated_price']:,.2f} | Up {v['up_probability']:.1%} | Conf {v['confidence']:.1%} | {v['model']}")
        lines.append("")
        lines.append(f"- {c['data_note']}")
        if c.get("split_note"):
            lines.append(f"- {c['split_note'].splitlines()[0]}")
        return "\n".join(lines)

    def _fmt_tech(self, c):
        lines = []
        lines.append("TECH STACK")
        lines.append("")
        lines.append(f"SMA20: {c['sma20'] if np.isfinite(c['sma20']) else 'n/a'} | SMA50: {c['sma50'] if np.isfinite(c['sma50']) else 'n/a'}")
        lines.append(f"RSI(14): {c['rsi14'] if np.isfinite(c['rsi14']) else 'n/a'}")
        lines.append(f"MACD: {c['macd'] if np.isfinite(c['macd']) else 'n/a'} | Signal: {c['macd_sig'] if np.isfinite(c['macd_sig']) else 'n/a'}")
        lines.append("")
        lines.append("Interpretation (rules-of-thumb):")
        lines.append("- SMA20 above SMA50 suggests short-term strength; below suggests weakness.")
        lines.append("- RSI>70 overbought, <30 oversold (context matters).")
        lines.append("- MACD above Signal suggests momentum improving.")
        return "\n".join(lines)

    def _fmt_risk(self, c):
        lines = []
        lines.append("RISK STACK")
        lines.append("")
        lines.append(f"Vol(ann): {c['vol_ann']:.2%}")
        lines.append(f"Max Drawdown: {c['maxdd']:.2%}")
        lines.append(f"Sharpe: {c['sharpe']:.2f}")
        lines.append("")
        lines.append("Market sensitivity:")
        lines.append(f"Beta(1y vs SPY): {c['beta_1y']:.2f}")
        lines.append(f"Corr(1y vs SPY): {c['corr_1y']:.2f}")
        return "\n".join(lines)

    def _fmt_regime(self, c):
        lines = []
        lines.append("REGIME / MARKET MICROSTRUCTURE PROXIES (price/volume only)")
        lines.append("")
        lines.append(f"Hurst exponent: {c['hurst'] if np.isfinite(c['hurst']) else 'n/a'}  (≈0.5 random walk; >0.5 trending; <0.5 mean-reverting)")
        lines.append(f"Realized vol regime: {c['vol_regime']} (RV20={c['rv20'] if np.isfinite(c['rv20']) else 'n/a'}, RV120={c['rv120'] if np.isfinite(c['rv120']) else 'n/a'})")
        lines.append("")
        lines.append("Split adjustment:")
        lines.append(f"- {c['data_note']}")
        if c.get("split_note"):
            lines.append(f"- {c['split_note'].splitlines()[0]}")
        return "\n".join(lines)

    def _fmt_season(self, df: pd.DataFrame, price_col: str) -> str:
        # Safe even with smaller histories
        try:
            if len(df) < 15:
                return "SEASONALITY\n\nNot enough history for seasonality summaries."
            tmp = df.copy()
            tmp["lr1"] = np.log(tmp[price_col].astype(float)).diff()
            tmp = tmp.dropna()
            if len(tmp) < 10:
                return "SEASONALITY\n\nNot enough history for seasonality summaries."
            tmp["dow"] = tmp["date"].dt.dayofweek
            tmp["month"] = tmp["date"].dt.month
            dow = tmp.groupby("dow")["lr1"].mean()
            mon = tmp.groupby("month")["lr1"].mean()

            lines = []
            lines.append("SEASONALITY (avg daily log-return by weekday / month)")
            lines.append("")
            lines.append("Weekday (0=Mon … 4=Fri):")
            for k in range(5):
                v = dow.get(k, float("nan"))
                lines.append(f"  {k}: {v:.5f}" if np.isfinite(v) else f"  {k}: n/a")
            lines.append("")
            lines.append("Month (1..12):")
            for m in range(1, 13):
                v = mon.get(m, float("nan"))
                lines.append(f"  {m:02d}: {v:.5f}" if np.isfinite(v) else f"  {m:02d}: n/a")
            lines.append("")
            lines.append("Note: Seasonality is small vs volatility; use as a minor prior.")
            return "\n".join(lines)
        except Exception:
            return "SEASONALITY\n\nUnable to compute seasonality for this dataset."

    def _fmt_forecast(self, c):
        f = c["forecasts"]
        lines = []
        lines.append("FORECAST STACK (Auto-adaptive: >=10 trading days supported)")
        lines.append("")
        if "error" in f:
            lines.append(f["error"])
            return "\n".join(lines)

        lines.append(f"History days loaded: {f['history_days_loaded']}")
        lines.append(f"Last: ${f['last_price']:,.2f}")
        lines.append("")

        for k, v in f["horizons"].items():
            lines.append(f"=== {k} ===")
            lines.append(f"Model: {v['model']}")
            lines.append(f"Estimated Price: ${v['estimated_price']:,.2f}")
            lines.append(f"Up/Down Prob: {v['up_probability']:.1%} / {(1-v['up_probability']):.1%}")
            lines.append(f"Confidence: {v['confidence']:.1%}")
            if v["model"] == "ENSEMBLE_ML_WF":
                lines.append(f"WF RMSE (logret): {v['rmse']:.4f}")
                lines.append(f"WF MAPE (ratio): {v['mape']:.4f}")
                lines.append(f"WF HitRate: {v['hit_rate']:.2%} | WF AUC: {v['auc'] if np.isfinite(v['auc']) else 'n/a'}")
            lines.append(f"Notes: {v['notes']}")
            lines.append("")

        lines.append("Notes:")
        for n in f.get("notes", []):
            lines.append(f"- {n}")
        return "\n".join(lines)

    # ---------------- MONTE ----------------
    def toggle_monte(self):
        if self.df is None:
            self.set_status("Load data first (FETCH).", WARN)
            return
        try:
            n_paths = int(self.mc_paths.get().strip())
            horizon = int(self.mc_horizon.get().strip())
            loop_s = float(self.mc_loop.get().strip())
        except Exception:
            self.set_status("Invalid Monte inputs.", BAD)
            return

        px = self.df[self.price_col].astype(float)
        self.mc_engine.configure(n_paths=n_paths, horizon_days=horizon, duration_sec=loop_s)

        if not self.mc_engine.running:
            self.tabs.set("MONTE")
            self.log(f"MONTE start paths={n_paths} horizon={horizon} loop={loop_s}s")
            try:
                self.mc_engine.start(px)
            except Exception as e:
                self.set_status(str(e), BAD)
        else:
            self.mc_engine.pause()
            self.log("MONTE paused")

    # ---------------- FUNDAMENTALS (AI) ----------------
    def run_fundamentals(self):
        tkr = (self.ticker_var.get() or "").strip().upper()
        text = self.fund_input.get("1.0", "end").strip()
        if len(text) < 25:
            self.set_status("Paste more fundamentals first.", WARN)
            return

        self.fund_btn.configure(state="disabled")
        self.set_status("Analyzing fundamentals (OpenAI)...", TEXT)
        self.log(f"FUNDAMENTALS analyze {tkr}")

        def task():
            res = openai_fundamentals_analyze(tkr, text)
            self._ui(self._on_fund_done, res)

        def on_err(e):
            self._ui(self._on_error, f"Fundamentals failed: {e}")

        run_in_thread(task, on_error=on_err)

    def _on_fund_done(self, res):
        self.fund_btn.configure(state="normal")

        key = (res.get("key") or "OK").upper().strip()
        if key not in ["GOOD", "OK", "BAD"]:
            key = "OK"

        if key == "GOOD":
            self.fund_key_label.configure(text_color=ACCENT)
        elif key == "BAD":
            self.fund_key_label.configure(text_color=BAD)
        else:
            self.fund_key_label.configure(text_color=WARN)

        self.fund_key_var.set(f"KEY: {key}")

        if "error" in res:
            self.set_status(res["error"], BAD)
        else:
            self.set_status("Fundamentals analysis complete.", ACCENT)

        def bullet_block(title, items):
            s = [title]
            if not items:
                s.append("  - (none)")
            else:
                for it in items:
                    s.append(f"  - {it}")
            return "\n".join(s)

        out = []
        out.append(res.get("6_sentence_summary", "").strip())
        out.append("")
        out.append(bullet_block("WHAT'S GOOD:", res.get("bullets_good", [])))
        out.append("")
        out.append(bullet_block("WHAT'S BAD / RISKS:", res.get("bullets_bad", [])))
        out.append("")
        out.append(bullet_block("WATCH ITEMS:", res.get("watch_items", [])))
        out.append("")
        out.append(bullet_block("QUESTIONS TO VERIFY:", res.get("questions_to_verify", [])))

        self.fund_out.delete("1.0", "end")
        self.fund_out.insert("end", "\n".join(out))
        self.tabs.set("FUNDAMENTALS (AI)")

    # ---------------- EXPORT / RESET ----------------
    def export_txt(self):
        if self.df is None:
            self.set_status("Nothing to export.", WARN)
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"terminal_{self.ticker}_{ts}.txt"

        content = []
        content.append("=== DASH ===\n" + self.dash_text.get("1.0", "end").strip())
        content.append("\n=== TECH ===\n" + self.tech_text.get("1.0", "end").strip())
        content.append("\n=== RISK ===\n" + self.risk_text.get("1.0", "end").strip())
        content.append("\n=== REGIME ===\n" + self.regime_text.get("1.0", "end").strip())
        content.append("\n=== SEASON ===\n" + self.season_text.get("1.0", "end").strip())
        content.append("\n=== FORECAST ===\n" + self.forecast_text.get("1.0", "end").strip())
        content.append("\n=== FUNDAMENTALS (AI) ===\n" + self.fund_out.get("1.0", "end").strip())

        try:
            with open(fname, "w", encoding="utf-8") as f:
                f.write("\n".join(content))
            self.set_status(f"Exported {fname}", ACCENT)
            self.log(f"EXPORT {fname}")
        except Exception as e:
            self.set_status(f"Export failed: {e}", BAD)

    def reset_all(self):
        if self.mc_engine and self.mc_engine.running:
            self.mc_engine.pause()

        self.df = None
        self.ticker = None
        self.price_col = None
        self.spy_df = None
        self.spy_price_col = None

        for t in [self.snapshot, self.dash_text, self.tech_text, self.risk_text, self.regime_text, self.season_text, self.forecast_text, self.fund_out]:
            t.delete("1.0", "end")

        self.dash_ax.clear()
        self.dash_canvas.draw_idle()
        self.tech_ax.clear()
        self.tech_canvas.draw_idle()
        self.mc_ax.clear()
        self.mc_canvas.draw_idle()

        self.fund_key_var.set("KEY: —")
        self.fund_key_label.configure(text_color=TEXT)

        self.set_status("Reset.", WARN)
        self.log("RESET")


def main():
    if sys.version_info < (3, 10):
        print("Use Python 3.10+")
        sys.exit(1)

    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("dark-blue")

    app = TerminalStockApp()
    app.mainloop()


if __name__ == "__main__":
    main()
