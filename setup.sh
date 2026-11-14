#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 -c 'import sys; assert sys.version_info >= (3, 10), "需要 Python 3.10+"'
test -d .venv || python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
printf '%s\n' '安装完成。编辑 .env 配置模型，然后运行 .venv/bin/python run.py'
