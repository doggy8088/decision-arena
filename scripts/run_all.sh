#!/usr/bin/env bash
# 依序執行全部測試。需要先 export GEMINI_API_KEY=...
#
#   ./scripts/run_all.sh            # 研究一（單音節）＋研究二（音場）＋研究三（發音）
#   ./scripts/run_all.sh --fast     # 只跑研究二、三，且減少重複次數
#
# 選用：export GROQ_API_KEY=...  才能做片段標註的獨立驗證
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "缺少 GEMINI_API_KEY 環境變數" >&2
  exit 1
fi

FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1

echo "### 1/5 研究一：單音節辨音（Decisions vs Argon）"
python3 scripts/decisions_test.py
python3 scripts/argon_test.py
python3 scripts/flash_test.py

echo
echo "### 2/5 研究二：下載 YouTube 片段（已存在會跳過）"
python3 scripts/fetch_scenes.py --jobs 5

if [[ -n "${GROQ_API_KEY:-}" ]]; then
  echo
  echo "### 3/5 片段標註的獨立驗證（Groq Whisper）"
  python3 scripts/validate_clips.py
fi

echo
echo "### 4/5 研究二：音場分類（Decisions vs Argon）"
if [[ $FAST -eq 1 ]]; then
  python3 scripts/scene_bench.py --decisions-runs 1 --argon-runs 1
else
  python3 scripts/scene_bench.py --decisions-runs 2 --argon-runs 3
fi

echo
echo "### 5/5 研究三：發音判斷基準（TTS 語料）"
python3 scripts/build_pron_corpus.py
if [[ $FAST -eq 1 ]]; then
  python3 scripts/pron_baseline.py --limit 12
else
  python3 scripts/pron_baseline.py
fi

echo
echo "全部完成，結果在 out/"
echo "發音練習 Web App：python3 app/server.py --port 8899"
