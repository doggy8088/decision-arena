#!/usr/bin/env python3
"""發音判斷基準測試：同一批 TTS 語料同時丟給 Decisions 與 Argon。

語料含「正確句」「刻意錯誤句（tone_error／wrong_word／missing_word／off_topic）」
「正確句＋背景噪音」。逐字檢查是否抓到刻意安排的錯誤。

用法：
  export GEMINI_API_KEY=...
  python3 scripts/pron_baseline.py
  python3 scripts/pron_baseline.py --limit 6     # 先試
輸出：out/pron-baseline.json、out/pron-summary.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import assess  # noqa: E402

MANIFEST = ROOT / "data" / "pron" / "manifest.json"
OUT = ROOT / "out" / "pron-baseline.json"
SUMMARY = ROOT / "out" / "pron-summary.md"

PAD_SECONDS = 0.6
DECIDE_ACCEPT = 0.5   # Decisions P(唸對) 的驗收門檻
ARGON_ACCEPT = 70     # Argon 0-100 的驗收門檻


def pad_mp3(raw: bytes) -> bytes:
    """補 0.6 秒尾靜音（Gemini 對沒有尾巴靜音的短音檔會漏聽最後幾個字）。"""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.mp3"
        dst = Path(td) / "out.mp3"
        src.write_bytes(raw)
        proc = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src),
                               "-af", f"apad=pad_dur={PAD_SECONDS}", "-ac", "1", "-ar", "24000",
                               "-c:a", "libmp3lame", "-b:a", "96k", str(dst)],
                              capture_output=True, timeout=60)
        if proc.returncode == 0 and dst.is_file():
            return dst.read_bytes()
    return raw


def auc(pos: list[float], neg: list[float]) -> float:
    """Mann-Whitney U 形式的 AUC：pos 應該比較高。"""
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return round(wins / (len(pos) * len(neg)), 3)


def flagged_tokens(expect_flag: str | None, tokens: list[str]) -> list[str]:
    if not expect_flag:
        return []
    return [t for t in tokens if t and (t in expect_flag or expect_flag in t)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--thinking", default="low", choices=["low", "high"])
    ap.add_argument("--no-pad", action="store_true", help="不補尾靜音（用來看尾切效應）")
    ap.add_argument("--ab-pad", action="store_true", help="對 correct 樣本加跑一次不補靜音的對照")
    args = ap.parse_args()

    cfg = json.loads(MANIFEST.read_text(encoding="utf-8"))
    clips = cfg["clips"]
    if args.limit:
        clips = clips[: args.limit]

    rows = []
    print(f"samples={len(clips)} thinking={args.thinking}")
    print(f"{'sample':26s} {'gold':6s} {'dec_p':>6s} {'lvl':>3s} {'argon':>5s}  flagged(dec/argon)")
    print("-" * 96)

    for clip in clips:
        audio = (ROOT / clip["file"]).read_bytes()
        if not args.no_pad:
            audio = pad_mp3(audio)
        try:
            res = assess.assess(audio, "audio/mpeg", clip["target"], clip["lang"], thinking=args.thinking)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {clip['id']:26s} {str(exc)[:80]}")
            rows.append({**clip, "error": str(exc)[:250]})
            continue

        d, a = res["decisions"], res["argon"]
        tokens = res["model_input"]["tokens"]
        want = flagged_tokens(clip.get("expect_flag"), tokens)

        dec_flagged = [w["token"] for w in d.get("words", [])
                       if w["token"] in want and w.get("verdict") != "correct"] if d.get("ok") else []
        arg_flagged = [w["token"] for w in a.get("words", [])
                       if w["token"] in want and w.get("status") in ("mispronounced", "missing")] if a.get("ok") else []

        row = {
            **clip,
            "decisions": {
                "ok": d.get("ok"), "p_correct": d.get("p_correct"), "level": d.get("level"),
                "level_label": d.get("level_label"), "level_probs": d.get("level_probs"),
                "latency_ms": d.get("latency_ms"), "cost_usd": d.get("cost_usd"),
                "flag_hit": len(dec_flagged), "flag_want": len(want),
                "words": [{"token": w["token"], "verdict": w["verdict"]} for w in d.get("words", [])],
                "error": d.get("error"),
            },
            "argon": {
                "ok": a.get("ok"), "overall": a.get("overall"), "transcript": a.get("transcript"),
                "summary": a.get("summary"), "tips": a.get("tips"),
                "latency_ms": a.get("latency_ms"), "cost_usd": a.get("cost_usd"),
                "flag_hit": len(arg_flagged), "flag_want": len(want),
                "words": [{"token": w["token"], "heard": w["heard"], "status": w["status"], "note": w["note"]}
                          for w in a.get("words", [])],
                "error": a.get("error"),
            },
            "cost_usd": res["cost_usd"],
        }
        rows.append(row)
        print(f"{clip['id']:26s} {clip['gold']:6s} "
              f"{(d.get('p_correct') or 0):6.2f} {(d.get('level') if d.get('level') is not None else -1):3d} "
              f"{(a.get('overall') or 0):5d}  "
              f"{','.join(dec_flagged) or '-'} / {','.join(arg_flagged) or '-'}")

    good = [r for r in rows if r.get("gold") == "ok" and r.get("decisions", {}).get("ok")]
    bad = [r for r in rows if r.get("gold") == "error" and r.get("decisions", {}).get("ok")]

    dp_ok = [r["decisions"]["p_correct"] for r in good]
    dp_bad = [r["decisions"]["p_correct"] for r in bad]
    ao_ok = [r["argon"]["overall"] for r in good if r.get("argon", {}).get("ok")]
    ao_bad = [r["argon"]["overall"] for r in bad if r.get("argon", {}).get("ok")]

    def accept_rate(vals: list[float], thr: float) -> str:
        if not vals:
            return "-"
        n = sum(1 for v in vals if v >= thr)
        return f"{n}/{len(vals)}"

    # 逐字抓錯
    want_total = sum(r["decisions"].get("flag_want", 0) for r in bad)
    dec_hit = sum(r["decisions"].get("flag_hit", 0) for r in bad)
    arg_hit = sum(r["argon"].get("flag_hit", 0) for r in bad)
    arg_want = sum(r["argon"].get("flag_want", 0) for r in bad)

    by_variant = defaultdict(lambda: {"n": 0, "dec": [], "arg": []})
    for r in rows:
        if not r.get("decisions", {}).get("ok"):
            continue
        g = by_variant[r["variant"]]
        g["n"] += 1
        g["dec"].append(r["decisions"]["p_correct"])
        if r["argon"].get("ok"):
            g["arg"].append(r["argon"]["overall"])

    # 尾靜音 A/B：只看無噪音的 correct 樣本
    ab = []
    if args.ab_pad:
        print("\n--- 尾靜音 A/B（不補靜音）---")
        for clip in [c for c in clips if c["variant"] == "correct"]:
            raw = (ROOT / clip["file"]).read_bytes()
            try:
                res = assess.assess(raw, "audio/mpeg", clip["target"], clip["lang"], thinking=args.thinking)
            except Exception:  # noqa: BLE001
                continue
            a = res["argon"]
            ab.append({"id": clip["id"], "ok": a.get("ok"), "overall": a.get("overall"),
                       "transcript": a.get("transcript"),
                       "missing": [w["token"] for w in a.get("words", []) if w.get("status") == "missing"]})
            print(f"  {clip['id']:24s} overall={a.get('overall')!s:>4s} "
                  f"漏掉={','.join(ab[-1]['missing']) or '-'} 「{(a.get('transcript') or '')[:40]}」")

    summary = {
        "samples": len(rows),
        "pad_seconds": None if args.no_pad else PAD_SECONDS,
        "ab_pad": {
            "n": len(ab),
            "mean_overall": round(sum(x["overall"] or 0 for x in ab) / len(ab), 1) if ab else None,
            "any_missing": sum(1 for x in ab if x["missing"]),
            "rows": ab,
        } if args.ab_pad else None,
        "decisions": {
            "auc": auc(dp_ok, dp_bad),
            "mean_p_correct_ok": round(sum(dp_ok) / len(dp_ok), 3) if dp_ok else None,
            "mean_p_correct_error": round(sum(dp_bad) / len(dp_bad), 3) if dp_bad else None,
            "accept_ok": accept_rate(dp_ok, DECIDE_ACCEPT),
            "accept_error": accept_rate(dp_bad, DECIDE_ACCEPT),
            "word_error_recall": f"{dec_hit}/{want_total}",
        },
        "argon": {
            "auc": auc(ao_ok, ao_bad),
            "mean_overall_ok": round(sum(ao_ok) / len(ao_ok), 1) if ao_ok else None,
            "mean_overall_error": round(sum(ao_bad) / len(ao_bad), 1) if ao_bad else None,
            "accept_ok": accept_rate(ao_ok, ARGON_ACCEPT),
            "accept_error": accept_rate(ao_bad, ARGON_ACCEPT),
            "word_error_recall": f"{arg_hit}/{arg_want}",
        },
        "by_variant": {k: {"n": v["n"],
                           "dec_mean": round(sum(v["dec"]) / len(v["dec"]), 3) if v["dec"] else None,
                           "arg_mean": round(sum(v["arg"]) / len(v["arg"]), 1) if v["arg"] else None}
                       for k, v in sorted(by_variant.items())},
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4),
        "latency_ms": {
            "decisions": round(sum(r["decisions"]["latency_ms"] or 0 for r in rows if r.get("decisions", {}).get("ok"))
                               / max(1, len(good) + len(bad))),
            "argon": round(sum(r["argon"]["latency_ms"] or 0 for r in rows if r.get("argon", {}).get("ok"))
                           / max(1, sum(1 for r in rows if r.get("argon", {}).get("ok")))),
        },
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== 摘要 ===")
    print(f"Decisions：AUC {summary['decisions']['auc']}　"
          f"正確句平均 P={summary['decisions']['mean_p_correct_ok']}、"
          f"錯誤句平均 P={summary['decisions']['mean_p_correct_error']}")
    print(f"  門檻 {DECIDE_ACCEPT}：正確句放行 {summary['decisions']['accept_ok']}、"
          f"錯誤句誤放 {summary['decisions']['accept_error']}　"
          f"逐字抓錯 {summary['decisions']['word_error_recall']}")
    print(f"Argon    ：AUC {summary['argon']['auc']}　"
          f"正確句平均 {summary['argon']['mean_overall_ok']}、錯誤句平均 {summary['argon']['mean_overall_error']}")
    print(f"  門檻 {ARGON_ACCEPT}：正確句放行 {summary['argon']['accept_ok']}、"
          f"錯誤句誤放 {summary['argon']['accept_error']}　逐字抓錯 {summary['argon']['word_error_recall']}")
    print(f"平均延遲：Decisions {summary['latency_ms']['decisions']} ms，Argon {summary['latency_ms']['argon']} ms")
    print(f"花費：US${summary['cost_usd']}")

    md = ["# 發音判斷基準結果", "", f"- 樣本：{summary['samples']}（TTS 合成）",
          f"- 花費：US${summary['cost_usd']}", "",
          "| 指標 | Decisions | Argon |", "| --- | --- | --- |",
          f"| AUC（正確 vs 錯誤） | {summary['decisions']['auc']} | {summary['argon']['auc']} |",
          f"| 正確句平均分 | {summary['decisions']['mean_p_correct_ok']} | {summary['argon']['mean_overall_ok']} |",
          f"| 錯誤句平均分 | {summary['decisions']['mean_p_correct_error']} | {summary['argon']['mean_overall_error']} |",
          f"| 正確句放行率 | {summary['decisions']['accept_ok']} | {summary['argon']['accept_ok']} |",
          f"| 錯誤句誤放率 | {summary['decisions']['accept_error']} | {summary['argon']['accept_error']} |",
          f"| 逐字抓錯 | {summary['decisions']['word_error_recall']} | {summary['argon']['word_error_recall']} |",
          "", "## 各變體平均分", "", "| 變體 | n | Decisions P | Argon 0-100 |", "| --- | --- | --- | --- |"]
    for k, v in summary["by_variant"].items():
        md.append(f"| {k} | {v['n']} | {v['dec_mean']} | {v['arg_mean']} |")
    SUMMARY.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n→ {OUT.relative_to(ROOT)}\n→ {SUMMARY.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
