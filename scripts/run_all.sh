#!/usr/bin/env bash
# 依序執行三個測試。需要先 export GEMINI_API_KEY=...
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "缺少 GEMINI_API_KEY 環境變數" >&2
  exit 1
fi

echo "### 1/3 Decisions API（gemini-decision-1）"
python3 scripts/decisions_test.py

echo
echo "### 2/3 Argon 盲測（gemini-4-argon）"
python3 scripts/argon_test.py

echo
echo "### 3/3 低成本模型對照（flash / flash-lite）"
python3 scripts/flash_test.py

echo
echo "全部完成，結果在 out/"
