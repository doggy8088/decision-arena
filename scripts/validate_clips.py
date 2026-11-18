#!/usr/bin/env python3
"""用 Groq Whisper 獨立驗證片段標註（不依賴 Gemini，避免循環論證）。

對每個片段取得逐段轉錄與 no_speech_prob，據此檢查：
  - music / noise 應該「沒有語音」
  - speech / multi_speech / speech_music 應該「有語音」
  - singing / concert 允許兩者（唱歌可能被轉出歌詞，也可能沒有）

用法：
  export GROQ_API_KEY=...
  python3 scripts/validate_clips.py
輸出：out/clip-validation.json，並印出可疑片段
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "scenes" / "manifest.json"
OUT = ROOT / "out" / "clip-validation.json"
URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3"

EXPECT_VOICE = {
    "speech": "voice",
    "multi_speech": "voice",
    "speech_music": "voice",
    "music": "silent",
    "noise": "silent",
    "singing": "either",
    "concert": "either",
}


def transcribe(path: Path) -> dict:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        sys.exit("缺少 GROQ_API_KEY")
    boundary = uuid.uuid4().hex
    body = bytearray()
    fields = {"model": MODEL, "response_format": "verbose_json", "language": "en",
              "temperature": "0"}
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{path.name}\"\r\nContent-Type: audio/mpeg\r\n\r\n").encode()
    body += path.read_bytes() + b"\r\n"
    body += (f"--{boundary}--\r\n").encode()

    req = urllib.request.Request(URL, data=bytes(body), headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        # urllib 預設 UA 會被 Cloudflare 以 1010 擋掉，必須換成一般 UA
        "User-Agent": "curl/8.7.1",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows, suspicious = [], []

    for clip in manifest["clips"]:
        path = ROOT / clip["file"]
        try:
            r = transcribe(path)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  {clip['id']:16s} 轉錄失敗：{str(exc)[:100]}")
            continue
        segs = r.get("segments", []) or []
        nsp = [s.get("no_speech_prob", 0) for s in segs] or [1.0]
        text = (r.get("text") or "").strip()
        words = len(text.split())
        row = {
            "id": clip["id"],
            "cat": clip["cat"],
            "title": clip.get("title"),
            "text": text,
            "words": words,
            "segments": len(segs),
            "no_speech_mean": round(statistics.mean(nsp), 3),
            "no_speech_max": round(max(nsp), 3),
            "avg_logprob": round(statistics.mean([s.get("avg_logprob", 0) for s in segs]), 3) if segs else None,
            "expect": EXPECT_VOICE[clip["cat"]],
        }
        # 判定「有語音」：有字且（平均 no_speech_prob 低於 0.5 或字數 >= 6）
        has_voice = words >= 3 and row["no_speech_mean"] < 0.6
        row["asr_voice"] = has_voice
        expect = row["expect"]
        mismatch = (expect == "voice" and not has_voice) or (expect == "silent" and has_voice)
        row["mismatch"] = mismatch
        rows.append(row)
        if mismatch:
            suspicious.append(row)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'clip':16s} {'cat':13s} {'字數':>4s} {'no_speech':>9s} {'判定':6s} 文字")
    print("-" * 92)
    for r in rows:
        flag = "⚠️" if r["mismatch"] else "  "
        print(f"{flag}{r['id']:14s} {r['cat']:13s} {r['words']:4d} "
              f"{r['no_speech_mean']:9.2f} {'voice' if r['asr_voice'] else 'silent':6s} "
              f"{r['text'][:46]}")

    print(f"\n共 {len(rows)} 段，可疑 {len(suspicious)} 段")
    for r in suspicious:
        print(f"  ⚠️  {r['id']}（{r['cat']}）字數 {r['words']}、no_speech {r['no_speech_mean']}：{r['text'][:70]}")
    print(f"\n結果 → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
