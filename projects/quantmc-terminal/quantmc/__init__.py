"""
QuantMC -- Monte Carlo and quantitative modelling terminal.

Layering (nothing lower ever imports anything higher):

    quantmc.models    pure numpy/scipy maths -- path models, calibration,
                      pricing, statistics, risk, technicals, multi-asset
    quantmc.data      provider interface, yfinance + synthetic backends,
                      SQLite cache
    quantmc.engine    batched, cancellable, streaming simulation runner
    quantmc.config    persisted user settings
    quantmc.ui        PyQt6 terminal (imported lazily -- the rest of the
                      package works with no GUI toolkit installed)

DISCLAIMER
----------
This is a MODELLING TOOL, NOT INVESTMENT ADVICE.  Every distribution, price,
probability and risk number it produces is conditional on the assumptions of
the model that generated it.  Those assumptions are wrong in known ways: real
returns have fat tails, clustered volatility, jumps and regime shifts that no
single model captures at once.  Calibrated parameters are estimates with
standard errors, and drift in particular is barely identifiable from any
practical sample length.  Nothing here forecasts the market.
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
