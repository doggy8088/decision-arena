#!/usr/bin/env python3
"""音場分類基準測試：Decisions API vs gemini-4-argon。

每個 10 秒片段：
  - Decisions：一個 choice 題（7 類）＋ 7 個 noul 題（每類一個獨立是非題），跑 N 次
  - Argon    ：盲聽，輸出 JSON（類別、信心、是否有人聲、是否有多人），跑 M 次後多數決

用法：
  export GEMINI_API_KEY=...
  python3 scripts/scene_bench.py                 # 正式跑
  python3 scripts/scene_bench.py --limit 3       # 先試 3 段
  python3 scripts/scene_bench.py --budget 5      # 成本上限（美元）

輸出：out/scene-results.json、out/scene-summary.md，終端機印混淆矩陣
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import API_BASE, OUT, api_key, _post  # noqa: E402

MANIFEST = ROOT / "data" / "scenes" / "manifest.json"
RESULT = OUT / "scene-results.json"

DECISION_MODEL = "gemini-decision-1"
ARGON_MODEL = "gemini-4-argon"

CATS = ["speech", "singing", "music", "noise", "concert", "multi_speech", "speech_music"]
CAT_DESC = {
    "speech": "one person talking, no background music (talk, lecture, audiobook)",
    "singing": "singing voice, with or without instrumental backing (a song)",
    "music": "instrumental music only, no human voice",
    "noise": "environmental noise only: rain, traffic, construction, white noise; no voice, no music",
    "concert": "live concert recording: amplified performance, audience/crowd, applause, echoes",
    "multi_speech": "several people talking (podcast, panel, interview, conversation)",
    "speech_music": "a person talking over background music (ad, vlog, explainer)",
}
# 實務上有意義的二分法
VOICE_CATS = {"speech", "singing", "concert", "multi_speech", "speech_music"}
SPEECH_CATS = {"speech", "multi_speech", "speech_music"}

# 2026-11 牌價（per 1M tokens）；Argon 為 2026-11-30 前促銷價
PRICE = {
    DECISION_MODEL: (0.10, 0.10, 0.0),
    ARGON_MODEL: (2.00, 2.00, 10.00),
}

ARGON_SCHEMA = {
    "type": "object",
    "properties": {
        "scene": {"type": "string", "enum": CATS},
        "confidence": {"type": "number"},
        "voice_present": {"type": "boolean"},
        "music_present": {"type": "boolean"},
        "speaker_count": {"type": "integer"},
        "evidence": {"type": "string"},
    },
    "required": ["scene", "confidence", "voice_present", "music_present", "speaker_count", "evidence"],
}

ARGON_PROMPT = """Listen to this 10-second audio clip and classify the sound scene.

Choose exactly one label from this list:
- speech: one person talking, no background music
- singing: a singing voice, with or without instruments
- music: instrumental music only, no human voice
- noise: environmental noise only (rain, traffic, construction, white noise)
- concert: live concert recording with audience/crowd
- multi_speech: several people talking (podcast, panel, interview)
- speech_music: a person talking over background music (ad, vlog, explainer)

Also report: confidence (0-1), voice_present (is there any human voice at all),
music_present (is there any music at all), speaker_count (how many distinct voices, 0 if none),
and evidence (one short sentence in Traditional Chinese describing what you heard).

