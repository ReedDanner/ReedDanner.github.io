/* Portfolio data. Edited automatically by the tools in /tools.
   You can also hand-edit it - it is plain JSON inside window.PORTFOLIO. */
window.PORTFOLIO = {
  "profile": {
    "name": "Reed Danner",
    "monogram": "RD",
    "kicker": "Aspiring Investment Analyst",
    "status": "Building quant tools in public",
    "headline": {
      "lead": "The whole",
      "accent": "distribution."
    },
    "intro": "I build trading terminals, options analytics and Monte Carlo risk models - tools that show the full range of outcomes rather than a single number.",
    "focus": "Options analytics & risk simulation",
    "location": "",
    "email": "reed.danner@pm.me",
    "github": "https://github.com/ReedDanner",
    "linkedin": "https://www.linkedin.com/in/kenneth-d-5a4654353/"
  },
  "projects": [
    {
      "id": "quantmc-terminal",
      "title": "QuantMC - Monte Carlo Terminal",
      "summary": "Desktop terminal that prices options and stress-tests positions with Monte Carlo simulation.",
      "description": "A PyQt6 desktop terminal for Monte Carlo modelling of equity and options positions. It simulates price paths under configurable volatility and drift assumptions, prices derivatives off those paths, and reports the whole risk distribution - VaR, expected shortfall, and the full payoff profile - rather than a single point estimate.\n\nCalibration, multi-asset correlation, an implied-volatility surface and a caching data layer sit in separate modules, so the engine can be driven headlessly as well as from the interface. The package ships with a self-test suite of 67 checks that exercises the pipeline end to end.",
      "kind": "app",
      "tags": [
        "Python",
        "PyQt6",
        "Monte Carlo",
        "Options Pricing",
        "Risk"
      ],
      "date": "Aug 2026",
      "featured": true,
      "links": [],
      "cover": "projects/quantmc-terminal/screenshot-distribution.png",
      "images": [
        "projects/quantmc-terminal/screenshot-distribution.png",
        "projects/quantmc-terminal/screenshot-volatility-surface.png"
      ],
      "docs": [],
      "code": [
        {
          "path": "projects/quantmc-terminal/quantmc/__main__.py",
          "name": "__main__.py"
        },
        {
          "path": "projects/quantmc-terminal/README.md",
          "name": "README.md"
        },
        {
          "path": "projects/quantmc-terminal/requirements.txt",
          "name": "requirements.txt"
        },
        {
          "path": "projects/quantmc-terminal/run_terminal.pyw",
          "name": "run_terminal.pyw"
        },
        {
          "path": "projects/quantmc-terminal/selftest.bat",
          "name": "selftest.bat"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/selftest.py",
          "name": "selftest.py"
        }
      ],
      "downloads": [
        {
          "path": "projects/quantmc-terminal/quantmc/__init__.py",
          "name": "__init__.py",
          "size": "1.2 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/config.py",
          "name": "config.py",
          "size": "7.6 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/data/__init__.py",
          "name": "__init__.py",
          "size": "704 B"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/data/cache.py",
          "name": "cache.py",
          "size": "12.8 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/data/provider.py",
          "name": "provider.py",
          "size": "50.3 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/engine.py",
          "name": "engine.py",
          "size": "19.4 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/models/__init__.py",
          "name": "__init__.py",
          "size": "384 B"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/models/calibration.py",
          "name": "calibration.py",
          "size": "18.6 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/models/multiasset.py",
          "name": "multiasset.py",
          "size": "10.6 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/models/paths.py",
          "name": "paths.py",
          "size": "21.9 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/models/pricing.py",
          "name": "pricing.py",
          "size": "26.5 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/models/risk.py",
          "name": "risk.py",
          "size": "14.9 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/models/stats.py",
          "name": "stats.py",
          "size": "23.6 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/models/technicals.py",
          "name": "technicals.py",
          "size": "8.4 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/ui/__init__.py",
          "name": "__init__.py",
          "size": "74 B"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/ui/charts.py",
          "name": "charts.py",
          "size": "27.0 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/ui/main_window.py",
          "name": "main_window.py",
          "size": "77.9 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/ui/panels.py",
          "name": "panels.py",
          "size": "18.2 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/ui/theme.py",
          "name": "theme.py",
          "size": "10.9 KB"
        },
        {
          "path": "projects/quantmc-terminal/quantmc/ui/workers.py",
          "name": "workers.py",
          "size": "7.0 KB"
        }
      ],
      "demo": ""
    },
    {
      "id": "quantdesk-terminal",
      "title": "QuantDesk Terminal",
      "summary": "Single-file equity analytics workstation: technicals, risk, regime detection, forecasting and backtesting.",
      "description": "A desktop equity analytics workstation built as a single Python file. It pulls end-of-day data from MarketStack and layers technical, risk and regime analysis, adaptive forecasting, Monte Carlo simulation and strategy backtesting on top of it, including proper corporate-action handling so adjusted prices survive splits and dividends.\n\nThe repository also carries two companion tools: a statistical prediction system (Linear Regression, moving averages, ARIMA and GARCH combined into an ensemble) and the Marketstack-backed price predictor shown in the screenshot.",
      "kind": "app",
      "tags": [
        "Python",
        "MarketStack",
        "Backtesting",
        "ARIMA",
        "GARCH"
      ],
      "date": "Aug 2026",
      "featured": true,
      "links": [],
      "cover": "projects/quantdesk-terminal/screenshot-price-predictor.png",
      "images": [
        "projects/quantdesk-terminal/screenshot-price-predictor.png"
      ],
      "docs": [],
      "code": [
        {
          "path": "projects/quantdesk-terminal/README.md",
          "name": "README.md"
        },
        {
          "path": "projects/quantdesk-terminal/quantdesk_terminal.py",
          "name": "quantdesk_terminal.py"
        },
        {
          "path": "projects/quantdesk-terminal/stock2.py",
          "name": "stock2.py"
        },
        {
          "path": "projects/quantdesk-terminal/predict1.py",
          "name": "predict1.py"
        },
        {
          "path": "projects/quantdesk-terminal/requirements.txt",
          "name": "requirements.txt"
        }
      ],
      "downloads": [
        {
          "path": "projects/quantdesk-terminal/.gitignore",
          "name": ".gitignore",
          "size": "1.1 KB"
        },
        {
          "path": "projects/quantdesk-terminal/LICENSE",
          "name": "LICENSE",
          "size": "1.0 KB"
        }
      ],
      "demo": ""
    },
    {
      "id": "convexity-portfolio",
      "title": "The Convexity Portfolio",
      "summary": "A 163-page research framework on options, leverage and risk. Published as a redacted sample.",
      "description": "A rule-governed framework for combining long options and leveraged equity exposure into one portfolio: the mathematics of optimal leverage, position sizing, drawdown control, and an empirical validation section that backtests the rules against a century of real market history.\n\nThis copy is redacted. The structure, scale and section numbering are intact; every rule, parameter, table and chart is obscured. The working document stays private.",
      "kind": "document",
      "tags": [
        "Research",
        "Options",
        "Risk",
        "Portfolio Construction"
      ],
      "date": "Aug 2026",
      "featured": true,
      "links": [],
      "cover": "",
      "images": [],
      "docs": [
        "projects/convexity-portfolio/Convexity Portfolio (redacted).pdf"
      ],
      "code": [],
      "downloads": [],
      "demo": ""
    },
    {
      "id": "terminal-v3",
      "title": "Terminal V3",
      "summary": "Live-loop stock analytics terminal with a continuously updating Monte Carlo simulation.",
      "description": "An earlier single-file analytics terminal, built around a live loop: it keeps a Monte Carlo simulation running against streaming prices rather than recomputing on demand. The direct ancestor of the QuantMC terminal, kept here because the live-loop design is different enough to be worth reading on its own.",
      "kind": "app",
      "tags": [
        "Python",
        "Monte Carlo",
        "Analytics"
      ],
      "date": "Aug 2026",
      "featured": false,
      "links": [],
      "cover": "",
      "images": [],
      "docs": [],
      "code": [
        {
          "path": "projects/terminal-v3/TerminalV3.py",
          "name": "TerminalV3.py"
        }
      ],
      "downloads": [],
      "demo": ""
    },
    {
      "id": "options-calculator",
      "title": "Professional Options Calculator",
      "summary": "Black-Scholes pricing with the full Greeks suite, probability analysis and payoff diagrams.",
      "description": "A standalone options calculator: Black-Scholes pricing, the complete Greeks suite, probability-of-profit analysis, payoff diagrams and probability distribution curves for a given contract.",
      "kind": "algorithm",
      "tags": [
        "Python",
        "Black-Scholes",
        "Greeks",
        "Options"
      ],
      "date": "Aug 2026",
      "featured": false,
      "links": [],
      "cover": "",
      "images": [],
      "docs": [],
      "code": [
        {
          "path": "projects/options-calculator/optionCalc.py",
          "name": "optionCalc.py"
        }
      ],
      "downloads": [],
      "demo": ""
    },
    {
      "id": "capital-decision-dashboard",
      "title": "Capital Decision Dashboard",
      "summary": "A personal financial decision assistant built with CustomTkinter.",
      "description": "A desktop dashboard for personal capital decisions - laying out the trade-offs behind an allocation choice rather than just reporting balances. Built with CustomTkinter.",
      "kind": "app",
      "tags": [
        "Python",
        "CustomTkinter",
        "Personal Finance"
      ],
      "date": "Aug 2026",
      "featured": false,
      "links": [],
      "cover": "",
      "images": [],
      "docs": [],
      "code": [
        {
          "path": "projects/capital-decision-dashboard/capitalDash.py",
          "name": "capitalDash.py"
        }
      ],
      "downloads": [],
      "demo": ""
    },
    {
      "id": "apex-terminal",
      "title": "Apex Terminal",
      "summary": "A browser-based investment terminal built as a single self-contained HTML file.",
      "description": "A master investment platform that runs entirely in the browser - charts, screens and analysis panels - with no build step and no dependencies, written as one self-contained HTML file.",
      "kind": "website",
      "tags": [
        "HTML",
        "CSS",
        "JavaScript",
        "Dashboard"
      ],
      "date": "Aug 2026",
      "featured": false,
      "links": [],
      "cover": "",
      "images": [],
      "docs": [],
      "code": [
        {
          "path": "projects/apex-terminal/index.html",
          "name": "index.html"
        }
      ],
      "downloads": [],
      "demo": "projects/apex-terminal/index.html"
    },
    {
      "id": "master-terminal",
      "title": "Master Terminal",
      "summary": "A finance and investment command centre covering fundamentals, in one HTML file.",
      "description": "A browser command centre for finance fundamentals and investment analysis, organised as a set of panels. Another single-file build - the whole application is one HTML document.",
      "kind": "website",
      "tags": [
        "HTML",
        "CSS",
        "JavaScript",
        "Dashboard"
      ],
      "date": "Aug 2026",
      "featured": false,
      "links": [],
      "cover": "",
      "images": [],
      "docs": [],
      "code": [
        {
          "path": "projects/master-terminal/index.html",
          "name": "index.html"
        }
      ],
      "downloads": [],
      "demo": "projects/master-terminal/index.html"
    },
    {
      "id": "citadis-holdings",
      "title": "Citadis Holdings",
      "summary": "Front-end for an institutional investment analysis firm.",
      "description": "A site for an institutional investment analysis practice: positioning, the analysis offering and the investment case, built as a single self-contained HTML file.",
      "kind": "website",
      "tags": [
        "HTML",
        "CSS",
        "JavaScript",
        "Web Design"
      ],
      "date": "Aug 2026",
      "featured": false,
      "links": [],
      "cover": "",
      "images": [],
      "docs": [],
      "code": [
        {
          "path": "projects/citadis-holdings/index.html",
          "name": "index.html"
        }
      ],
      "downloads": [],
      "demo": "projects/citadis-holdings/index.html"
    },
    {
      "id": "verdant-apex-capital",
      "title": "Verdant Apex Capital",
      "summary": "A ten-page front-end for an AI-driven wealth management service, with auth and a Supabase backend.",
      "description": "A full multi-page site for a wealth management product: landing page, solutions, research tiers, pricing, client area, portfolio and model pages, and a contact route. Wired to Supabase for authentication and data, with the client keys left as placeholders.",
      "kind": "website",
      "tags": [
        "HTML",
        "CSS",
        "JavaScript",
        "Supabase",
        "Web Design"
      ],
      "date": "Aug 2026",
      "featured": false,
      "links": [],
      "cover": "",
      "images": [],
      "docs": [],
      "code": [
        {
          "path": "projects/verdant-apex-capital/index.html",
          "name": "index.html"
        },
        {
          "path": "projects/verdant-apex-capital/script.js",
          "name": "script.js"
        },
        {
          "path": "projects/verdant-apex-capital/styles.css",
          "name": "styles.css"
        },
        {
          "path": "projects/verdant-apex-capital/solutions.html",
          "name": "solutions.html"
        },
        {
          "path": "projects/verdant-apex-capital/clients.html",
          "name": "clients.html"
        },
        {
          "path": "projects/verdant-apex-capital/model.html",
          "name": "model.html"
        }
      ],
      "downloads": [
        {
          "path": "projects/verdant-apex-capital/auth.html",
          "name": "auth.html",
          "size": "3.0 KB"
        },
        {
          "path": "projects/verdant-apex-capital/contact.html",
          "name": "contact.html",
          "size": "4.9 KB"
        },
        {
          "path": "projects/verdant-apex-capital/portfolio.html",
          "name": "portfolio.html",
          "size": "5.9 KB"
        },
        {
          "path": "projects/verdant-apex-capital/pricing.html",
          "name": "pricing.html",
          "size": "4.4 KB"
        },
        {
          "path": "projects/verdant-apex-capital/research-pro.html",
          "name": "research-pro.html",
          "size": "3.7 KB"
        },
        {
          "path": "projects/verdant-apex-capital/research.html",
          "name": "research.html",
          "size": "3.5 KB"
        },
        {
          "path": "projects/verdant-apex-capital/supabaseClient.js",
          "name": "supabaseClient.js",
          "size": "320 B"
        }
      ],
      "demo": "projects/verdant-apex-capital/index.html"
    },
    {
      "id": "investpro-elite",
      "title": "InvestPro Elite",
      "summary": "Marketing and stock-pick front-end for a subscription research service.",
      "description": "A subscription research service front-end: landing page, pricing tiers and a stock-picks board, each with its own stylesheet and script. Built to test how the same offer reads across different page layouts.",
      "kind": "website",
      "tags": [
        "HTML",
        "CSS",
        "JavaScript",
        "Web Design"
      ],
      "date": "Aug 2026",
      "featured": false,
      "links": [],
      "cover": "",
      "images": [],
      "docs": [],
      "code": [
        {
          "path": "projects/investpro-elite/main.js",
          "name": "main.js"
        },
        {
          "path": "projects/investpro-elite/index.html",
          "name": "index.html"
        },
        {
          "path": "projects/investpro-elite/stock-picks.html",
          "name": "stock-picks.html"
        },
        {
          "path": "projects/investpro-elite/style.css",
          "name": "style.css"
        },
        {
          "path": "projects/investpro-elite/pricing.html",
          "name": "pricing.html"
        },
        {
          "path": "projects/investpro-elite/stock-picks.js",
          "name": "stock-picks.js"
        }
      ],
      "downloads": [
        {
          "path": "projects/investpro-elite/pricing.js",
          "name": "pricing.js",
          "size": "9.1 KB"
        },
        {
          "path": "projects/investpro-elite/stock-picks.css",
          "name": "stock-picks.css",
          "size": "14.6 KB"
        }
      ],
      "demo": "projects/investpro-elite/index.html"
    }
  ],
  "approach": {
    "lead": "Make it",
    "accent": "reproducible.",
    "statement": "A model is only worth something if you can rerun it, question it, and see where it breaks. I put as much care into the tooling around the maths as into the maths itself.",
    "points": [
      {
        "title": "Start from the data",
        "body": "Cache it, validate it, and know exactly which call produced each number."
      },
      {
        "title": "Simulate, do not guess",
        "body": "A point estimate hides the risk. Ten thousand paths show you its shape."
      },
      {
        "title": "Finish it as a tool",
        "body": "A model nobody can run is a note. I ship applications, with self-tests that prove they still work."
      }
    ]
  },
  "toolkit": [
    "Python",
    "NumPy",
    "pandas",
    "SciPy",
    "PyQt6",
    "Monte Carlo",
    "Black-Scholes",
    "Options Greeks",
    "Volatility Surfaces",
    "Matplotlib",
    "SQLite",
    "JavaScript",
    "HTML / CSS",
    "Git"
  ]
};
