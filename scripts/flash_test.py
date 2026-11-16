#!/usr/bin/env python3
"""低成本模型對照測試：gemini-3.8-flash 與 gemini-3.1-flash-lite。

目的：確認便宜模型是否也能辨識單音節與聲調，作為「全量自動驗收」的候選。

第一階段：注音格式提示，跑 5 段（含新舊 lu2）
第二階段：拼音＋NONE 提示，跑靜音／噪音與新舊 lu2，檢驗是否會幻聽

用法：
  export GEMINI_API_KEY=...
  python3 scripts/flash_test.py
  python3 scripts/flash_test.py --model gemini-3.8-flash

輸出：終端機表格 + out/flash-result.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ROOT, generate, load_clips, save  # noqa: E402

DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]

BOPOMOFO_PROMPT = (
    "這是台灣華語的單音節錄音。請只輸出你聽到的音節，"
    "格式：注音|漢語拼音|聲調（1-4，5 為輕聲）。不要解釋、不要加其他文字。"
)
PINYIN_PROMPT = (
    "只輸出你聽到的單音節漢語拼音＋聲調數字（例如 lu2）。若不確定或沒有語音，只輸出 NONE。"
)

PHASE1_IDS = ["ma", "ma3", "old_M_lu2", "new_M_lu2", "new_F_lu2"]
PHASE2_IDS = ["silence", "noise", "old_M_lu2", "new_M_lu2"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", help="可重複指定；預設跑兩個模型")
    args = parser.parse_args()
    models = args.model or DEFAULT_MODELS

    clips = {c["id"]: c for c in load_clips()}
    rows = []

    for model in models:
        print(f"\n=== {model} ===")
        print("-- 第一階段：注音格式（盲測）--")
        for clip_id in PHASE1_IDS:
            clip = clips[clip_id]
            output = generate(model, BOPOMOFO_PROMPT, ROOT / clip["file"])
            rows.append(
                {
                    "model": model,
                    "phase": "bopomofo",
                    "id": clip_id,
                    "expect": clip["zhuyin"],
                    "verdict": clip["verdict"],
                    "output": output,
                }
            )
            print(f"  {clip_id:12s} 期望={clip['zhuyin']:10s} 模型={output}")

        print("-- 第二階段：拼音＋NONE（含負向控制）--")
        for clip_id in PHASE2_IDS:
            clip = clips[clip_id]
            output = generate(model, PINYIN_PROMPT, ROOT / clip["file"])
            expect = clip["pinyin"] or "NONE"
            rows.append(
                {
                    "model": model,
                    "phase": "pinyin",
                    "id": clip_id,
                    "expect": expect,
                    "verdict": clip["verdict"],
                    "output": output,
                }
            )
            print(f"  {clip_id:12s} 期望={expect:10s} 模型={output}")

    path = save("flash-result.json", {"models": models, "rows": rows})
    print(f"\n結果已寫入 {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
