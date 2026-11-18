#!/usr/bin/env python3
"""替指定片段重新找「有語音」的時間窗。

做法：下載一次音訊（長片只抓前 8 分鐘），對多個候選起點各切 10 秒，
用 Groq Whisper 轉錄，挑字數最多（＝真的有人在講話／唱歌）的窗。

用法：
  python3 scripts/probe_windows.py sm_sprite sm_vlog sg_despacito
  python3 scripts/probe_windows.py --patch ...   # 找到最佳窗後寫回 data/scenes.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "data" / "scenes.json"
SR = 24000
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def sh(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def download(video: str, td: Path, max_seconds: int = 480) -> Path:
    tmpl = str(td / "full.%(ext)s")
    sh(["yt-dlp", "--no-warnings", "--no-playlist", "-f", "bestaudio/best", "-x",
        "--audio-format", "wav", "--postprocessor-args", f"-ar {SR} -ac 1",
        "--download-sections", f"*0-{max_seconds}", "-o", tmpl,
        f"https://www.youtube.com/watch?v={video}"])
    wav = next(iter(td.glob("full.wav")), None)
    if wav is None:
        raise RuntimeError("下載失敗")
    return wav


def cut(wav: Path, start: float, out: Path) -> bool:
    r = sh(["ffmpeg", "-v", "error", "-y", "-ss", f"{start}", "-t", "10", "-i", str(wav),
            "-ac", "1", "-ar", str(SR), "-c:a", "libmp3lame", "-b:a", "96k", str(out)])
    return out.is_file() and r.returncode == 0


def words(path: Path) -> tuple[int, str]:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    boundary = uuid.uuid4().hex
    body = bytearray()
    for k, v in {"model": "whisper-large-v3", "response_format": "json", "temperature": "0"}.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{path.name}\"\r\nContent-Type: audio/mpeg\r\n\r\n").encode()
    body += path.read_bytes() + b"\r\n" + (f"--{boundary}--\r\n").encode()
    req = urllib.request.Request(GROQ_URL, data=bytes(body), headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "curl/8.7.1",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        text = (json.loads(resp.read().decode()).get("text") or "").strip()
    return len(text.split()), text


def probe(entry: dict, patch: bool) -> dict:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        wav = download(entry["video"], tdp)
        dur = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(wav)]).stdout.strip() or 0)
        cands = [5, 20, 40, 60, 90, 120, 150, 180, 210, 240, 270, 300]
        cands = [c for c in cands if c + 10 <= dur]
        if not cands:
            cands = [0]

        def one(start: float):
            out = tdp / f"c{int(start)}.mp3"
            if not cut(wav, start, out):
                return start, -1, ""
            try:
                n, text = words(out)
                return start, n, text
            except Exception as exc:  # noqa: BLE001
                return start, -2, str(exc)[:80]

        results = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            for start, n, text in pool.map(one, cands):
                results.append({"start": start, "words": n, "text": text})
                print(f"    {entry['id']:16s} @{start:4.0f}s words={n:3d} {text[:60]}")

    valid = [r for r in results if r["words"] > 0]
    best = max(valid, key=lambda r: r["words"]) if valid else None
    if best and patch:
        raw = json.loads(SCENES.read_text(encoding="utf-8"))
        for src in raw["sources"]:
            if src["id"] == entry["id"]:
                src["start"] = int(best["start"])
                src["note"] = (src.get("note") or "") + f"（改窗至 {best['start']}s）"
        SCENES.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  ✏️  {entry['id']} 起點改為 {best['start']}s（{best['words']} 字）")
    return {"id": entry["id"], "best": best, "all": results}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--patch", action="store_true")
    args = ap.parse_args()
    raw = json.loads(SCENES.read_text(encoding="utf-8"))
    targets = [s for s in raw["sources"] if not args.ids or s["id"] in set(args.ids)]
    for entry in targets:
        print(f"\n▶ {entry['id']} ({entry['cat']}) {entry['video']}")
        probe(entry, args.patch)


if __name__ == "__main__":
    main()
