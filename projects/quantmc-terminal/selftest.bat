@echo off
REM Run the headless model suite. Exits non-zero if any check fails.
python -m quantmc --selftest %*
