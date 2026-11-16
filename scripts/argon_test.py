#!/usr/bin/env python3
"""gemini-4-argon 盲測：只給音檔，要求模型寫出聽到的音節。

作為 Decisions API 的對照組（baseline）。不使用任何提示洩漏答案。

用法：
  export GEMINI_API_KEY=...
  python3 scripts/argon_test.py

輸出：終端機表格 + out/argon-result.json
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ROOT, generate, load_clips, save  # noqa: E402

MODEL = "gemini-4-argon"
THINKING = "low"

PROMPT = (
    "這是台灣華語的單音節錄音。請只輸出你聽到的音節，"
    "格式：注音|漢語拼音|聲調（1-4，5 為輕聲）。不要解釋、不要加其他文字。"
)

BOPOMOFO_TONE = {"ˊ": 2, "ˇ": 3, "ˋ": 4, "˙": 5}
PINYIN_TONE_MAP = {
    "ā": ("a", 1), "á": ("a", 2), "ǎ": ("a", 3), "à": ("a", 4),
    "ē": ("e", 1), "é": ("e", 2), "ě": ("e", 3), "è": ("e", 4),
    "ī": ("i", 1), "í": ("i", 2), "ǐ": ("i", 3), "ì": ("i", 4),
    "ō": ("o", 1), "ó": ("o", 2), "ǒ": ("o", 3), "ò": ("o", 4),
    "ū": ("u", 1), "ú": ("u", 2), "ǔ": ("u", 3), "ù": ("u", 4),
    "ǖ": ("ü", 1), "ǘ": ("ü", 2), "ǚ": ("ü", 3), "ǜ": ("ü", 4),
}


def strip_bopomofo_tone(text: str) -> tuple[str, int | None]:
    tone = None
    base = []
    for ch in text:
        if ch in BOPOMOFO_TONE:
            tone = BOPOMOFO_TONE[ch]
        else:
            base.append(ch)
    return "".join(base).strip(), tone


def strip_pinyin(text: str) -> tuple[str, int | None]:
    tone = None
    out = []
    for ch in unicodedata.normalize("NFC", text.strip().lower()):
        if ch in PINYIN_TONE_MAP:
            base, t = PINYIN_TONE_MAP[ch]
            out.append(base)
            tone = t
        else:
            out.append(ch)
    joined = "".join(out)
    digits = [c for c in joined if c.isdigit()]
    if digits:
        tone = int(digits[0])
        joined = "".join(c for c in joined if not c.isdigit())
    return joined.replace("v", "ü"), tone


def parse(output: str) -> dict:
    fields = [f.strip() for f in output.replace("｜", "|").split("|")]
    zhuyin = fields[0] if fields else ""
    pinyin = fields[1] if len(fields) > 1 else ""
    tone_field = fields[2] if len(fields) > 2 else ""

    z_base, z_tone = strip_bopomofo_tone(zhuyin)
    p_base, p_tone = strip_pinyin(pinyin)

    tone = None
    if tone_field[:1].isdigit():
        tone = int(tone_field[0])
    elif z_tone:
        tone = z_tone
    elif p_tone:
        tone = p_tone

    return {"zhuyin": z_base, "pinyin": p_base, "tone": tone, "raw": output}


def main() -> None:
    clips = [c for c in load_clips() if c["category"] in ("control", "target")]
    rows = []

    print(f"model={MODEL}  clips={len(clips)}")
    header = f"{'clip':12s} {'expect':10s} {'model_output':22s} {'syllable':9s} {'tone':5s}"
    print(header)
    print("-" * len(header))

    for clip in clips:
        expected_zhuyin, zhuyin_tone = strip_bopomofo_tone(clip["zhuyin"])
        expected_pinyin, pinyin_tone = strip_pinyin(clip["pinyin"])
        # 一聲在注音沒有調號，必須回退到拼音的數字（ma1 → 1）
        expected_tone = zhuyin_tone if zhuyin_tone is not None else pinyin_tone
        output = generate(MODEL, PROMPT, ROOT / clip["file"], thinking=THINKING)
        parsed = parse(output)

        syllable_ok = (
            parsed["zhuyin"] == expected_zhuyin and parsed["pinyin"] == expected_pinyin
        )
        tone_ok = parsed["tone"] == expected_tone

        rows.append(
            {
                "id": clip["id"],
                "category": clip["category"],
                "verdict": clip["verdict"],
                "expect_zhuyin": clip["zhuyin"],
                "expect_pinyin": clip["pinyin"],
                "raw": parsed["raw"],
                "parsed": {"zhuyin": parsed["zhuyin"], "pinyin": parsed["pinyin"], "tone": parsed["tone"]},
                "syllable_match": syllable_ok,
                "tone_match": tone_ok,
            }
        )

        print(
            f"{clip['id']:12s} {clip['zhuyin']:10s} {output[:22]:22s} "
            f"{'OK' if syllable_ok else 'DIFF':9s} {('OK' if tone_ok else 'DIFF'):5s}"
        )

    total = len(rows)
    syl = sum(1 for r in rows if r["syllable_match"])
    tone = sum(1 for r in rows if r["tone_match"])
    both = sum(1 for r in rows if r["syllable_match"] and r["tone_match"])

    print("\n=== 摘要 ===")
    print(f"音節（注音＋拼音）相符：{syl}/{total}")
    print(f"聲調相符：{tone}/{total}")
    print(f"音節與聲調都相符：{both}/{total}")

    defective = [r for r in rows if r["verdict"] == "defective-audio"]
    caught = [r for r in defective if not (r["syllable_match"] and r["tone_match"])]
    print(f"瑕疵音檔被抓出：{len(caught)}/{len(defective)}")

    path = save(
        "argon-result.json",
        {"model": MODEL, "prompt": PROMPT, "rows": rows},
    )
    print(f"\n結果已寫入 {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
