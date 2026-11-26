#!/usr/bin/env python3
"""把 flash-lite 稽核結果做成單檔 HTML 報告。

資料來源：
  data/audit/*.jsonl                  第一輪逐檔結果
  out/audit-sample-arbitration.json   150 個檔案的 Argon 抽樣仲裁

用法：
  python3 scripts/build_audit_report.py
輸出：
  audit-report.html
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import legacy  # noqa: E402  共用網站外殼

DATADIR = ROOT / "data" / "audit"
TPL = ROOT / "scripts" / "report_audit"
OUT = ROOT / "out"

TONE_NAME = {1: "一聲", 2: "二聲", 3: "三聲", 4: "四聲", 5: "輕聲"}
STATUS_NAME = {"tone": "聲調不同", "syllable": "音節不同", "unparsed": "無法解析"}


def kind(exp: str, got: str) -> str:
    if not got:
        return "無法解析"
    if exp.endswith("ng") != got.endswith("ng"):
        return "n／ng 韻尾"
    for a, b in (("zh", "z"), ("ch", "c"), ("sh", "s")):
        if (exp.startswith(a) and got.startswith(b)) or (exp.startswith(b) and got.startswith(a)):
            return "翹舌／平舌"
    if ("v" in exp) != ("v" in got):
        return "ü／u"
    if exp.rstrip("ng") == got.rstrip("ng"):
        return "其他韻尾"
    return "其他（聲母或韻母不同）"


def main() -> None:
    rows: list[dict] = []
    for f in sorted(DATADIR.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit("沒有稽核資料")

    n = len(rows)
    dist = Counter(r["status"] for r in rows)
    voices = {v: Counter(r["status"] for r in rows if r["voice"] == v) for v in ("M", "F")}

    # 聲調
    matrix = [[0] * 5 for _ in range(5)]
    for r in rows:
        gt = r.get("got_tone")
        if gt and 1 <= gt <= 5 and 1 <= r["exp_tone"] <= 5:
            matrix[r["exp_tone"] - 1][gt - 1] += 1
    tones = []
    for t in (1, 2, 3, 4, 5):
        tot = sum(1 for r in rows if r["exp_tone"] == t)
        ok = sum(1 for r in rows if r["exp_tone"] == t and r["status"] == "ok")
        worst = Counter()
        for r in rows:
            if r["exp_tone"] == t and r["status"] == "tone" and r.get("got_tone"):
                worst[r["got_tone"]] += 1
        w = worst.most_common(1)
        tones.append({
            "t": t, "name": TONE_NAME[t], "n": tot, "ok": ok,
            "rate": round(ok / tot * 100, 1) if tot else 0,
            "worst": {"name": TONE_NAME.get(w[0][0], "?"), "n": w[0][1]} if w else None,
        })

    # 音節錯誤
    pairs = Counter((r["exp_base"], r["got_base"]) for r in rows if r["status"] == "syllable")
    types = Counter(kind(e, g) for (e, g) in pairs.elements())
    type_rows = [{"k": k, "n": v, "pct": round(v / max(1, sum(types.values())) * 100)}
                 for k, v in types.most_common()]
    pair_rows = [{"a": a, "b": b, "n": c} for (a, b), c in pairs.most_common(18)]

    # 仲裁
    arb_path = OUT / "audit-sample-arbitration.json"
    arb = json.loads(arb_path.read_text(encoding="utf-8")) if arb_path.is_file() else []
    arb_stat = Counter(x["argon_status"] for x in arb) if arb else Counter()
    arb_map = {f"{x['voice']}/{x['name']}": x for x in arb}

    # 逐檔清單
    flags = []
    for r in rows:
        if r["status"] not in ("tone", "syllable"):
            continue
        key = f"{r['voice']}/{r['name']}"
        a = arb_map.get(key)
        flags.append({
            "v": r["voice"], "n": r["name"],
            "e": f"{r['exp_base']}{r['exp_tone']}",
            "g": r.get("raw") or "",
            "t": r["exp_tone"],
            "s": r["status"],
            "a": a["argon"] if a else None,
            "as": a["argon_status"] if a else None,
        })
    flags.sort(key=lambda x: (x["v"], x["n"]))

    tokens = {"text": 0, "audio": 0, "out": 0}
    for r in rows:
        us = [r.get("usage") or {}] + list(r.get("usage_extra") or []) + [r.get("usage_judge") or {}]
        for u in us:
            for d in u.get("promptTokensDetails") or []:
                if (d.get("modality") or "").upper() == "AUDIO":
                    tokens["audio"] += d.get("tokenCount") or 0
                else:
                    tokens["text"] += d.get("tokenCount") or 0
            tokens["out"] += (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)

    data = {
        "meta": {
            "date": "2026-11-17",
            "files": n, "calls": n + dist["error"],
            "tokens": tokens, "cost": round((tokens["text"] * 0.25 + tokens["audio"] * 0.50 + tokens["out"] * 1.50) / 1e6, 4),
            "costArb": 0.036, "arbN": len(arb),
        },
        "dist": dict(dist),
        "voices": {k: dict(v) for k, v in voices.items()},
        "tones": tones,
        "matrix": matrix,
        "toneNames": [TONE_NAME[i] for i in (1, 2, 3, 4, 5)],
        "types": type_rows,
        "pairs": pair_rows,
        "arb": {"n": len(arb), "ok": arb_stat.get("ok", 0),
                "bad": arb_stat.get("tone", 0) + arb_stat.get("syllable", 0),
                "rows": [{"f": f"{x['voice']}/{x['name']}", "e": f"{x['exp_base']}{x['exp_tone']}",
                          "f1": x["raw"], "f2": x["argon"],
                          "who": "flash-lite 錯" if x["argon_status"] == "ok" else "兩邊都說不對"}
                         for x in arb]},
        "flags": flags,
    }

    css = (TPL / "style.css").read_text(encoding="utf-8")
    body = (TPL / "body.html").read_text(encoding="utf-8")
    js = (TPL / "app.js").read_text(encoding="utf-8")
    js = js.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    html = legacy.render(
        title="注音音檔稽核｜Decision Arena",
        description="以 gemini-3.1-flash-lite 全量檢查 2,934 個注音音檔，並用 Gemini 4 Argon 仲裁抽樣結果。",
        path="audit-report.html", generated="2026-11-17", body=body, css=css, scripts=f"<script>\n{js}</script>")
    (ROOT / "audit-report.html").write_text(html, encoding="utf-8")
    print(f"✅ audit-report.html  {len(html)/1024:.0f} KB")
    print(f"   檔案 {n}、標記 {len(flags)}、仲裁 {len(arb)}")


if __name__ == "__main__":
    main()
