#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then sh setup.sh; fi
printf '%s\n' '请在浏览器打开 http://127.0.0.1:8765；按 Ctrl+C 停止。'
exec .venv/bin/python run.py
