#!/usr/bin/env bash
set -e

pip install --upgrade pip
pip install -r requirements.txt

PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install chromium
