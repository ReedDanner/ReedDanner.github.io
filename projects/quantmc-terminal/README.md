# QuantMC — Monte Carlo & Quantitative Modelling Terminal

A dense, dark, keyboard-driven desktop terminal for Monte Carlo simulation,
derivatives pricing and return diagnostics on any ticker.

> **This is a modelling tool, not investment advice.** Every distribution,
> price, probability and risk number it produces is conditional on the
> assumptions of the model that generated it. Those assumptions are wrong in
> known ways: real returns have fat tails, clustered volatility, jumps and
> regime shifts that no single model captures at once. Calibrated parameters
> are estimates with standard errors — drift in particular is barely
> identifiable from any practical sample length. Nothing here forecasts the
> market.

---

## Install

```bash
pip install -r requirements.txt
```

Python 3.11+ (developed on 3.13). Only `numpy`, `pandas`, `scipy` and
`matplotlib` are needed for the model suite; `PyQt6` adds the GUI. Live data
needs only `requests` — the default provider talks to Yahoo's JSON endpoints
directly. `yfinance` is optional and used as a second-opinion fallback. The
model suite runs without `PyQt6`.

## Launch

```bash
python -m quantmc
```

| Command | What it does |
| --- | --- |
| `python -m quantmc` | Launch the terminal |
| `python -m quantmc --ticker NVDA` | Launch preloaded with a symbol |
| `python -m quantmc --offline` | Never touch the network; cached data only |
| `python -m quantmc --selftest` | Run the full model suite headlessly, exit non-zero on failure |
| `python -m quantmc --selftest --selftest-group pricing` | Run one group only |
| `python -m quantmc --headless --ticker AAPL --calibrate` | One simulation, printed summary, no GUI |
| `python -m quantmc --clear-cache` | Empty the local market-data cache |
| `python -m quantmc --allow-synthetic` | Permit generated fixture data when no real data can be had (**off by default**) |

On Windows, `run_terminal.pyw` is double-clickable and opens with no console
window; `selftest.bat` runs the suite.

### Keyboard

| Key | Action |
| --- | --- |
| `Ctrl+R` | Run simulation |
| `Esc` | Cancel the running simulation |
| `Ctrl+K` | Calibrate from history |
| `F5` | Reload data from the provider |
| `Ctrl+L` | Focus the ticker box |
| `Ctrl+1`…`Ctrl+6` | Jump to a chart tab |
| `Ctrl+S` / `Ctrl+E` | Export chart PNG / full run |

---

## File tree

```
QuantMonteCarlo/
├── README.md
├── requirements.txt
├── run_terminal.pyw            double-clickable launcher (no console)
├── selftest.bat                runs the headless suite
└── quantmc/
    ├── __init__.py             package docstring + disclaimer
    ├── __main__.py             CLI: --selftest, --headless, --offline, ...
    ├── config.py               persisted settings (JSON in the user app dir)
    ├── engine.py               batched, cancellable, streaming simulation runner
    ├── selftest.py             67-check correctness suite
    ├── data/
    │   ├── cache.py            SQLite cache: bars, quotes, option chains
    │   └── provider.py         DataProvider ABC, direct-Yahoo + yfinance +
    │                           synthetic backends, MarketData ladder
    ├── models/                 pure numpy/scipy — no GUI, no I/O
    │   ├── paths.py            the six path-generating model families
    │   ├── calibration.py      MLE / QMLE / method-of-moments estimators
    │   ├── pricing.py          BSM + Greeks, trees, MC, exotics, implied vol
    │   ├── stats.py            diagnostics, distribution fitting, ADF, HMM
    │   ├── technicals.py       SMA/EMA/Bollinger/RSI/MACD/ATR, vol cone
    │   ├── risk.py             VaR, CVaR, drawdown, Kelly, convergence
    │   └── multiasset.py       correlation, PSD repair, Cholesky basket MC
    └── ui/
        ├── theme.py            palette, Qt stylesheet, matplotlib defaults
        ├── charts.py           one canvas per tab
        ├── panels.py           collapsible sections, numeric fields, tables
        ├── workers.py          QThread adapters
        └── main_window.py      the terminal
```

**Layering rule:** nothing lower imports anything higher. `models/` has no GUI
and no I/O, so every function is importable and testable headlessly:

```python
from quantmc.models.paths import simulate_heston
import numpy as np
paths = simulate_heston(100.0, 252, 50_000, 1/252, np.random.default_rng(0),
                        mu=0.08, v0=0.04, kappa=3.0, theta=0.04, xi=0.5, rho=-0.7)
```

