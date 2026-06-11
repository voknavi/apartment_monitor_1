@echo off
chcp 65001 >nul 2>&1
echo.
echo  Apartment Monitor (Playwright edition)
echo  ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Install from https://python.org  ^(check "Add Python to PATH"^)
    pause
    exit /b 1
)

echo [1/3] Installing Python packages...
python -m pip install requests playwright --quiet --no-warn-script-location

echo [2/3] Installing Chromium browser for Playwright...
python -m playwright install chromium --with-deps

echo [3/3] Starting monitor...  ^(Ctrl+C to stop^)
echo.
python monitor.py
pause
