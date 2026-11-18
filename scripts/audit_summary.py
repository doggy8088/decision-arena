#!/usr/bin/env python3
"""把 data/audit/*.jsonl 整理成可讀的報告與表格。

用法：
  python3 scripts/audit_summary.py
輸出：
  out/audit-report.md   完整報告（含分布、混淆表、完整清單）
  out/audit-flags.csv   只含被標記的檔案
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATADIR = ROOT / "data" / "audit"
OUT = ROOT / "out"
TONE_NAME = {1: "一聲", 2: "二聲", 3: "三聲", 4: "四聲", 5: "輕聲"}


def load() -> list[dict]:
    rows = []
    for f in sorted(DATADIR.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def tokens(rec: dict) -> tuple[int, int, int]:
    us = [rec.get("usage") or {}] + list(rec.get("usage_extra") or []) + [rec.get("usage_judge") or {}]
    t = a = o = 0
    for u in us:
        for d in u.get("promptTokensDetails") or []:
            if (d.get("modality") or "").upper() == "AUDIO":
                a += d.get("tokenCount") or 0
            else:
                t += d.get("tokenCount") or 0
        o += (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)
    return t, a, o


def main() -> None:
    rows = load()
    n = len(rows)
    if not n:
        raise SystemExit("沒有紀錄，先跑 scripts/audit_syllables.py")

    status = Counter(r["status"] for r in rows)
    voice_stat = defaultdict(Counter)
    for r in rows:
        voice_stat[r["voice"]][r["status"]] += 1

    # 聲調混淆（音節本體正確、只有聲調不同時才算）
    tone_pairs = Counter()   # 只算「不一致」
    tone_matrix = Counter()  # 全部（含對角線）
    for r in rows:
        gt = r.get("got_tone")
        if not gt:
            continue
        tone_matrix[(r["exp_tone"], gt)] += 1
        if r["status"] == "tone":
            tone_pairs[(r["exp_tone"], gt)] += 1
    tone_total = Counter(r["exp_tone"] for r in rows)

    syll = Counter((r["exp_base"], r.get("got_base"))
                   for r in rows if r["status"] == "syllable")

    flagged = [r for r in rows if r["status"] in ("tone", "syllable", "unparsed")]
    confirmed = [r for r in flagged if r.get("majority_status") in ("tone", "syllable", "unparsed")]
    judge_ok = [r for r in confirmed if (r.get("judge") or {}).get("status") == "ok"]
    judge_bad = [r for r in confirmed if (r.get("judge") or {}).get("status") in ("tone", "syllable")]

    tsum = asum = osum = 0
    for r in rows:
        t, a, o = tokens(r)
        tsum += t
        asum += a
        osum += o
    cost = (tsum * 0.25 + asum * 0.50 + osum * 1.50) / 1e6
    calls = n + sum(len(r.get("usage_extra") or []) for r in rows) + sum(
        1 for r in rows if r.get("usage_judge"))

    pct = lambda x: f"{x / n * 100:.1f}%"  # noqa: E731
    md = [
        "# gemini-3.1-flash-lite 全量注音檢測",
        "",
        f"前提：`public/M/*.mp3`、`public/F/*.mp3` 全部視為正確讀音；模型輸出與檔名不符＝模型認為有錯。",
        "",
        f"- 檔案：**{n}** 個（M {voice_stat['M']['ok'] + sum(v for k, v in voice_stat['M'].items() if k != 'ok')}、"
        f"F {sum(voice_stat['F'].values())}）",
        f"- 呼叫：**{calls}** 次（{n} 個檔案各一次，其餘為重試）",
        f"- Token：文字 {tsum:,}、音訊 {asum:,}、輸出 {osum:,} → 合計 **{tsum+asum+osum:,}**",
        f"- 花費：**US${cost:.4f}**（另有 150 次 Argon 抽樣仲裁，約 US$0.04）",
        "",
        "## 一、整體結果",
        "",
        "| 狀態 | 數量 | 比例 | 說明 |",
        "| --- | --- | --- | --- |",
        f"| 一致 | {status['ok']} | {pct(status['ok'])} | 模型聽到的音節與聲調都與檔名相同 |",
        f"| 只有聲調不同 | {status['tone']} | {pct(status['tone'])} | 音節對了，聲調不對 |",
        f"| 音節不同 | {status['syllable']} | {pct(status['syllable'])} | 聲母或韻母就不同 |",
        f"| 無法解析 | {status['unparsed']} | {pct(status['unparsed'])} | 模型沒給出可比較的拼音 |",
    ]
    if status["nonstandard"]:
        md.append(f"| 檔名非標準拼音 | {status['nonstandard']} | {pct(status['nonstandard'])} | 不列入統計 |")
    if status["error"]:
        md.append(f"| 呼叫失敗 | {status['error']} | {pct(status['error'])} | 已重試仍失敗 |")

    md += [
        "",
        "## 二、男聲 vs 女聲",
        "",
        "| 聲音 | 一致 | 聲調不同 | 音節不同 | 一致率 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for v in ("M", "F"):
        s = voice_stat[v]
        tot = sum(s.values())
        md.append(f"| {'男聲 M' if v == 'M' else '女聲 F'} | {s['ok']} | {s['tone']} | {s['syllable']} | "
                  f"{s['ok'] / tot * 100:.1f}% |")

    md += ["", "## 三、各聲調的辨識率", "",
           "| 檔名聲調 | 檔案數 | 一致 | 一致率 | 最常被聽成 |",
           "| --- | --- | --- | --- | --- |"]
    for t in (1, 2, 3, 4, 5):
        tot = tone_total.get(t, 0)
        if not tot:
            continue
        ok = sum(1 for r in rows if r["exp_tone"] == t and r["status"] == "ok")
        worst = Counter({k[1]: v for k, v in tone_pairs.items() if k[0] == t}).most_common(1)
        worst_txt = f"{TONE_NAME.get(worst[0][0], worst[0][0])}（{worst[0][1]} 個）" if worst else "—"
        md.append(f"| {TONE_NAME.get(t, t)} | {tot} | {ok} | {ok / tot * 100:.1f}% | {worst_txt} |")

    md += ["", "### 聲調混淆表（列＝檔名聲調，欄＝模型聽成）", "",
           "| 期望 \\ 模型 | 一聲 | 二聲 | 三聲 | 四聲 | 輕聲 |",
           "| --- | --- | --- | --- | --- | --- |"]
    for t in (1, 2, 3, 4, 5):
        cells = " | ".join(str(tone_matrix.get((t, x), 0)) for x in (1, 2, 3, 4, 5))
        md.append(f"| **{TONE_NAME.get(t, t)}** | {cells} |")

    if syll:
        md += ["", "## 四、音節錯誤的常見型態（前 15）", "",
               "| 檔名音節 | 模型聽成 | 次數 |", "| --- | --- | --- |"]
        for (exp, got), c in syll.most_common(15):
            md.append(f"| {exp} | {got} | {c} |")

    # 音節錯誤分類
    def kind(exp: str, got: str) -> str:
        if not got:
            return "無法解析"
        if exp.endswith("ng") != got.endswith("ng"):
            return "n／ng 韻尾"
        for a, b in (("zh", "z"), ("ch", "c"), ("sh", "s")):
            if exp.startswith(a) and got.startswith(b) or exp.startswith(b) and got.startswith(a):
                return "翹舌／平舌（zh-z、ch-c、sh-s）"
        if ("v" in exp) != ("v" in got):
            return "ü／u"
        if exp.rstrip("ng") == got.rstrip("ng"):
            return "其他韻尾"
        return "其他（聲母或韻母不同）"

    groups = Counter(kind(e, g) for (e, g) in syll.elements())
    md += ["", "### 音節錯誤的類型", "", "| 類型 | 數量 | 佔音節錯誤 |", "| --- | --- | --- |"]
    for k, c in groups.most_common():
        md.append(f"| {k} | {c} | {c / max(1, sum(groups.values())) * 100:.0f}% |")

    # 若有抽樣仲裁檔，優先採用（避免逐檔 Argon 太慢）
    sample = OUT / "audit-sample-arbitration.json"
    sample_rows = json.loads(sample.read_text(encoding="utf-8")) if sample.is_file() else []
    md += ["", "## 五、到底是模型錯，還是音檔有問題？", ""]
    if sample_rows:
        sc = Counter(x["argon_status"] for x in sample_rows)
        sn = len(sample_rows)
        md += [
            f"被標記的 {len(flagged)} 個裡，隨機抽 **{sn}** 個檔案，再用 `gemini-4-argon` 聽一次當仲裁：",
            "",
            "| Argon 的說法 | 數量 | 比例 | 意思 |",
            "| --- | --- | --- | --- |",
            f"| 與檔名相同 | {sc['ok']} | {sc['ok']/sn*100:.0f}% | **flash-lite 自己聽錯**，音檔沒問題 |",
            f"| 也與檔名不同 | {sc['tone']+sc['syllable']} | {(sc['tone']+sc['syllable'])/sn*100:.0f}% | 兩個模型都不同意 → 音檔可能真的有問題 |",
            "",
            f"換算到全量：flash-lite 標記的 {len(flagged)} 個裡面，大約 **{len(flagged)*sc['ok']//sn}** 個是它自己聽錯，"
            f"**{len(flagged)*(sc['tone']+sc['syllable'])//sn}** 個連 Argon 都覺得不對。",
            "",
        ]
        md += ["| 抽樣檔案 | 期望 | flash-lite | Argon | 誰對 |", "| --- | --- | --- | --- | --- |"]
        for x in sample_rows[:40]:
            who = "flash-lite 錯" if x["argon_status"] == "ok" else "兩邊都說不對"
            md.append(f"| {x['voice']}/{x['name']} | {x['exp_base']}{x['exp_tone']} | {x['raw']} | {x['argon']} | {who} |")
        md.append("")
    if confirmed:
        md += [
            f"被 flash-lite 標記、且 3 次覆核後仍然不一致：**{len(confirmed)}** 個。"
            f"再用 `gemini-4-argon` 仲裁一次：",
            "",
            f"- 兩邊都不同意檔名：**{len(judge_bad)}** 個 → 比較可能是**音檔本身**的聲調與檔名不符",
            f"- 只有 flash-lite 不同意：**{len(judge_ok)}** 個 → 比較可能是**flash-lite 聽錯**",
            "",
            "| 檔名 | 期望 | flash-lite（3 次） | Argon | 判定 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in sorted(confirmed, key=lambda x: (x["voice"], x["exp_base"], x["exp_tone"]))[:400]:
            votes = " / ".join(str(v) for v in (r.get("votes") or [r.get("raw")]))
            j = r.get("judge") or {}
            verdict = ("兩邊都說不對" if j.get("status") in ("tone", "syllable")
                       else "只有 flash-lite 說不對" if j.get("status") == "ok" else "未仲裁")
            md.append(f"| {r['voice']}/{r['name']} | {r['exp_base']}{r['exp_tone']} | {votes} | "
                      f"{j.get('raw', '—')} | {verdict} |")
        if len(confirmed) > 400:
            md.append(f"| … | 其餘 {len(confirmed) - 400} 筆見 CSV | | | |")
    else:
        md.append("（沒有需要仲裁的項目）")

    md += ["", "## 六、判讀與限制", "",
           "- 音檔是**按注音共用**的單音節錄音，不是逐字；因此這份表是「音節」層級，同一音節的所有字都會受影響。",
           "- 只跑一個模型、一次（被標記者才做 3 次覆核），單次結果本身有噪聲，這也是為什麼要覆核。",
           "- 檔案是 TTS 合成音，孤立音節的聲調（尤其輕聲、以及 a / ai / ao 這種開口韻）本來就容易被聽成別的調。",
           "- 「模型認為有錯」不等於「音檔有錯」；第三節的 Argon 仲裁就是在拆開這兩件事。",
           ]

    OUT.mkdir(exist_ok=True)
    (OUT / "audit-report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    fields = ["voice", "name", "exp_base", "exp_tone", "raw", "got_base", "got_tone",
              "status", "votes", "majority", "majority_status", "judge"]
    with (OUT / "audit-flags.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in sorted(flagged, key=lambda x: (x["status"] != "syllable", x["voice"], x["name"])):
            row = {k: r.get(k) for k in fields}
            if isinstance(row.get("judge"), dict):
                row["judge"] = row["judge"].get("raw")
            if isinstance(row.get("votes"), list):
                row["votes"] = " / ".join(str(v) for v in row["votes"])
            w.writerow(row)

    print(f"檔案 {n}、呼叫 {calls}、Token {tsum+asum+osum:,}、成本 US${cost:.4f}")
    print(f"一致 {status['ok']} / 聲調 {status['tone']} / 音節 {status['syllable']} / 未解析 {status['unparsed']}")
    print(f"→ {OUT/'audit-report.md'}\n→ {OUT/'audit-flags.csv'}")


if __name__ == "__main__":
    main()
