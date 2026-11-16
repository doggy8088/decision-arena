#!/usr/bin/env python3
"""Gemini Decisions API（gemini-decision-1）辨音能力測試。

測試設計：每段音檔送一次請求，問兩個獨立的題目
  1. noul   ：是否為 ㄌㄨˊ（lu，二聲）
  2. choice ：四選一（lu2 / lü2 / lü3 / other），回傳各選項機率

用法：
  export GEMINI_API_KEY=...
  python3 scripts/decisions_test.py

輸出：終端機表格 + out/decisions-result.json
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ROOT, decide, fmt_probs, load_clips, save  # noqa: E402

MODEL = "gemini-decision-1"

QUESTIONS = {
    "is_lu2": {
        "type": "noul",
        "instructions": "Is the spoken Mandarin syllable ㄌㄨˊ (lu, second tone)?",
    },
    "which": {
        "type": "choice",
        "instructions": "Which Mandarin syllable is spoken?",
        "criteria": {
            "lu2": "ㄌㄨˊ / lu, second tone",
            "lv2": "ㄌㄩˊ / lü, second tone",
            "lv3": "ㄌㄩˇ / lü, third tone",
            "other": "any other syllable",
        },
    },
}


def main() -> None:
    clips = load_clips()
    rows = []

    print(f"model={MODEL}  clips={len(clips)}")
    header = f"{'clip':12s} {'category':9s} {'expect_lu2':10s} {'P(lu2)':>7s}  {'top':8s}  probs"
    print(header)
    print("-" * len(header))

    for clip in clips:
        audio = ROOT / clip["file"]
        result = decide(audio, QUESTIONS)
        answers = result["answers"]
        p_lu2 = answers["is_lu2"]["noul"]
        top_answer = answers["which"]
        probs = top_answer.get("probabilities", {}) or {}
        top = max(probs, key=probs.get) if probs else "-"

        rows.append(
            {
                "id": clip["id"],
                "category": clip["category"],
                "verdict": clip["verdict"],
                "expect_lu2": clip["expect_lu2"],
                "p_lu2": p_lu2,
                "choice_top": top,
                "choice_probs": probs,
                "usage": result.get("usage", {}),
            }
        )

        print(
            f"{clip['id']:12s} {clip['category']:9s} "
            f"{('YES' if clip['expect_lu2'] else 'no'):10s} {p_lu2:7.3f}  {top:8s}  {fmt_probs(probs)}"
        )

    positives = [r["p_lu2"] for r in rows if r["expect_lu2"]]
    negatives = [r["p_lu2"] for r in rows if not r["expect_lu2"]]
    hit = sum(1 for r in rows if r["expect_lu2"] and r["choice_top"] == "lu2")

    print("\n=== 摘要 ===")
    print(f"應為 lu2 的檔案數：{len(positives)}，P(lu2) 平均 {sum(positives)/len(positives):.3f}")
    print(f"其餘檔案數：{len(negatives)}，P(lu2) 平均 {sum(negatives)/len(negatives):.3f}")
    print(f"choice 選對 lu2 的比例：{hit}/{len(positives)}")
    if positives and negatives:
        print(
            f"分離度：min(P|正)= {min(positives):.3f} vs max(P|負)= {max(negatives):.3f}"
            f" → {'可完全分離' if min(positives) > max(negatives) else '無法完全分離'}"
        )

    path = save(
        "decisions-result.json",
        {"model": MODEL, "questions": QUESTIONS, "rows": rows},
    )
    print(f"\n結果已寫入 {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
