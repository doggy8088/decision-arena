#!/usr/bin/env python3
"""把 out/ms-bench.json 組成單檔 HTML 報告（套用網站外殼，元件樣式與注音稽核報告共用）。

用法：
  python3 scripts/build_ms_html.py
輸出：
  ms-decision-report.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import legacy  # noqa: E402  共用網站外殼

CSS = ROOT / "scripts" / "report_audit" / "style.css"
BODY = ROOT / "scripts" / "report_ms" / "body.html"


def main() -> None:
    d = json.loads((ROOT / "out" / "ms-bench.json").read_text(encoding="utf-8"))
    s, a, tb, tc = d["summary"], d["summary"]["taskA"], d["summary"]["taskB"], d["summary"]["taskC"]
    ops = s.get("ops") or {}

    body = BODY.read_text(encoding="utf-8")

    m = {
        "__MSA_OK__": a["ms"]["ok"], "__MSA_N__": a["ms"]["n"], "__MSA_ACC__": a["ms"]["acc"],
        "__MSA_MS__": f"{a['ms']['ms']:,}", "__MSA_FAIL__": a["ms"]["fail"],
        "__GA_OK__": a["gemini"]["ok"], "__GA_N__": a["gemini"]["n"], "__GA_ACC__": a["gemini"]["acc"],
        "__GA_MS__": f"{a['gemini']['ms']:,}", "__GA_FAIL__": a["gemini"]["fail"],
        "__AGREE__": s["taskA_agree"]["agree"], "__AGREE_N__": s["taskA_agree"]["n"],
        "__AGREE_PCT__": s["taskA_agree"]["rate"],
        "__B_MS_POS__": tb["ms"]["mean_pos"], "__B_G_POS__": tb["gemini"]["mean_pos"],
        "__B_MS_NEU__": tb["ms"]["mean_neutral"], "__B_G_NEU__": tb["gemini"]["mean_neutral"],
        "__B_MS_NEG__": tb["ms"]["mean_neg"], "__B_G_NEG__": tb["gemini"]["mean_neg"],
        "__B_MS_OK__": tb["ms"]["correct_at_0_5"], "__B_G_OK__": tb["gemini"]["correct_at_0_5"],
        "__B_N__": tb["ms"]["n"],
        "__C_MS_SP__": tc["ms"]["mean_spam"], "__C_G_SP__": tc["gemini"]["mean_spam"],
        "__C_MS_HM__": tc["ms"]["mean_ham"], "__C_G_HM__": tc["gemini"]["mean_ham"],
        "__C_MS_OK__": tc["ms"]["correct"], "__C_MS_N__": tc["ms"]["n"],
        "__C_G_OK__": tc["gemini"]["correct"], "__C_G_N__": tc["gemini"]["n"],
        "__C_MS_FAIL__": tc["ms"]["fail"],
        "__FIRST_TRY__": ops.get("first_try_rate", "—"),
        "__LAT__": ops.get("latency_median_ms", "—"),
    }
    for k, v in m.items():
        body = body.replace(k, str(v))

    html = legacy.render(
        title="Microsoft Decision 1.1 實測｜Decision Arena",
        description="Microsoft Decision 1.1（Azure AI Foundry）的音訊支援查證與純文字任務對照。",
        path="ms-decision-report.html", generated="2026-11-19", body=body, css=CSS.read_text(encoding="utf-8"))
    (ROOT / "ms-decision-report.html").write_text(html, encoding="utf-8")
    print(f"✅ ms-decision-report.html  {len(html)/1024:.0f} KB"
          f"（殘留佔位符 {html.count('__')}）")


if __name__ == "__main__":
    main()
