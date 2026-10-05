#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# 仓库里可能残留其它平台构建的 .venv（解释器软链指向不存在的路径）；不可用时重建
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
  echo "检测到 .venv 缺失或不可用，重新创建虚拟环境…"
  rm -rf .venv
  python3 -m venv .venv
fi

.venv/bin/pip install -q -r requirements.txt
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
