"""
Command-line entry point.

    python -m quantmc                 launch the terminal
    python -m quantmc --selftest      run the model suite headlessly, exit 1 on failure
    python -m quantmc --ticker NVDA   launch preloaded with a ticker
    python -m quantmc --offline       never touch the network; cache only
    python -m quantmc --headless ...  run one simulation and print the summary

The GUI import is deliberately deferred until after argument parsing, so
``--selftest`` and ``--headless`` work on a machine with no Qt installed.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quantmc",
        description="Monte Carlo and quantitative modelling terminal. "
                    "MODELLING TOOL, NOT INVESTMENT ADVICE.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Simulated distributions are conditional on the assumptions of "
               "the chosen model.",
    )
    p.add_argument("--version", action="version",
                   version=f"quantmc {__version__}")
    p.add_argument("--selftest", action="store_true",
                   help="run the full model suite with no GUI and exit "
                        "non-zero on failure")
    p.add_argument("--selftest-group", action="append", default=None,
                   metavar="NAME",
                   choices=["paths", "pricing", "stats", "calibration",
                            "risk", "engine"],
                   help="restrict --selftest to one group (repeatable)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="print tracebacks for failing self-test checks")

    p.add_argument("--ticker", "-t", default=None, help="preload this symbol")
    p.add_argument("--offline", action="store_true",
                   help="never contact the provider; serve cached data only")
    p.add_argument("--clear-cache", action="store_true",
                   help="empty the local market-data cache and exit")
    p.add_argument("--allow-synthetic", action="store_true",
                   help="permit falling back to generated fixture data when no "
                        "real data is available (off by default, so a data "
                        "failure is reported rather than faked)")

    h = p.add_argument_group("headless simulation")
    h.add_argument("--headless", action="store_true",
                   help="run one simulation without a GUI and print the summary")
    h.add_argument("--model", default="gbm",
                   help="path model (default: gbm)")
    h.add_argument("--paths", type=int, default=100_000, help="number of paths")
    h.add_argument("--horizon", type=int, default=252, help="steps to simulate")
    h.add_argument("--seed", type=int, default=42, help="RNG seed")
    h.add_argument("--calibrate", action="store_true",
                   help="calibrate the model from history before simulating")
    return p


def _run_headless(args: argparse.Namespace) -> int:
    """Run one simulation from the command line and print a compact report."""
    import numpy as np

    from .config import AppConfig, cache_path
    from .data import BarCache, MarketData, default_provider, interval_to_dt
    from .engine import SimRequest, SimulationEngine
    from .models import calibration as cal
    from .models import paths as pathmod
    from .models import stats as statmod

    cfg = AppConfig.load()
    ticker = (args.ticker or cfg.ticker).upper()
    cache = BarCache(cache_path())
    market = MarketData(provider=default_provider(), cache=cache,
                        offline=args.offline,
                        fallback_synthetic=args.allow_synthetic)

    hist = market.history(ticker, cfg.period, cfg.interval)
    print(f"\n{ticker}: {hist.status.health.value} -- {hist.status.message}")
    if hist.empty:
        print("No usable data. Aborting.")
        return 2
    returns = statmod.log_returns(hist.close)
    dt = interval_to_dt(cfg.interval)

    params = cfg.params_for(args.model)
    if args.calibrate:
        params.update(cal.calibrate(args.model, returns, dt))
        print("Calibrated:", {k: round(float(v), 6)
                              for k, v in params.items() if k != "returns"})

    request = SimRequest(
        ticker=ticker, s0=hist.spot, model=args.model, params=params,
        horizon_days=args.horizon, n_paths=args.paths, dt=dt, seed=args.seed,
        history_returns=returns,
        target_price=hist.spot * 1.1, barrier=hist.spot * 1.2,
        ruin_level=hist.spot * 0.5, risk_free=cfg.risk_free,
    )
    result = SimulationEngine().run(request)
    if result.error:
        print(f"Simulation failed: {result.error}")
        return 1

    summary = result.summary()
    risk = result.risk()
    print(f"\n{pathmod.MODEL_LABELS.get(args.model, args.model)}  "
          f"{result.n_done:,} paths x {args.horizon} steps in "
          f"{result.elapsed:.2f}s")
    print(f"  spot            {request.s0:,.2f}")
    print(f"  mean / median   {summary['mean']:,.2f} / {summary['median']:,.2f}")
    print(f"  5% / 95%        {summary['p5']:,.2f} / {summary['p95']:,.2f}")
    print(f"  P(up)           {summary['prob_up']*100:.1f}%")
    print(f"  P(>{request.target_price:,.2f})   "
          f"{summary.get('prob_above_target', float('nan'))*100:.1f}%")
    print(f"  E[max drawdown] {summary['expected_max_drawdown']*100:.1f}%")
    print(f"  VaR / CVaR 95%  {risk.get('var_95', float('nan'))*100:.1f}% / "
          f"{risk.get('cvar_95', float('nan'))*100:.1f}%")
    print(f"  Sharpe          {risk.get('sharpe', float('nan')):.3f}")
    print("\nMODELLING OUTPUT, NOT INVESTMENT ADVICE. Conditional on the "
          "model's assumptions.\n")
    cache.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.selftest:
        from .selftest import run_selftest
        return run_selftest(verbose=args.verbose, groups=args.selftest_group)

    if args.clear_cache:
        from .config import cache_path
        from .data import BarCache
        cache = BarCache(cache_path())
        before = cache.size_bytes()
        cache.clear()
        cache.close()
        print(f"Cache cleared ({before/1e6:.1f} MB) at {cache_path()}")
        return 0

    if args.headless:
        return _run_headless(args)

    try:
        from .ui.main_window import launch
    except ImportError as exc:
        print(f"Cannot start the GUI: {exc}\n\n"
              "PyQt6 is required for the terminal. Install it with:\n"
              "    pip install PyQt6\n\n"
              "The model suite works without it:\n"
              "    python -m quantmc --selftest\n"
              "    python -m quantmc --headless --ticker AAPL",
              file=sys.stderr)
        return 3

    from .config import AppConfig, cache_path
    from .data import BarCache, MarketData, default_provider

    cfg = AppConfig.load()
    if args.offline:
        cfg.offline = True
    cache = BarCache(cache_path())
    if args.allow_synthetic:
        cfg.allow_synthetic = True
    market = MarketData(
        provider=default_provider(), cache=cache,
        max_age_seconds=cfg.cache_max_age_minutes * 60.0,
        offline=cfg.offline, fallback_synthetic=cfg.allow_synthetic,
    )
    return launch(cfg, market, ticker=args.ticker)


if __name__ == "__main__":
    sys.exit(main())