Only output JSON."""


# ---------------------------------------------------------------- cost
def usage_cost(model: str, usage: dict) -> float:
    if not usage:
        return 0.0
    text_in, audio_in, text_out = PRICE[model]
    by_mod = {}
    for d in usage.get("input_tokens_by_modality") or usage.get("promptTokensDetails") or []:
        key = (d.get("modality") or "").lower()
        by_mod[key] = d.get("tokens") or d.get("tokenCount") or 0
    if by_mod:
        tin, ain = by_mod.get("text", 0), by_mod.get("audio", 0)
    else:
        tin = usage.get("total_input_tokens") or usage.get("promptTokenCount") or 0
        ain = 0
    tout = (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0)
    tout += usage.get("total_output_tokens") or 0
    return (tin * text_in + ain * audio_in + tout * text_out) / 1_000_000


class Ledger:
    def __init__(self, budget: float):
        self.budget = budget
        self.spent = 0.0
        self.lock = threading.Lock()
        self.calls = 0

    def charge(self, usd: float) -> None:
        with self.lock:
            self.spent += usd
            self.calls += 1
            if self.spent > self.budget:
                raise RuntimeError(f"已超出預算 US${self.budget}（目前 US${self.spent:.3f}）")

    def left(self) -> float:
        return max(0.0, self.budget - self.spent)


# ---------------------------------------------------------------- API
def decisions_questions() -> dict:
    q: dict = {
        "scene": {
            "type": "choice",
            "instructions": "Which sound scene does this audio clip contain?",
            "criteria": {c: CAT_DESC[c] for c in CATS},
        }
    }
    for c in CATS:
        q[f"is_{c}"] = {
            "type": "noul",
            "instructions": f"Does this audio clip contain {CAT_DESC[c]}?",
        }
    return q


def run_decisions(b64: str, mime: str, questions: dict, ledger: Ledger) -> dict:
    body = {
        "model": DECISION_MODEL,
        "input": [{"type": "audio", "mime_type": mime, "data": b64}],
        "questions": questions,
    }
    t0 = time.perf_counter()
    result = _post(f"{API_BASE}/decisions?key={api_key()}", body, timeout=180)
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "unknown"))
    usage = result.get("usage", {})
    ledger.charge(usage_cost(DECISION_MODEL, usage))
    answers = result["answers"]
    probs = answers["scene"].get("probabilities", {})
    noul = {c: answers[f"is_{c}"]["noul"] for c in CATS}
    return {
        "choice_probs": probs,
        "choice_top": max(probs, key=probs.get) if probs else None,
        "confidence": answers["scene"].get("confidence"),
        "noul": noul,
        "noul_top": max(noul, key=noul.get) if noul else None,
        "usage": usage,
        "cost_usd": round(usage_cost(DECISION_MODEL, usage), 6),
        "ms": round((time.perf_counter() - t0) * 1000),
    }


def run_argon(b64: str, mime: str, thinking: str, ledger: Ledger) -> dict:
    body = {
        "contents": [{
            "parts": [
                {"text": ARGON_PROMPT},
                {"inlineData": {"mimeType": mime, "data": b64}},
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "thinkingConfig": {"thinkingLevel": thinking},
            "responseMimeType": "application/json",
            "responseSchema": ARGON_SCHEMA,
        },
    }
    t0 = time.perf_counter()
    result = _post(f"{API_BASE}/models/{ARGON_MODEL}:generateContent?key={api_key()}", body, timeout=180)
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "unknown"))
    usage = result.get("usageMetadata", {})
    ledger.charge(usage_cost(ARGON_MODEL, usage))
    try:
        text = "".join(p.get("text", "") for p in result["candidates"][0]["content"]["parts"])
        parsed = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"JSON 解析失敗：{exc}") from exc
    return {
        "scene": parsed.get("scene"),
        "confidence": parsed.get("confidence"),
        "voice_present": parsed.get("voice_present"),
        "music_present": parsed.get("music_present"),
        "speaker_count": parsed.get("speaker_count"),
        "evidence": parsed.get("evidence"),
        "usage": usage,
        "cost_usd": round(usage_cost(ARGON_MODEL, usage), 6),
        "ms": round((time.perf_counter() - t0) * 1000),
    }


# ---------------------------------------------------------------- 單一 clip
def process_clip(clip: dict, dec_runs: int, arg_runs: int, thinking: str,
                 ledger: Ledger) -> dict:
    path = ROOT / clip["file"]
    b64 = base64.b64encode(path.read_bytes()).decode()
    mime = "audio/mpeg"
    questions = decisions_questions()

    decisions, argon, errors = [], [], []
    for i in range(dec_runs):
        try:
            decisions.append(run_decisions(b64, mime, questions, ledger))
        except Exception as exc:  # noqa: BLE001
            errors.append({"stage": f"decisions#{i}", "error": str(exc)[:250]})
    for i in range(arg_runs):
        try:
            argon.append(run_argon(b64, mime, thinking, ledger))
        except Exception as exc:  # noqa: BLE001
            errors.append({"stage": f"argon#{i}", "error": str(exc)[:250]})

    votes = Counter(a["scene"] for a in argon if a.get("scene"))
    majority = votes.most_common(1)[0][0] if votes else None
    return {
        "id": clip["id"],
        "cat": clip["cat"],
        "title": clip.get("title"),
        "clip_start": clip.get("clip_start_in_video"),
        "decisions": decisions,
        "argon": argon,
        "argon_votes": dict(votes),
        "argon_majority": majority,
        "errors": errors,
    }


# ---------------------------------------------------------------- 指標
def confusion(rows: list[dict], key: str) -> dict:
    m = {t: Counter() for t in CATS}
    for r in rows:
        pred = r.get(key)
        if pred:
            m[r["cat"]][pred] += 1
    return m


def accuracy(rows: list[dict], key: str) -> tuple[int, int]:
    hit = sum(1 for r in rows if r.get(key) == r["cat"])
    return hit, len(rows)


def binary(rows: list[dict], key: str, positive: set[str]) -> tuple[int, int]:
    hit = sum(1 for r in rows if (r.get(key) in positive) == (r["cat"] in positive))
    return hit, len(rows)


def fmt_matrix(m: dict) -> str:
    short = {c: c[:6] for c in CATS}
    head = "true\\pred".ljust(13) + "".join(short[c].rjust(8) for c in CATS) + "   n  recall"
    lines = [head, "-" * len(head)]
    for t in CATS:
        row = m[t]
        n = sum(row.values())
        recall = f"{row[t]}/{n}" if n else "-"
        lines.append(t.ljust(13) + "".join(str(row.get(c, 0)).rjust(8) for c in CATS)
                     + f" {n:3d}  {recall}")
    return "\n".join(lines)


def summarise(rows: list[dict]) -> dict:
    dec0 = [{"cat": r["cat"], "pred": r["decisions"][0]["choice_top"] if r["decisions"] else None}
            for r in rows]
    dec_noul = [{"cat": r["cat"], "pred": r["decisions"][0]["noul_top"] if r["decisions"] else None}
                for r in rows]
    arg = [{"cat": r["cat"], "pred": r["argon_majority"]} for r in rows]
    arg1 = [{"cat": r["cat"], "pred": r["argon"][0]["scene"] if r["argon"] else None} for r in rows]

    out: dict = {}
    for name, data in (("decisions_choice", dec0), ("decisions_noul", dec_noul),
                       ("argon_majority", arg), ("argon_single", arg1)):
        d = [x for x in data if x["pred"]]
        hit, n = accuracy(d, "pred")
        vhit, vn = binary(d, "pred", VOICE_CATS)
        shit, sn = binary(d, "pred", SPEECH_CATS)
        out[name] = {
            "accuracy": f"{hit}/{n}",
            "acc_rate": round(hit / n, 3) if n else None,
            "voice_binary": f"{vhit}/{vn}",
            "speech_binary": f"{shit}/{sn}",
            "matrix": {t: dict(confusion(d, "pred")[t]) for t in CATS},
        }

    # 穩定性：同一 clip 多次 Decisions choice 是否一致
    same = agree = 0
    for r in rows:
        tops = [x["choice_top"] for x in r["decisions"] if x.get("choice_top")]
        if len(tops) > 1:
            agree += 1 if len(set(tops)) == 1 else 0
            same += 1
    out["decisions_stability"] = f"{agree}/{same}"

    arg_same = agree = 0
    for r in rows:
        tops = [x["scene"] for x in r["argon"] if x.get("scene")]
        if len(tops) > 1:
            agree += 1 if len(set(tops)) == 1 else 0
            arg_same += 1
    out["argon_stability"] = f"{agree}/{arg_same}"

    # 每類平均：真實類別被分配的機率
    true_p = []
    for r in rows:
        if not r["decisions"]:
            continue
        p = r["decisions"][0]["choice_probs"].get(r["cat"])
        if p is not None:
            true_p.append(p)
    out["decisions_mean_p_true"] = round(sum(true_p) / len(true_p), 3) if true_p else None

    # 信心分布
    confs = [r["decisions"][0]["confidence"] for r in rows if r["decisions"]]
    out["decisions_mean_confidence"] = round(sum(confs) / len(confs), 3) if confs else None
    aconf = [x["confidence"] for r in rows for x in r["argon"] if isinstance(x.get("confidence"), (int, float))]
    out["argon_mean_confidence"] = round(sum(aconf) / len(aconf), 3) if aconf else None

    out["ms"] = {
        "decisions_mean": round(sum(x["ms"] for r in rows for x in r["decisions"])
                                / max(1, sum(len(r["decisions"]) for r in rows))),
        "argon_mean": round(sum(x["ms"] for r in rows for x in r["argon"])
                            / max(1, sum(len(r["argon"]) for r in rows))),
    }
    out["cost_usd"] = round(sum(x["cost_usd"] for r in rows for x in r["decisions"] + r["argon"]), 4)
    return out


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=5.0)
    ap.add_argument("--decisions-runs", type=int, default=2)
    ap.add_argument("--argon-runs", type=int, default=3)
    ap.add_argument("--thinking", default="low", choices=["low", "high"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", default="", help="逗號分隔的 clip id")
    ap.add_argument("--merge", action="store_true", help="與既有結果合併（配合 --only）")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    clips = manifest["clips"]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        clips = [c for c in clips if c["id"] in wanted]
    if args.limit:
        clips = clips[: args.limit]
    if not clips:
        sys.exit("沒有可測試的片段，先跑 scripts/fetch_scenes.py")

    ledger = Ledger(args.budget)
    results: list[dict] = []
    lock = threading.Lock()

    prior: dict[str, dict] = {}
    if args.merge and RESULT.is_file():
        try:
            prior = {c["id"]: c for c in json.loads(RESULT.read_text(encoding="utf-8"))["clips"]}
        except (json.JSONDecodeError, KeyError):
            prior = {}

    print(f"clips={len(clips)}  decisions×{args.decisions_runs}  argon×{args.argon_runs} "
          f"(thinking={args.thinking})  budget=US${args.budget}")
    print("-" * 96)

    def work(clip):
        row = process_clip(clip, args.decisions_runs, args.argon_runs, args.thinking, ledger)
        with lock:
            results.append(row)
            d = row["decisions"][0]["choice_top"] if row["decisions"] else "ERR"
            a = row["argon_majority"] or "ERR"
            mark = "✅" if d == clip["cat"] and a == clip["cat"] else ("🟡" if a == clip["cat"] else "❌")
            print(f"{mark} {clip['id']:16s} true={clip['cat']:13s} dec={d:13s} argon={a:13s} "
                  f"spent=US${ledger.spent:.3f}")
            # 逐段落盤，避免中斷就全毀
            OUT.mkdir(exist_ok=True)
            merged = {**prior, **{r["id"]: r for r in results}}
            RESULT.write_text(json.dumps({"meta": vars(args),
                                          "clips": sorted(merged.values(), key=lambda r: r["id"])},
                                         ensure_ascii=False, indent=1), encoding="utf-8")

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(work, clips))
    except RuntimeError as exc:
        print(f"\n⚠️  {exc}")
    except KeyboardInterrupt:
        print("\n中斷。")

    if not results:
        sys.exit("沒有完成任何片段")

    merged = {**prior, **{r["id"]: r for r in results}}
    all_rows = sorted(merged.values(), key=lambda r: r["id"])
    summary = summarise(all_rows)
    payload = {"meta": vars(args), "summary": summary, "clips": all_rows}
    OUT.mkdir(exist_ok=True)
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== 指標 ===")
    for k in ("decisions_choice", "decisions_noul", "argon_majority", "argon_single"):
        s = summary[k]
        print(f"{k:18s} 七類 {s['accuracy']:>6s}  有無人聲 {s['voice_binary']:>5s}  "
              f"有無說話 {s['speech_binary']:>5s}")
    print(f"Decisions 重跑一致 {summary['decisions_stability']}，Argon 重跑一致 {summary['argon_stability']}")
    print(f"真實類別平均機率 {summary['decisions_mean_p_true']}，"
          f"平均信心 Decisions {summary['decisions_mean_confidence']} / Argon {summary['argon_mean_confidence']}")
    print(f"平均延遲：Decisions {summary['ms']['decisions_mean']} ms，Argon {summary['ms']['argon_mean']} ms")
    print(f"總花費：US${ledger.spent:.4f}（{ledger.calls} 次呼叫）")

    md = [f"# 音場分類結果\n", f"- 片段數：{len(all_rows)}",
          f"- 設定：Decisions×{args.decisions_runs}、Argon×{args.argon_runs}（thinking={args.thinking}）",
          f"- 花費：US${ledger.spent:.4f}（{ledger.calls} 次呼叫）\n", "## 指標\n",
          "| 方法 | 七類正確 | 有無人聲 | 有無說話 |", "| --- | --- | --- | --- |"]
    for k in ("decisions_choice", "decisions_noul", "argon_majority", "argon_single"):
        s = summary[k]
        md.append(f"| {k} | {s['accuracy']} | {s['voice_binary']} | {s['speech_binary']} |")
    md += ["\n## 混淆矩陣（Decisions choice）\n", "```", fmt_matrix(confusion(
        [{"cat": r["cat"], "pred": r["decisions"][0]["choice_top"] if r["decisions"] else None}
         for r in all_rows], "pred")), "```", "\n## 混淆矩陣（Argon 多數決）\n", "```",
        fmt_matrix(confusion([{"cat": r["cat"], "pred": r["argon_majority"]} for r in all_rows], "pred")),
        "```"]
    (OUT / "scene-summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n結果 → {RESULT.relative_to(ROOT)}")
    print(f"摘要 → {(OUT / 'scene-summary.md').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
