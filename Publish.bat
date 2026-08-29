@echo off
title Publish portfolio
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set "PYEXE="
python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYEXE=python"
if not defined PYEXE (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYEXE=py -3"
)
if not defined PYEXE (
  python3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYEXE=python3"
)
if not defined PYEXE goto nopython
%PYEXE% "tools\publish.py"
exit /b

:nopython
echo.
echo   Python is not installed, or Windows cannot find a working copy.
echo   Get it from https://www.python.org/downloads/
echo   During install, tick "Add python.exe to PATH".
echo.
pause
exit /b 1
