#!/bin/bash
echo "Apartment Monitor (Playwright edition)"
echo "======================================="
echo ""
echo "[1/3] Installing Python packages..."
pip3 install requests playwright --quiet --break-system-packages 2>/dev/null || pip install requests playwright --quiet

echo "[2/3] Installing Chromium..."
python3 -m playwright install chromium --with-deps

echo "[3/3] Starting monitor... (Ctrl+C to stop)"
echo ""
python3 monitor.py
