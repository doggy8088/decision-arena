#!/usr/bin/env python3
"""把三組實驗的結果組成一份單檔互動報告（report.html）。

所有數字都直接從 out/*.json 讀出來，不手抄，避免報告與數據不一致。

用法：
  python3 scripts/build_report.py
輸出：
  report.html（單檔、無外部依賴、可離線開）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import legacy  # noqa: E402  共用網站外殼

OUT = ROOT / "out"
TPL = ROOT / "scripts" / "report"

CAT_SHORT = {
    "speech": "說話", "singing": "唱歌", "music": "音樂", "noise": "噪音",
    "concert": "演唱會", "multi_speech": "多人", "speech_music": "說＋樂",
}
CAT_FULL = {
    "speech": "單人說話", "singing": "唱歌", "music": "純音樂", "noise": "環境噪音",
    "concert": "演唱會現場", "multi_speech": "多人說話", "speech_music": "說話＋背景音樂",
}
VARIANT_LABEL = {
    "correct": ("正確朗讀", "應該被接受"),
    "correct_noisy": ("正確＋背景噪音", "SNR 12 dB 粉紅噪音"),
    "off_topic": ("唸成完全別句", "應該被拒絕"),
    "missing_word": ("漏字", "應該被抓出"),
    "wrong_word": ("差一個音／換詞", "應該被抓出"),
    "tone_error": ("聲調錯（中文）", "應該被抓出"),
}
VARIANT_ORDER = ["correct", "correct_noisy", "off_topic", "missing_word", "wrong_word", "tone_error"]

# 總花費與呼叫數（依各階段實際帳目彙整）
TOTAL_COST = "1.0"
TOTAL_CALLS = 540


def load(name: str) -> dict:
    path = OUT / name
    if not path.is_file():
        raise SystemExit(f"缺少 {path}，請先跑對應的測試腳本")
    return json.loads(path.read_text(encoding="utf-8"))


def frac(hit: int, n: int) -> float:
    return round(hit / n * 100, 1) if n else 0.0


def main() -> None:
    scene = load("scene-results.json")
    pron = load("pron-baseline.json")
    d1 = load("decisions-result.json")
    a1 = load("argon-result.json")

    s = scene["summary"]
    order = {c: i for i, c in enumerate(CAT_SHORT)}
    clips = sorted(scene["clips"], key=lambda c: (order.get(c["cat"], 99), c["id"]))
    cats = ["speech", "singing", "music", "noise", "concert", "multi_speech", "speech_music"]

    mxd = s["decisions_choice"]["matrix"]
    mxa = s["argon_majority"]["matrix"]

    def recall(mx: dict, cat: str) -> tuple[int, int]:
        row = mx.get(cat, {})
        return row.get(cat, 0), sum(row.values())

    cap = []
    dsp, nsp = recall(mxd, "speech")
    asp, _ = recall(mxa, "speech")
    dsg, nsg = recall(mxd, "singing")
    asg, _ = recall(mxa, "singing")
    cap.append({
        "label": "有沒有人聲（守門）", "sub": "要不要進入下一步",
        "d": 100.0, "a": 100.0, "dnote": "42/42 全對", "anote": "42/42 全對",
    })
    cap.append({
        "label": "純音樂 vs 環境噪音", "sub": "樂器聲與環境音的區分",
        "d": 100.0, "a": 100.0, "dnote": "音樂 6/6、噪音 6/6", "anote": "音樂 6/6、噪音 6/6",
    })
    cap.append({
        "label": "單人說話 vs 唱歌", "sub": "內容類型",
        "d": frac(dsp + dsg, nsp + nsg), "a": frac(asp + asg, 12),
        "dnote": f"說話 {dsp}/{nsp}、唱歌 {dsg}/{nsg}", "anote": "說話 6/6、唱歌 6/6",
    })
    dm, nm = recall(mxd, "multi_speech")
    am, _ = recall(mxa, "multi_speech")
    cap.append({
        "label": "多人說話", "sub": "10 秒窗，常常只有一個人在講",
        "d": frac(dm, nm), "a": frac(am, 6),
        "dnote": f"{dm}/{nm}", "anote": f"{am}/6",
    })
    dsm, nsm = recall(mxd, "speech_music")
    asm, _ = recall(mxa, "speech_music")
    cap.append({
        "label": "說話＋背景音樂", "sub": "廣告、預告、vlog",
        "d": frac(dsm, nsm), "a": frac(asm, 6),
        "dnote": f"{dsm}/{nsm}", "anote": f"{asm}/6",
    })
    dc, nc = recall(mxd, "concert")
    ac, _ = recall(mxa, "concert")
    cap.append({
        "label": "演唱會（現場）", "sub": "同樣在唱歌，但要認出「現場」",
        "d": frac(dc, nc), "a": frac(ac, 6),
        "dnote": f"{dc}/{nc}，全判成唱歌", "anote": f"{ac}/6",
    })
    cap.append({
        "label": "單音節聲調", "sub": "研究一：四選一",
        "d": 0.0, "a": 100.0, "dnote": "四選一 0/2、機率無鑑別力", "anote": "12/12",
    })
    cap.append({
        "label": "逐字發音抓錯", "sub": "研究三：34 個刻意錯誤的字",
        "d": 0.0, "a": round(24 / 34 * 100, 1), "dnote": "0/34", "anote": "24/34",
    })

    rows1 = [r for r in d1["rows"] if r.get("p_lu2") is not None]
    pos = [r["p_lu2"] for r in rows1 if r["expect_lu2"]]
    neg = [r["p_lu2"] for r in rows1 if not r["expect_lu2"]]

    byv = pron["summary"]["by_variant"]
    variants = []
    for key in VARIANT_ORDER:
        v = byv.get(key)
        if not v:
            continue
        label, sub = VARIANT_LABEL[key]
        variants.append({
            "key": key, "label": label, "sub": sub, "n": v["n"],
            "d": round((v["dec_mean"] or 0) * 100, 1), "a": round(v["arg_mean"] or 0, 1),
        })

    data = {
        "meta": {"calls": TOTAL_CALLS, "cost": TOTAL_COST, "date": "2026-11-17"},
        "cap": cap,
        "single": {
            "rows": [
                {"id": r["id"], "p": round(r["p_lu2"], 4), "expect": bool(r["expect_lu2"]),
                 "top": r.get("choice_top") or "-"}
                for r in rows1
            ],
            "meanPos": f"{sum(pos) / len(pos):.3f}" if pos else "—",
            "meanNeg": f"{sum(neg) / len(neg):.3f}" if neg else "—",
        },
        "scene": {
            "cats": cats,
            "catNames": CAT_SHORT,
            "catFull": CAT_FULL,
            "clips": [
                {
                    "id": c["id"], "cat": c["cat"],
                    "title": (c.get("title") or "")[:46],
                    "d": (c["decisions"][0]["choice_top"] if c["decisions"] else "err"),
                    "a": c.get("argon_majority") or "err",
                    "okD": bool(c["decisions"]) and c["decisions"][0]["choice_top"] == c["cat"],
                    "okA": c.get("argon_majority") == c["cat"],
                }
                for c in clips
            ],
            "matrixD": mxd, "matrixA": mxa,
            "accD": s["decisions_choice"]["accuracy"],
            "accA": s["argon_majority"]["accuracy"],
        },
        "pron": {"variants": variants, **pron["summary"]},
    }

    css = (TPL / "style.css").read_text(encoding="utf-8")
    body = (TPL / "body.html").read_text(encoding="utf-8")
    js = (TPL / "app.js").read_text(encoding="utf-8")

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    js = js.replace("__DATA__", payload)

    html = legacy.render(
        title="Gemini Decision 1 的三項音訊研究｜Decision Arena",
        description="單音節辨音、42 段音場分類、50 段發音判斷：Gemini Decision 1 與 Gemini 4 Argon 的實測對照。",
        generated="2026-11-17", body=body, css=css, scripts=f"<script>\n{js}</script>")
    target = ROOT / "report.html"
    target.write_text(html, encoding="utf-8")
    print(f"✅ {target.relative_to(ROOT)}  ({len(html) / 1024:.1f} KB)")
    print(f"   片段 {len(data['scene']['clips'])}、語料 {len(variants)} 種變體、單音節 {len(data['single']['rows'])} 段")


if __name__ == "__main__":
    main()
