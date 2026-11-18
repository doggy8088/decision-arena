#!/usr/bin/env python3
"""用 macOS `say` 合成發音基準語料（正確句 + 刻意錯誤句）。

每個變體輸出 data/pron/<item>__<variant>.mp3（24kHz 單聲道）。
另外為每個 correct 產生一份加了粉紅噪音的版本（SNR 約 12 dB），
模擬家用／教室環境，用來檢查背景噪音會不會讓判斷失準。

用法：
  python3 scripts/build_pron_corpus.py
  python3 scripts/build_pron_corpus.py --force
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ROOT / "data" / "pron" / "variants.json"
OUTDIR = ROOT / "data" / "pron"
MANIFEST = OUTDIR / "manifest.json"
SR = 24000
SNR_DB = 12


def sh(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def rms_db(path: Path) -> float:
    out = sh(["ffmpeg", "-v", "info", "-i", str(path), "-af", "astats=metadata=1:reset=0",
              "-f", "null", "-"]).stderr
    vals = re.findall(r"RMS level dB:\s*(-?[\d.]+|-inf)", out)
    try:
        return float(vals[-1])
    except (IndexError, ValueError):
        return -30.0


def synth(text: str, voice: str, dest: Path, aiff: Path) -> None:
    r = sh(["say", "-v", voice, "-o", str(aiff), text])
    if not aiff.is_file():
        raise RuntimeError(f"say 失敗：{r.stderr[:200]}")
    r = sh(["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", str(SR),
            "-c:a", "libmp3lame", "-b:a", "96k", str(dest)])
    if not dest.is_file():
        raise RuntimeError(f"ffmpeg 失敗：{r.stderr[:200]}")


def add_noise(src: Path, dest: Path, snr_db: float = SNR_DB) -> None:
    dur = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", str(src)]).stdout.strip() or 3)
    target_db = rms_db(src) - snr_db
    amp = min(0.5, 10 ** (target_db / 20))
    sh(["ffmpeg", "-v", "error", "-y", "-i", str(src),
        "-f", "lavfi", "-i", f"anoisesrc=d={dur:.2f}:c=pink:r={SR}:a={amp:.4f}:seed=42",
        "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0",
        "-ac", "1", "-ar", str(SR), "-c:a", "libmp3lame", "-b:a", "96k", str(dest)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = json.loads(VARIANTS.read_text(encoding="utf-8"))
    voices = cfg["voices"]
    OUTDIR.mkdir(parents=True, exist_ok=True)
    clips = []

    for item in cfg["items"]:
        for name, spec in item["variants"].items():
            dest = OUTDIR / f"{item['id']}__{name}.mp3"
            if args.force or not dest.is_file():
                with tempfile.TemporaryDirectory() as td:
                    synth(spec["text"], voices[item["lang"]], dest, Path(td) / "v.aiff")
            clips.append({
                "id": f"{item['id']}__{name}",
                "item": item["id"],
                "lang": item["lang"],
                "variant": name,
                "target": item["target"],
                "spoken": spec["text"],
                "gold": spec["gold"],
                "expect_flag": spec.get("expect_flag"),
                "why": spec.get("why"),
                "file": str(dest.relative_to(ROOT)),
                "noisy": False,
            })
            # 正確句另外產生加噪版本
            if name == "correct":
                noisy = OUTDIR / f"{item['id']}__correct_noisy.mp3"
                if args.force or not noisy.is_file():
                    add_noise(dest, noisy)
                clips.append({
                    "id": f"{item['id']}__correct_noisy",
                    "item": item["id"],
                    "lang": item["lang"],
                    "variant": "correct_noisy",
                    "target": item["target"],
                    "spoken": spec["text"],
                    "gold": "ok",
                    "expect_flag": None,
                    "why": f"正確句 + SNR {SNR_DB}dB 粉紅噪音",
                    "file": str(noisy.relative_to(ROOT)),
                    "noisy": True,
                })
            print(f"✅ {item['id']:6s} {name:13s} {dest.name}")

    MANIFEST.write_text(json.dumps({"snr_db": SNR_DB, "clips": clips}, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    ok = sum(1 for c in clips if c["gold"] == "ok")
    print(f"\n共 {len(clips)} 個樣本（正確 {ok}、錯誤 {len(clips) - ok}）")
    print(f"→ {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