**Design choice — PyQt6 over Tkinter.** The engine streams a partial result
every batch; Tkinter's single-threaded event loop and lack of a native
worker-signal mechanism make that awkward and janky, and its widget set has no
real table or splitter. PyQt6 gives proper `QThread` + signal marshalling,
`QSplitter` layouts, styled tables, and a matplotlib backend that repaints
without flicker. The cost is a 78 MB wheel, which is why the GUI import is
deferred until after argument parsing — `--selftest` and `--headless` work
without Qt installed at all.

---

## The six path models

Selected in the left panel. All are drift-compensated to the **same** annualised
`mu`, so switching models changes the *shape* of the distribution, not its
expected value — which is what makes them comparable.

| Model | Captures | Misses |
| --- | --- | --- |
| **Geometric Brownian Motion** | The baseline. Exact at any step size. | Fat tails, clustering, jumps |
| **Student-t GBM** | Fat tails at every step, same total variance as GBM | Volatility clustering |
| **Merton jump diffusion** | Sudden gaps; negative skew from negative mean jumps | Crash *clustering* (jumps arrive independently) |
| **Heston stochastic vol** | Mean-reverting variance, leverage effect, vol smirk | Jumps; O(dt) Euler bias |
| **GARCH(1,1)** | Volatility clustering and mean reversion | Leverage asymmetry (use GJR/EGARCH) |
| **Historical bootstrap** | The real return distribution, exactly | *All* time dependence; can never draw an unprecedented day |
| **Block bootstrap** | Real distribution **and** dependence up to the block length | Dependence beyond the block |

### Parameter reference

Common to every model:

| Field | Meaning |
| --- | --- |
| `horizon (days)` | Steps to simulate. With `1d` bars, 252 ≈ one year |
| `paths` | Independent simulations. Error falls like 1/√n — quartering it costs 16× the paths |
| `seed` | Fixes the RNG. Same seed **and same batch size** reproduce exactly |
| `Antithetic variates` | Pairs each shock with its negation. Same distribution, lower estimator variance |
| `batch size` | Paths per batch. Smaller = smoother streaming and faster cancel; larger = marginally faster |
| `fan paths drawn` | Individual paths drawn behind the ribbons. Display only |

Model-specific (`mu` and `sigma` are always **annualised**, except GARCH):

| Model | Parameters |
| --- | --- |
| GBM | `mu` drift of dS/S · `sigma` volatility |
| Student-t | `+ nu` degrees of freedom. Must exceed 2 for finite variance; below 4 the kurtosis is infinite. Daily equity fits land at 3–5 |
| Merton | `sigma` *diffusive* vol excluding jumps · `lam` jumps per year · `jump_mean` mean log jump · `jump_std` its dispersion |
| Heston | `v0` initial variance · `kappa` reversion speed · `theta` long-run variance · `xi` vol of vol · `rho` price/vol correlation (negative for equities). Feller condition `2·kappa·theta > xi²` keeps variance positive — reported, not enforced |
| GARCH | **Per step, not annualised.** `omega` variance intercept · `alpha` shock loading · `beta` persistence. Needs `alpha+beta < 1`; long-run variance is `omega/(1−alpha−beta)` |
| Bootstrap | `recenter` 1 = impose `mu` on the historical shape, 0 = keep the historical drift |
| Block bootstrap | `+ block` length in steps. 10–40 days for daily equities; 1 degenerates to the iid bootstrap |

**Calibrate from history** estimates all of these from the last `calib. lookback`
bars and writes them into the fields. Estimator accuracy is *not* uniform, and
the app says so where it matters (see Known limitations).

### Probability targets

`target price` (P of finishing above), `barrier` + direction (P of touching at
any step), and `ruin level` as a percentage of spot. Leave a field at 0 to get
a sensible default relative to spot.

---

## Tabs

1. **Price & Technicals** — price with SMA/EMA/Bollinger, RSI and MACD panes,
   and the high-volatility HMM regime shaded in red behind the price.
2. **Monte Carlo Fan** — sample paths under 5/25/50/75/95 percentile ribbons,
   streaming as batches land.
3. **Distribution** — terminal-price histogram with a fitted lognormal, plus a
   convergence panel showing the running mean inside its ±2 standard-error
   envelope.
4. **Options / IV** — smile by expiry, ATM term structure, 3D implied-vol
   surface, and a full pricing table (BSM + Greeks, binomial/trinomial
   European and American, MC with its error against the closed form, and the
   chosen exotic payoff).
