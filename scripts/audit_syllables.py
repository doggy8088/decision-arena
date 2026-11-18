#!/usr/bin/env python3
"""用 gemini-3.1-flash-lite 逐一檢測 stroke 專案的注音音檔。

前提（使用者指定）：`public/M/*.mp3` 與 `public/F/*.mp3` 都是正確讀音。
因此「模型輸出 != 檔名音節」就是模型認為有錯的地方。

流程：
  1. 第一輪：每個檔案呼叫一次 flash-lite，取拼音+聲調
  2. 第二輪：只針對第一輪不一致的檔案，再抽 2 次取多數決（共 3 票）
  3. 第三輪（選用）：多數決仍不一致者，用 gemini-4-argon 仲裁，判斷是模型錯還是音檔有問題

用法：
  python3 scripts/audit_syllables.py --pilot 30        # 先試 30 個
  python3 scripts/audit_syllables.py                   # 全量
  python3 scripts/audit_syllables.py --voice F         # 只跑女聲

輸出：
  data/audit/<voice>.jsonl      每檔的完整紀錄（含 usage），可中斷續跑
  out/audit-flags.csv           模型認為有錯的清單
  out/audit-report.md           摘要與表格
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import API_BASE, api_key, _post  # noqa: E402

SRC = Path("/Users/will/games/stroke/public")
OUTDIR = ROOT / "out"
DATADIR = ROOT / "data" / "audit"

MODEL = "gemini-3.1-flash-lite"
JUDGE = "gemini-4-argon"
PRICE = {  # per 1M tokens
    MODEL: {"text": 0.25, "audio": 0.50, "out": 1.50},
    JUDGE: {"text": 2.00, "audio": 2.00, "out": 10.00},
}

PROMPT = (
    "這是台灣華語的單音節錄音。請只輸出你聽到的音節，"
    "格式：漢語拼音+聲調數字（1-5），例如 ma3、zhong1、lv4、er2。"
    "不要解釋、不要加其他文字。若完全沒有語音，只輸出 NONE。"
)

TONE_MARKS = {
    "ā": ("a", 1), "á": ("a", 2), "ǎ": ("a", 3), "à": ("a", 4),
    "ē": ("e", 1), "é": ("e", 2), "ě": ("e", 3), "è": ("e", 4),
    "ī": ("i", 1), "í": ("i", 2), "ǐ": ("i", 3), "ì": ("i", 4),
    "ō": ("o", 1), "ó": ("o", 2), "ǒ": ("o", 3), "ò": ("o", 4),
    "ū": ("u", 1), "ú": ("u", 2), "ǔ": ("u", 3), "ù": ("u", 4),
    "ǖ": ("v", 1), "ǘ": ("v", 2), "ǚ": ("v", 3), "ǜ": ("v", 4), "ü": ("v", 0),
}

# 檔案命名不是標準拼音的（無法用檔名當 ground truth）
NONSTANDARD = {"lvan2", "lvan3", "nui2", "q5", "ch5"}


def parse_expected(name: str) -> tuple[str, int]:
    """檔名 → (拼音本體, 聲調)。沒有數字視為一聲。"""
    m = re.match(r"^([a-z]+)([1-5])?$", name)
    if not m:
        return "", 0
    base, tone = m.group(1), m.group(2)
    return base, int(tone) if tone else 1


def normalise(text: str) -> tuple[str, int | None, str]:
    """模型輸出 → (拼音本體, 聲調, 原始字串)。失敗回 ("", None, raw)。"""
    raw = text.strip()
    if not raw or raw.upper().startswith("NONE"):
        return "", None, raw
    s = unicodedata.normalize("NFC", raw.lower())
    s = s.replace("lu:", "lv").replace("ü", "v").replace("u:", "v")
    tone = None
    out = []
    for ch in s:
        if ch in TONE_MARKS:
            base_ch, t = TONE_MARKS[ch]
            out.append(base_ch)
            if t:
                tone = t
        else:
            out.append(ch)
    joined = "".join(out)
    joined = re.sub(r"[\s\-_·。、,，]|（|）|\(|\)", "", joined)
    digits = re.findall(r"[1-5]", joined)
    if digits:
        tone = int(digits[0])
    joined = re.sub(r"[^a-z]", "", joined)
    joined = re.sub(r"(.)\1{2,}", r"\1\1", joined)  # maaa → maa
    return joined, tone, raw


def compare(exp_base: str, exp_tone: int, got_base: str, got_tone: int | None) -> str:
    if not got_base:
        return "unparsed"
    if got_base == exp_base and got_tone == exp_tone:
        return "ok"
    if got_base == exp_base:
        return "tone"
    return "syllable"


def usage_cost(model: str, usage: dict) -> float:
    p = PRICE[model]
    by = {}
    for d in usage.get("promptTokensDetails") or []:
        by[(d.get("modality") or "").upper()] = d.get("tokenCount") or 0
    tin = by.get("TEXT", 0)
    ain = by.get("AUDIO", 0)
    tout = (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0)
    return (tin * p["text"] + ain * p["audio"] + tout * p["out"]) / 1_000_000


def ask(model: str, audio_path: Path, prompt: str = PROMPT, retries: int = 6) -> dict:
    data = base64.b64encode(audio_path.read_bytes()).decode()
    body = {
        "contents": [{"parts": [{"text": prompt},
                                {"inlineData": {"mimeType": "audio/mpeg", "data": data}}]}],
        "generationConfig": {"temperature": 0},
    }
    last = ""
    for attempt in range(retries):
        started = time.perf_counter()
        try:
            r = _post(f"{API_BASE}/models/{model}:generateContent?key={api_key()}", body, timeout=120)
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:160]
            time.sleep(min(30, 2 ** attempt) + random.random())
            continue
        if "error" in r:
            msg = str(r["error"].get("message", ""))[:160]
            last = msg
            if "quota" in msg.lower() or "rate" in msg.lower() or "429" in msg:
                time.sleep(min(45, 3 ** attempt) + random.random())
                continue
            return {"ok": False, "error": msg, "ms": 0, "usage": {}}
        try:
            text = "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"]).strip()
        except (KeyError, IndexError):
            last = "no content"
            time.sleep(1 + random.random())
            continue
        usage = r.get("usageMetadata", {})
        return {"ok": True, "text": text, "usage": usage,
                "ms": round((time.perf_counter() - started) * 1000),
                "cost": usage_cost(model, usage)}
    return {"ok": False, "error": last or "unknown", "ms": 0, "usage": {}}


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="both", choices=["M", "F", "both"])
    ap.add_argument("--pilot", type=int, default=0, help="只跑前 N 個（測試用）")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-confirm", action="store_true", help="不做第二輪多數決")
    ap.add_argument("--skip-arbitrate", action="store_true", help="不做 Argon 仲裁")
    args = ap.parse_args()

    DATADIR.mkdir(parents=True, exist_ok=True)
    voices = ["M", "F"] if args.voice == "both" else [args.voice]

    # 續跑：已完成的就不重跑（省錢）
    prior: dict[str, dict] = {}
    for v in voices:
        f = DATADIR / f"{v}.jsonl"
        if f.is_file():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    if r.get("status") == "error":
                        continue  # 失敗的重跑
                    prior[f"{r['voice']}/{r['name']}"] = r
    if prior:
        print(f"已有紀錄 {len(prior)} 筆，將跳過")

    jobs = []
    for v in voices:
        for f in sorted((SRC / v).glob("*.mp3")):
            jobs.append({"voice": v, "name": f.stem, "path": str(f)})
    jobs = [j for j in jobs if f"{j['voice']}/{j['name']}" not in prior]
    if args.pilot:
        jobs = jobs[: args.pilot]
    print(f"檔案 {len(jobs)} 個，模型 {MODEL}，併發 {args.workers}")

    # ---------- 第一輪 ----------
    lock = threading.Lock()
    done = 0
    t0 = time.perf_counter()
    store: list[dict] = list(prior.values())

    def persist(rec: dict) -> None:
        f = DATADIR / f"{rec['voice']}.jsonl"
        with lock:
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def run1(job: dict) -> dict:
        exp_base, exp_tone = parse_expected(job["name"])
        r = ask(MODEL, Path(job["path"]))
        rec = {**job, "exp_base": exp_base, "exp_tone": exp_tone,
               "nonstandard": job["name"] in NONSTANDARD}
        if not r["ok"]:
            rec.update({"status": "error", "error": r["error"], "usage": {}, "cost": 0.0})
        else:
            gb, gt, raw = normalise(r["text"])
            rec.update({"raw": raw, "got_base": gb, "got_tone": gt,
                        "status": "nonstandard" if rec["nonstandard"]
                                  else compare(exp_base, exp_tone, gb, gt),
                        "usage": r["usage"], "cost": r["cost"], "ms": r["ms"]})
        persist(rec)
        with lock:
            nonlocal done
            done += 1
            if done % 100 == 0 or done == len(jobs):
                el = time.perf_counter() - t0
                print(f"  第一輪 {done}/{len(jobs)}  {el:.0f}s  "
                      f"({done/el:.1f}/s)  目前不一致 {sum(1 for x in store if x['status'] in ('tone','syllable'))}")
        return rec

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for rec in pool.map(run1, jobs):
            store.append(rec)
    print(f"第一輪完成：{time.perf_counter()-t0:.0f}s")

    # ---------- 第二輪：多數決 ----------
    flagged = [r for r in store
               if r["status"] in ("tone", "syllable", "unparsed") and not r.get("majority")]
    print(f"第一輪不一致 {len(flagged)} 個，進行第二輪多數決…" if flagged else "全部一致。")
    if flagged and not args.skip_confirm:
        def run_more(rec: dict) -> dict:
            votes = [{"base": rec.get("got_base"), "tone": rec.get("got_tone"), "raw": rec.get("raw")}]
            extra_cost = 0.0
            extra_usage = []
            for _ in range(2):
                r = ask(MODEL, Path(rec["path"]))
                if not r["ok"]:
                    continue
                gb, gt, raw = normalise(r["text"])
                votes.append({"base": gb, "tone": gt, "raw": raw})
                extra_cost += r["cost"]
                extra_usage.append(r["usage"])
            counts: dict[str, int] = {}
            for v in votes:
                key = f"{v['base']}{v['tone'] if v['tone'] is not None else '?'}"
                counts[key] = counts.get(key, 0) + 1
            top = max(counts, key=counts.get)
            rec["votes"] = [v["raw"] for v in votes]
            rec["majority"] = top
            rec["majority_n"] = counts[top]
            rec["cost"] = (rec.get("cost") or 0) + extra_cost
            rec["usage_extra"] = extra_usage
            mb, mt = normalise(top)[0], normalise(top)[1]
            rec["majority_status"] = compare(rec["exp_base"], rec["exp_tone"], mb, mt)
            return rec

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(run_more, flagged))

        still = [r for r in store
                 if r.get("majority_status") in ("tone", "syllable", "unparsed") and not r.get("judge")]
        print(f"多數決後仍不一致 {len(still)} 個")

        # ---------- 第三輪：Argon 仲裁 ----------
        if still and not args.skip_arbitrate:
            print("進行 Argon 仲裁…")

            def arbitrate(rec: dict) -> dict:
                r = ask(JUDGE, Path(rec["path"]))
                if not r["ok"]:
                    rec["judge"] = None
                    return rec
                gb, gt, raw = normalise(r["text"])
                rec["judge"] = {"raw": raw, "base": gb, "tone": gt,
                                "status": compare(rec["exp_base"], rec["exp_tone"], gb, gt)}
                rec["cost"] = (rec.get("cost") or 0) + r["cost"]
                rec["usage_judge"] = r["usage"]
                return rec

            with ThreadPoolExecutor(max_workers=max(3, args.workers // 2)) as pool:
                list(pool.map(arbitrate, still))

    # ---------- 落盤 ----------
    for v in voices:
        rows = [r for r in store if r["voice"] == v]
        if rows:
            (DATADIR / f"{v}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    summarise(store, time.perf_counter() - t0)


def summarise(store: list[dict], elapsed: float) -> None:
    OUTDIR.mkdir(exist_ok=True)
    cats = ["ok", "tone", "syllable", "unparsed", "nonstandard", "error"]
    total = len(store)
    counts = {c: sum(1 for r in store if r["status"] == c) for c in cats}

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

    tsum = asum = osum = 0
    for r in store:
        t, a, o = tokens(r)
        tsum += t
        asum += a
        osum += o
    cost = sum(r.get("cost") or 0 for r in store)
    calls = total + sum(len(r.get("usage_extra") or []) for r in store) + sum(
        1 for r in store if r.get("usage_judge"))

    print("\n=== 結果 ===")
    print(f"檔案 {total} 個，呼叫 {calls} 次，耗時 {elapsed:.0f}s")
    for c in cats:
        if counts[c]:
            print(f"  {c:12s} {counts[c]:5d}  ({counts[c]/total*100:.1f}%)")
    print(f"Token：文字輸入 {tsum:,}、音訊輸入 {asum:,}、輸出 {osum:,}（合計 {tsum+asum+osum:,}）")
    print(f"成本：US${cost:.4f}")

    # CSV
    import csv
    fields = ["voice", "name", "exp_base", "exp_tone", "raw", "got_base", "got_tone",
              "status", "votes", "majority", "majority_status", "judge"]
    with (OUTDIR / "audit-flags.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in sorted(store, key=lambda x: (x["status"] != "ok", x["voice"], x["name"])):
            row = {k: r.get(k) for k in fields}
            if isinstance(row.get("judge"), dict):
                row["judge"] = row["judge"].get("raw")
            if isinstance(row.get("votes"), list):
                row["votes"] = " / ".join(str(v) for v in row["votes"])
            w.writerow(row)

    # Markdown
    bad = [r for r in store if r["status"] in ("tone", "syllable", "unparsed")]
    confirmed = [r for r in bad if r.get("majority_status") in ("tone", "syllable", "unparsed")]
    judge_bad = [r for r in confirmed if (r.get("judge") or {}).get("status") in ("tone", "syllable")]

    md = ["# flash-lite 全量注音檢測", "",
          f"- 檔案：{total}（M/F 各半）",
          f"- 模型：`{MODEL}`，temperature 0",
          f"- 呼叫：{calls} 次（含第二輪多數決與 Argon 仲裁）",
          f"- Token：文字 {tsum:,}、音訊 {asum:,}、輸出 {osum:,}，合計 **{tsum+asum+osum:,}**",
          f"- 成本：**US${cost:.4f}**", "",
          "## 結果分布", "", "| 狀態 | 數量 | 比例 |", "| --- | --- | --- |"]
    label = {"ok": "一致", "tone": "聲調不同", "syllable": "音節不同",
             "unparsed": "無法解析", "nonstandard": "檔名非標準拼音（不計）", "error": "呼叫失敗"}
    for c in cats:
        if counts[c]:
            md.append(f"| {label[c]} | {counts[c]} | {counts[c]/total*100:.1f}% |")

    md += ["", "## 模型認為有錯的清單（多數決後仍不一致）", ""]
    if confirmed:
        md += ["| 檔名 | 期望 | 模型（3 次） | Argon 仲裁 | 判定 |", "| --- | --- | --- | --- | --- |"]
        for r in sorted(confirmed, key=lambda x: (x["voice"], x["exp_base"], x["exp_tone"])):
            votes = " / ".join(str(v) for v in (r.get("votes") or [r.get("raw")]))
            judge = r.get("judge") or {}
            verdict = {"tone": "兩模型都說聲調不同", "syllable": "兩模型都說音節不同"}.get(
                judge.get("status"), "未仲裁" if not judge else "Argon 認為正確")
            md.append(f"| {r['voice']}/{r['name']} | {r['exp_base']}{r['exp_tone']} | {votes} | "
                      f"{judge.get('raw', '—')} | {verdict} |")
    else:
        md.append("（無）")

    (OUTDIR / "audit-report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n→ {OUTDIR / 'audit-report.md'}\n→ {OUTDIR / 'audit-flags.csv'}")


if __name__ == "__main__":
    main()
