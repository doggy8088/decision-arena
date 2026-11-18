#!/usr/bin/env python3
"""Microsoft Decision 1.1 vs Gemini Decision 1 —— 文字決策基準測試。

背景：MS 這個端點的 `state` 會被當成純文字序列化，音訊（base64）不會被解碼，
      所以三項音訊測試無法執行。改用「兩邊都能吃」的文字任務做對照：

  Task A  語意分類：42 段轉錄稿 → 7 類音場（1 個 choice + 7 個 noul）
  Task B  機率校準：18 句已知正/負/中性商品評論 → 1 個 noul

用法：
  export MS_KEY=...
  python3 scripts/ms_bench.py
輸出：
  out/ms-bench.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import API_BASE, api_key, _post  # noqa: E402

MS_URL = "https://mvpai-eastus.services.ai.azure.com/providers/microsoft/v1/systemone"
MS_MODEL = "Decision-1.1"
G_MODEL = "gemini-decision-1"

CATS = ["speech", "singing", "music", "noise", "concert", "multi_speech", "speech_music"]
CAT_DESC = {
    "speech": "one person talking, no background music",
    "singing": "a singing voice, with or without instruments",
    "music": "instrumental music only, no human voice",
    "noise": "environmental noise only",
    "concert": "live concert with audience",
    "multi_speech": "several people talking",
    "speech_music": "a person talking over background music",
}

# Task B：18 句商品評論，p=正面、n=負面、x=中性/反諷
REVIEWS = [
    ("p1", "p", "This blender is fantastic, it crushes ice in seconds and cleans itself."),
    ("p2", "p", "Arrived a day early and the build quality is better than I expected."),
    ("p3", "p", "Battery lasts all week and the screen is gorgeous."),
    ("p4", "p", "Customer service replied within an hour and sent a replacement for free."),
    ("p5", "p", "Lightweight, quiet, and honestly the best purchase I made this year."),
    ("p6", "p", "The instructions were clear and setup took five minutes."),
    ("n1", "n", "Stopped charging after two weeks and support never answered."),
    ("n2", "n", "The plastic cracked the first time I dropped it from waist height."),
    ("n3", "n", "Battery dies in three hours, nowhere near the advertised twelve."),
    ("n4", "n", "It arrived scratched and the box was clearly already opened."),
    ("n5", "n", "Loud, flimsy, and the app crashes every time I open it."),
    ("n6", "n", "Wrong colour shipped and returning it costs more than the item."),
    ("x1", "x", "It works. That is about all I can say."),
    ("x2", "x", "Great, another charger that needs its own special cable."),
    ("x3", "x", "The packaging was lovely, the product is fine, nothing special."),
    ("x4", "x", "I have used it twice. It has not broken yet."),
    ("x5", "x", "Exactly as described, which is both good and disappointing."),
    ("x6", "x", "Well, it arrived."),
]
REVIEW_Q = {"q": {"type": "noul", "instructions":
                  "Is the reviewer positive about the product overall?"}}

# Task C：24 封訊息，s=垃圾/釣魚、h=正常
MESSAGES = [
    ("s1", "s", "Congratulations! You have won a $1000 gift card. Claim now at bit.ly/claim-now"),
    ("s2", "s", "URGENT: your account will be suspended within 24 hours unless you verify your password here."),
    ("s3", "s", "Cheap replica watches, 90% off, limited stock, order today!!!"),
    ("s4", "s", "Dear customer, we detected unusual activity. Confirm your card number and PIN to unlock."),
    ("s5", "s", "You are our lucky winner! Reply with your bank details to receive the prize."),
    ("s6", "s", "Hot singles in your area want to chat tonight, click the link."),
    ("s7", "s", "Final notice: unpaid invoice #88213, pay immediately via this link or legal action follows."),
    ("s8", "s", "Earn $5000 per week working from home, no experience needed, sign up free."),
    ("s9", "s", "Your parcel is held at customs, pay the $2.99 fee at this secure link to release it."),
    ("s10", "s", "Limited time: buy one get three free, only for the next 2 hours, shop now."),
    ("s11", "s", "Hi, I am a prince and I need your help transferring funds, you will be rewarded."),
    ("s12", "s", "Your subscription auto-renewed. To cancel, log in with your full card details here."),
    ("h1", "h", "Hi team, the quarterly report is attached. Let me know if you need anything else."),
    ("h2", "h", "Your order #4821 has shipped and should arrive on Tuesday."),
    ("h3", "h", "Reminder: the design review moved to Thursday at 2pm in room 4B."),
    ("h4", "h", "Thanks for the feedback, I have pushed a fix and it is on staging now."),
    ("h5", "h", "Can you send me the latest version of the budget spreadsheet?"),
    ("h6", "h", "The invoice for October is attached; payment is due within 30 days as usual."),
    ("h7", "h", "Lunch tomorrow? There is a new place near the office."),
    ("h8", "h", "We have scheduled maintenance on Saturday from 2 to 4am; the service may be slow."),
    ("h9", "h", "Here is the link to the shared drive with the interview recordings."),
    ("h10", "h", "Your appointment with Dr Chen is confirmed for Monday 10am."),
    ("h11", "h", "I reviewed the pull request and left two comments about error handling."),
    ("h12", "h", "The kids school is closed on Friday due to the typhoon warning."),
]
SPAM_Q = {"q": {"type": "noul", "instructions":
                "Is this message spam or a phishing attempt (as opposed to a legitimate message)?"}}


# ---------------------------------------------------------------- 呼叫
def ms_call(state: dict, questions: dict, retries: int = 6) -> dict:
    body = {"model": MS_MODEL, "state": state, "questions": questions}
    req = urllib.request.Request(
        MS_URL, data=json.dumps(body).encode(),
        headers={"api-key": os.environ["MS_KEY"], "Content-Type": "application/json"},
        method="POST")
    t0 = time.perf_counter()
    last = ""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
                return {"ok": True, "answers": d.get("answers", {}),
                        "usage": d.get("usage", {}),
                        "ms": round((time.perf_counter() - t0) * 1000),
                        "attempts": attempt + 1}
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None)
            body_txt = exc.read().decode()[:200] if hasattr(exc, "read") else str(exc)
            last = f"{code or 'ERR'} {body_txt}"
            if code in (400, 413, 422):   # 不是暫時性錯誤，不用重試
                break
            time.sleep(min(8, 0.6 * (2 ** attempt)) + random.random() * 0.4)
    return {"ok": False, "error": last, "ms": round((time.perf_counter() - t0) * 1000),
            "attempts": retries}


def gemini_call(state_text: str, questions: dict) -> dict:
    body = {"model": G_MODEL,
            "input": [{"type": "text", "text": state_text}],
            "questions": questions}
    t0 = time.perf_counter()
    try:
        d = _post(f"{API_BASE}/decisions?key={api_key()}", body, timeout=120)
        if "error" in d:
            return {"ok": False, "error": str(d["error"])[:200], "ms": 0, "attempts": 1}
        return {"ok": True, "answers": d.get("answers", {}), "usage": d.get("usage", {}),
                "ms": round((time.perf_counter() - t0) * 1000), "attempts": 1}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200], "ms": 0, "attempts": 1}


# ---------------------------------------------------------------- Task A
def scene_questions() -> dict:
    q = {"scene": {"type": "choice",
                   "instructions": "Which sound scene does this transcript come from?",
                   "criteria": {c: CAT_DESC[c] for c in CATS}}}
    for c in CATS:
        q[f"is_{c}"] = {"type": "noul",
                        "instructions": f"Does this transcript come from audio containing {CAT_DESC[c]}?"}
    return q


def run_task_a(runs: int, workers: int) -> list[dict]:
    clips = json.loads((ROOT / "out" / "clip-validation.json").read_text(encoding="utf-8"))
    clips = [c for c in clips if (c.get("text") or "").strip()]
    q = scene_questions()
    jobs = [(c, r) for c in clips for r in range(runs)]
    out = []
    lock_errors = Counter()

    def work(job):
        clip, run = job
        text = f"Transcript of a short audio clip: {clip['text']}"
        ms = ms_call({"type": "text", "text": text}, q)
        gm = gemini_call(text, q)
        return {"id": clip["id"], "cat": clip["cat"], "run": run,
                "transcript": clip["text"], "ms": ms, "gemini": gm}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, rec in enumerate(pool.map(work, jobs), 1):
            out.append(rec)
            if i % 20 == 0:
                print(f"  Task A {i}/{len(jobs)}")
    return out


# ---------------------------------------------------------------- Task B
def run_task_c() -> list[dict]:
    out = []
    for mid, label, text in MESSAGES:
        ms = ms_call({"type": "text", "text": text}, SPAM_Q)
        gm = gemini_call(text, SPAM_Q)
        out.append({"id": mid, "label": label, "text": text, "ms": ms, "gemini": gm})
    print(f"  Task C {len(out)} 筆完成")
    return out


def run_task_b() -> list[dict]:
    out = []
    for rid, label, text in REVIEWS:
        ms = ms_call({"type": "text", "text": text}, REVIEW_Q)
        gm = gemini_call(text, REVIEW_Q)
        out.append({"id": rid, "label": label, "text": text, "ms": ms, "gemini": gm})
    print(f"  Task B {len(out)} 筆完成")
    return out


# ---------------------------------------------------------------- 分析
def pick_choice(res: dict) -> str | None:
    if not res.get("ok"):
        return None
    a = res["answers"].get("scene") or {}
    return a.get("choice") or (max(a["probabilities"], key=a["probabilities"].get)
                                if a.get("probabilities") else None)


def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    w = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return round(w / (len(pos) * len(neg)), 3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-b", action="store_true")
    ap.add_argument("--skip-ops", action="store_true")
    args = ap.parse_args()
    if not os.environ.get("MS_KEY"):
        sys.exit("缺少 MS_KEY")

    print("Task A：42 段轉錄稿 × 7 類")
    a = run_task_a(args.runs, args.workers)
    b = [] if args.skip_b else run_task_b()
    print("Task C：24 封訊息 × 垃圾/正常")
    c = run_task_c()

    # ---- Task A 統計
    by_model = {}
    for name, key in (("ms", "ms"), ("gemini", "gemini")):
        rows = [(r["cat"], pick_choice(r[key])) for r in a if r[key].get("ok")]
        hit = sum(1 for c, p in rows if p == c)
        by_model[name] = {
            "n": len(rows),
            "ok": hit,
            "acc": round(hit / len(rows) * 100, 1) if rows else None,
            "matrix": {t: dict(Counter(p for t, p in rows if t == c and p)) for c in CATS for t in [c]},
            "ms": round(statistics.mean([r[key]["ms"] for r in a if r[key].get("ok")])),
            "tokens": sum((r[key].get("usage", {}).get("input_tokens")
                           or r[key].get("usage", {}).get("total_input_tokens") or 0) for r in a),
            "fail": sum(1 for r in a if not r[key].get("ok")),
            "attempts": sum(r[key].get("attempts", 1) for r in a),
        }
    # 每類召回
    for name in ("ms", "gemini"):
        rows = [(r["cat"], pick_choice(r[name])) for r in a if r[name].get("ok")]
        by_model[name]["per_class"] = {
            c: {"n": sum(1 for t, _ in rows if t == c),
                "hit": sum(1 for t, p in rows if t == c and p == c)}
            for c in CATS}

    # 兩模型一致度
    agree = tot = 0
    for r in a:
        p1, p2 = pick_choice(r["ms"]), pick_choice(r["gemini"])
        if p1 and p2:
            tot += 1
            agree += p1 == p2

    # ---- Task B 統計
    tb = {}
    if b:
        for name in ("ms", "gemini"):
            pos = [r[name]["answers"]["q"]["noul"] for r in b
                   if r[name].get("ok") and r["label"] == "p"]
            neg = [r[name]["answers"]["q"]["noul"] for r in b
                   if r[name].get("ok") and r["label"] == "n"]
            neu = [r[name]["answers"]["q"]["noul"] for r in b
                   if r[name].get("ok") and r["label"] == "x"]
            tb[name] = {
                "mean_pos": round(statistics.mean(pos), 3) if pos else None,
                "mean_neg": round(statistics.mean(neg), 3) if neg else None,
                "mean_neutral": round(statistics.mean(neu), 3) if neu else None,
                "auc": auc(pos, neg),
                "correct_at_0_5": sum(1 for v in pos if v >= 0.5) + sum(1 for v in neg if v < 0.5),
                "n": len(pos) + len(neg),
            }

    tc = {}
    if c:
        for name in ("ms", "gemini"):
            rows = [(r["label"], r[name]["answers"]["q"]["noul"]) for r in c if r[name].get("ok")]
            sp = [v for l, v in rows if l == "s"]
            hm = [v for l, v in rows if l == "h"]
            tc[name] = {
                "n": len(rows),
                "mean_spam": round(statistics.mean(sp), 3) if sp else None,
                "mean_ham": round(statistics.mean(hm), 3) if hm else None,
                "auc": auc(sp, hm),
                "correct": sum(1 for v in sp if v >= 0.5) + sum(1 for v in hm if v < 0.5),
                "fail": sum(1 for r in c if not r[name].get("ok")),
                "ms": round(statistics.mean([r[name]["ms"] for r in c if r[name].get("ok")])) if rows else None,
                "tokens": sum((r[name].get("usage", {}).get("input_tokens")
                               or r[name].get("usage", {}).get("total_input_tokens") or 0) for r in c),
            }

    # ---- 操作特性探針：乾淨延遲 + 首次成功率（不受重試退避污染）
    ops = {}
    if not args.skip_ops:
        lat, tries, got = [], 0, 0
        while got < 8 and tries < 40:
            tries += 1
            t0 = time.perf_counter()
            r = ms_call({"type": "text", "text": f"Message {tries}: limited offer, buy now."},
                        {"q": {"type": "noul", "instructions": "Is this message spam?"}}, retries=1)
            if r["ok"]:
                lat.append((time.perf_counter() - t0) * 1000)
                got += 1
        ops = {
            "probe_calls": tries, "probe_ok": got,
            "first_try_rate": round(got / tries * 100, 1) if tries else None,
            "latency_median_ms": round(statistics.median(lat)) if lat else None,
            "latency_min_ms": round(min(lat)) if lat else None,
            "latency_max_ms": round(max(lat)) if lat else None,
        }
        print(f"  操作探針：首次成功率 {ops['first_try_rate']}%、"
              f"成功延遲中位數 {ops['latency_median_ms']} ms")

    summary = {
        "ops": ops,
        "taskA": by_model,
        "taskC": tc,
        "taskA_agree": {"agree": agree, "n": tot,
                        "rate": round(agree / tot * 100, 1) if tot else None},
        "taskB": tb,
    }
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "ms-bench.json").write_text(
        json.dumps({"summary": summary, "taskA": a, "taskB": b, "taskC": c},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")

    print("\n=== Task A：轉錄稿 → 7 類 ===")
    for name, label in (("ms", "MS Decision 1.1"), ("gemini", "Gemini Decision 1")):
        s = by_model[name]
        print(f"{label:20s} {s['ok']}/{s['n']} ({s['acc']}%)  "
              f"{s['ms']}ms  {s['tokens']} tokens  失敗 {s['fail']}/{s['n']}  "
              f"平均嘗試 {s['attempts']/max(1,s['n']+s['fail']):.2f}")
    print(f"兩模型答案一致：{agree}/{tot} ({summary['taskA_agree']['rate']}%)")
    if tb:
        print("\n=== Task B：評論正負向（機率校準）===")
        for name, label in (("ms", "MS Decision 1.1"), ("gemini", "Gemini Decision 1")):
            s = tb[name]
            print(f"{label:20s} 正 {s['mean_pos']} / 中性 {s['mean_neutral']} / 負 {s['mean_neg']}  "
                  f"AUC {s['auc']}  ≥0.5 判對 {s['correct_at_0_5']}/{s['n']}")
    if tc:
        print("\n=== Task C：垃圾訊息判斷 ===")
        for name, label in (("ms", "MS Decision 1.1"), ("gemini", "Gemini Decision 1")):
            s2 = tc[name]
            print(f"{label:20s} 垃圾 {s2['mean_spam']} / 正常 {s2['mean_ham']}  "
                  f"AUC {s2['auc']}  判對 {s2['correct']}/{s2['n']}  "
                  f"{s2['ms']}ms  {s2['tokens']} tokens  失敗 {s2['fail']}")
    print(f"\n→ {(ROOT / 'out' / 'ms-bench.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