5. **Diagnostics** — returns, four volatility estimators, ACF, QQ plot, fitted
   densities and the realised-vol cone, alongside Jarque-Bera, ADF, Ljung-Box
   and an AIC/BIC ranking of four distribution families.
6. **Correlation** — correlation heatmap for a basket plus a Cholesky-driven
   correlated simulation of the equal-weight portfolio.

Every tab carries a collapsible **"About this tab"** strip along its bottom
edge — one dim row until clicked, explaining what the numbers mean and where
they mislead.

**Price estimate, risk** and **position-sizing** tables update live on the
right, and the top bar carries the headline estimate next to the live price.

### Price estimate

The `PRICE ESTIMATE` panel reports three different central numbers, because
they answer different questions and conflating them is the classic way to
misread a Monte Carlo:

| Number | Meaning |
| --- | --- |
| **Mean** | Probability-weighted average outcome, with its Monte Carlo standard error. Sits *above* the median for a right-skewed distribution |
| **Median** | The 50th percentile — half the paths finish above it. The honest "central" number to compare a price target against |
| **Mode** | Peak of the terminal density: the single most likely outcome. Lowest of the three |

Alongside them: 68% and 95% percentile bands, and the **forward**
`S₀·e^((r−q)T)` — the risk-neutral no-arbitrage price carrying no view.
`model vs forward` is the edge your drift assumption claims over it. That is
**not a signal**: it means the `mu` you entered exceeds the risk-free rate,
which is an assumption you supplied, not something the simulation discovered.

## Export

- **Save chart as PNG** — the visible tab.
- **Save tables as CSV** — every populated table, in one file with section
  headers.
- **Export full run** — timestamped CSV or JSON with every parameter and every
  summary statistic (`Ctrl+E`).

Settings persist to `settings.json`, and the market-data cache to
`market_cache.sqlite`, in your user app directory
(`%LOCALAPPDATA%\QuantMonteCarlo` on Windows).

---

## Self-test

```bash
python -m quantmc --selftest
```

67 checks, ~60 s, printing a pass/fail table and exiting non-zero on any
failure. Three kinds:

- **Analytic identities** to machine precision — put-call parity, Greeks
  against finite differences (worst relative error 3e-6), barrier in + out =
  vanilla (exact to 1e-8), drawdown on hand-built fixtures.
- **Statistical convergence** against closed forms, checked against the
  estimate's own standard error — MC vs Black-Scholes, GBM terminal moments vs
  the analytic lognormal, VaR vs the analytic quantile, barrier-touch
  probability vs the reflection principle.
- **Estimator round trips** — simulate with known parameters, calibrate,
  confirm they come back. Includes the HMM recovering known regime
  transitions, GARCH QMLE recovering α and β, and the ADF test hitting its
  nominal 5% size.

Also covered: engine reproducibility, prompt cancellation, bounded memory, the
100k × 252 performance target, cache upsert idempotence, graceful degradation
on a bad ticker, and config round-trip through a corrupt file.

---

## Performance

100,000 paths × 252 steps of GBM completes in **~0.8 s** (≈128k paths/s) on the
development machine, against the 2 s target. Heston, which must step
sequentially, takes ~1.2 s; Merton ~1.8 s.

Memory is independent of the path count. Each batch's `(batch, steps+1)` matrix
is reduced to four per-path vectors and discarded; only a fixed reservoir
(default 4,000 paths) is kept for the fan chart. A million-path run uses no
more memory than a hundred-thousand-path one.

Percentile ribbons are computed from that reservoir, not the full sample — an
unbiased subsample, since paths are iid. Terminal-price statistics, drawdowns
and barrier probabilities use **every** path.

---

## Known limitations

**Data**
- Yahoo returns **HTTP 429 "Too Many Requests" to any request without a browser
  User-Agent**, no matter how few you have made. It is an identity check
  reported as a rate limit. `YahooProvider` sends browser headers, so this does
  not occur; if you see a 429 now it is a genuine throttle and clears in
  seconds (the provider already retries with exponential backoff).
- `/v7/quote` and `/v7/options` additionally require Yahoo's cookie + "crumb"
  handshake or they answer 401. The provider fetches a crumb lazily and
  refreshes it automatically on a 401.
- Prices are dividend- and split-adjusted (every OHLC column scaled by
  `adjclose/close`). Right for return and volatility estimation, *not* the
  traded price, so strikes on a high-yield name will look slightly offset.
