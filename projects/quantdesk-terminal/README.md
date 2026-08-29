# QuantDesk Terminal

A desktop equity analytics workstation in a single Python file. Pulls
end-of-day data from [MarketStack](https://marketstack.com) and provides
technical, risk and regime analysis, adaptive forecasting, Monte Carlo
simulation and strategy backtesting.

Not investment advice.

---

## Features

- **Corporate-action handling** — resolves adjusted prices from the API's
  `adj_close`, falling back to the `/splits` event calendar, then the per-bar
  `split_factor`, then a strict jump heuristic. Reports which method was used.
- **Risk analytics** — annualised volatility, Sharpe, Sortino, Calmar, Omega,
  max drawdown with recovery dates, historical and Cornish-Fisher VaR, CVaR,
  skew and kurtosis.
- **Benchmark statistics** — beta, correlation, alpha, tracking error,
  information ratio and up/down capture, all computed on returns joined by
  date rather than by position.
- **Regime detection** — volatility percentile, Hurst exponent, variance
  ratio, return autocorrelation, rolling beta.
- **Forecasting** — 1/3/6/12-month horizons with P10/P50/P90 bands. A
  walk-forward ML ensemble runs only where the sample can validate it, with an
  embargo between train and test folds; otherwise the estimate comes from
  simulation and is labelled as such. Horizons longer than the loaded history
  are reported as unsupported rather than guessed.
- **Monte Carlo** — animated simulation with a percentile fan and terminal
  price distribution. GBM, IID bootstrap, stationary block bootstrap and
  Student-t models.
- **Backtesting** — SMA/EMA crossover, MACD, RSI mean-reversion, Donchian
  breakout and buy-and-hold, with transaction costs and a one-bar trade lag so
  no future information is used.
- **Request caching** — responses are cached on disk and requests are
  throttled and retried, which matters on rate-limited API tiers. Switching
  the date range re-slices cached history and makes no new requests.
- **Optional AI company review** — sends the pulled reference data to an LLM,
  which returns strengths, risks, watch items and explicit data gaps.

## Requirements

- Python 3.9 or newer
- A free [MarketStack](https://marketstack.com) API key
- An OpenAI API key (optional, for the COMPANY tab only)

`tkinter` is required and ships with Python. If it is missing:

| Platform | Fix |
|---|---|
| Windows / macOS | Re-run the python.org installer, enable "tcl/tk and IDLE" |
| Debian / Ubuntu | `sudo apt install python3-tk` |
| Fedora | `sudo dnf install python3-tkinter` |

## Install

```bash
git clone https://github.com/ReedDanner/quantdesk-terminal.git
cd quantdesk-terminal
python -m pip install -r requirements.txt
```

Optional, for the COMPANY tab:

```bash
python -m pip install openai
```

## Configure

The MarketStack key is read from the environment.

macOS / Linux:

```bash
export MARKETSTACK_API_KEY="your_key_here"
```

Windows PowerShell, current session only:

```bash
$env:MARKETSTACK_API_KEY = "your_key_here"
```

Windows, saved permanently (open a new terminal afterwards):

```bash
setx MARKETSTACK_API_KEY "your_key_here"
```

`OPENAI_API_KEY` is set the same way and is only needed for the COMPANY tab.
Every other tab works without it.

Keys are never written to disk or included in logs, error messages or exports.

## Run

```bash
python quantdesk_terminal.py
```

Then enter a ticker and press **FETCH**, followed by **ANALYZE**.

| Shortcut | Action |
|---|---|
| `Enter` (in ticker box) | Fetch |
| `F5` | Fetch |
| `Ctrl+R` | Analyze |
| `Ctrl+E` | Export report |

## Verify the install

```bash
python quantdesk_terminal.py --selftest
```

Runs about 68 checks against live data covering the data layer, indicators,
risk statistics, forecasting, backtests and corporate-action handling. No
window is opened and cached responses are used, so it costs little or no API
quota. It ends with `N passed, N failed`.

Other options:

```bash
python quantdesk_terminal.py --selftest --symbol MSFT --benchmark QQQ
python quantdesk_terminal.py --clear-cache
python quantdesk_terminal.py --help
```

## Tabs

| Tab | Contents |
|---|---|
| OVERVIEW | Price, volume and drawdown charts, trailing returns, headline metrics |
| TECH | Bollinger bands, moving averages, RSI, MACD, ADX, stochastic, OBV |
| RISK | Underwater curve, return distribution, rolling volatility, VaR/CVaR |
| REGIME | Volatility percentile, Hurst, variance ratio, autocorrelation, rolling beta |
| SEASON | Weekday and month effects, with thin samples marked |
| FORECAST | Horizon bands, model choice and validation metrics |
| MONTE | Animated Monte Carlo with percentile fan and terminal distribution |
| BACKTEST | Strategy equity curve versus buy-and-hold |
| COMPANY | Pulled reference data, optionally reviewed by an LLM |
| DATA | Every bar, adjusted and raw, exportable to CSV |
| LOG | API calls, warnings and errors |

## A note on API plan limits

Free and lower-tier MarketStack plans cap history at roughly one year per
symbol regardless of the requested date range, and rate limit after a small
number of rapid requests.

The app handles this rather than hiding it:

- Horizons longer than the loaded history are reported as **UNSUPPORTED**
  instead of producing a number the data cannot support.
- Shorter samples fall back to simulation and say so.
- Thin seasonality buckets are marked and drawn hollow.
- Responses are cached, requests are throttled and retried with backoff, and
  the whole watchlist refreshes in a single request.

## Files and storage

Settings and cache live outside the repository:

```
Windows   %LOCALAPPDATA%\QuantDeskTerminal\
macOS     ~/QuantDeskTerminal/
Linux     ~/QuantDeskTerminal/
```

Delete `config.json` there to reset settings. Use the "Clear cache" button or
`--clear-cache` to force fresh downloads.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `MARKETSTACK_API_KEY is not set` | Key not exported, or terminal not reopened after `setx` |
| Rate limit reached / HTTP 429 | Too many rapid requests. Wait a minute; cached symbols still work |
| `No end-of-day data returned` | Unrecognised symbol, or an exchange not covered by your plan |
| `No module named 'customtkinter'` | Run the install step |
| `No module named 'tkinter'` | See the Requirements table |
| COMPANY tab returns `INSUFFICIENT DATA` | Expected. MarketStack does not supply revenue, margins or multiples; paste them into the box on that tab |

The LOG tab records every API call, warning and error.

## Limitations

- Forecasts are statistical extrapolations of past prices and know nothing
  about the underlying business.
- Backtest results come from one symbol over one window and are not evidence
  of an edge. Costs and slippage are modelled only roughly.
- Where a model validates below random, the app prints a warning and scores
  its confidence near zero rather than presenting the number as usable.

## License

MIT. See [LICENSE](LICENSE).