- Intraday intervals only cover a short recent window (~60 days for sub-hourly,
  ~2 years hourly). The request is clamped rather than erroring.
- **Synthetic data is off by default.** Silently substituting plausible-looking
  generated numbers for a real ticker is worse than an honest error, because
  nothing downstream can tell they are fake. Enable it explicitly with
  `--allow-synthetic`; when active the LED turns blue and the banner says
  `NO REAL DATA`.

**Models**
- Everything is single-name and single-factor. No stochastic rates, no
  correlation between the model and any macro driver.
- Heston uses Euler discretisation: O(dt) bias, small at daily steps, visible
  at weekly or coarser.
- Bootstrap models can never produce a day worse than the worst day in the
  sample. Their tails are bounded by history.
- Merton's jumps arrive independently, so crash clustering is not represented.
- GARCH(1,1) responds symmetrically to up and down shocks — no leverage term.

**Calibration** — accuracy is not uniform, and the app is explicit about it:
- **Drift is barely identifiable.** Its standard error depends on the calendar
  span, not the observation count: two years of daily data pins volatility down
  well and says almost nothing about `mu`. Override it with a view.
- **Heston `kappa` is biased high** (recovers ~4.7 from a true 3.0) and **`rho`
  is attenuated toward zero** (~−0.24 from a true −0.7). Both are
  errors-in-variables effects from using noisy realised variance as a
  regressor. `theta` is unbiased. Read `kappa` as an upper bound and assume the
  true leverage correlation is more negative than shown.
- Merton's threshold estimator misses sub-3σ jumps by construction, so `lam` is
  understated and the missed jumps are absorbed into `sigma`.
- All calibration is to the **physical** measure from history. A desk
  calibrating to the option surface gets materially different numbers, because
  the surface prices a variance risk premium history does not contain.

**Pricing**
- Exotics are **discretely monitored** on the step grid. Discretely monitored
  knock-outs are worth more than continuously monitored ones, and touch
  probabilities are biased low; the gap closes only like √dt. Raise the step
  count when a barrier sits near spot.
- Implied vol returns `nan` rather than a number when vega falls below 1e-8 —
  a deep-ITM short-dated option is worth intrinsic to forty decimal places, so
  no volatility is recoverable from its price. Above that floor, quotes invert
  to ~1e-12.
- Listed US single-stock options are American, but the IV solver is European,
  so early-exercise premium is misattributed to volatility. Small for OTM
  calls and short tenors, larger for deep ITM puts.
- American lattice values are exercisable only at the `n` tree dates, so they
  slightly understate the true continuously-exercisable value.

**Statistics**
- ADF uses fixed large-sample Dickey-Fuller critical values, not a MacKinnon
  p-value surface. Verified to have the correct 5% size and full power against
  `statsmodels`. A correctly sized test still calls one price series in twenty
  "stationary" by chance — one rejection is not evidence of mean reversion.
- Distribution fitting assumes iid draws from one fixed law, which volatility
  clustering violates. A fat-tailed unconditional fit may just be a mixture of
  calm and stressed Gaussian regimes — compare against the HMM and GARCH views
  before concluding the tails are structural.
- The HMM finds a *local* optimum. It is seeded deterministically so runs are
  reproducible, but the answer is not guaranteed global.
- Vol-cone percentiles come from heavily overlapping windows, so they are not
  independent observations and the cone's tails are less informative than the
  sample size suggests.

**Risk**
- The percentile ribbons are *pointwise*. The region between the 5th and 95th
  curves is **not** a 90% band for whole paths — the probability a path stays
  inside it for the entire horizon is far lower.
- Correlation is Gaussian: constant through time, no tail dependence. Real
  equity correlations rise toward 1 exactly when diversification is needed, so
  basket downside is understated.
- Kelly reports two numbers that are *not* meant to agree. The Gaussian one is
  the continuous-rebalancing limit; the empirical one is the optimum for
  holding this position over this horizon. They match at short horizons and
  diverge as the horizon grows (for a 12%-drift, 20%-vol asset: both ≈2.5 at a
  week, but ≈1.8 over a year). Size to the empirical figure — and full Kelly
  has brutal drawdowns and is extremely sensitive to an overstated edge, which
  is why half and quarter Kelly are shown next to it.
- Drawdowns and barrier touches are measured on the step grid only. Intra-step
  extremes are invisible, so a daily grid understates true continuous-time
  drawdown.
