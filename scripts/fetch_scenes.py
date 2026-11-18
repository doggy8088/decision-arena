#!/usr/bin/env python3
"""下載 YouTube 音訊並切出 10 秒測試片段（音場分類研究用）。

流程：yt-dlp 只抓指定時間窗的音訊 → ffmpeg 轉 24kHz 單聲道 → 切 10 秒
      → 量測能量特徵 → 寫入 data/scenes/manifest.json

用法：
  python3 scripts/fetch_scenes.py                 # 全部
  python3 scripts/fetch_scenes.py sp_jobs no_rain # 指定 id
  python3 scripts/fetch_scenes.py --force         # 已存在也重抓
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "data" / "scenes.json"
CLIP_DIR = ROOT / "data" / "scenes"
MANIFEST = CLIP_DIR / "manifest.json"

CLIP_SECONDS = 10.0
SR = 24000  # Gemini 內部會重採樣到 16k，24k 已足夠且檔案小


def run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)]).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def rms_profile(path: Path, sr: int = 8000, block: float = 0.5) -> list[float]:
    """把音訊解成 8kHz 單聲道並回傳每 0.5 秒的 RMS（0–1）。"""
    import array

    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr),
                           "-f", "s16le", "-"], capture_output=True, timeout=300)
    samples = array.array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    step = int(sr * block)
    prof = []
    for i in range(0, len(samples) - step + 1, step):
        chunk = samples[i : i + step]
        acc = 0
        for v in chunk[::4]:  # 每 4 點取樣一次，夠用且快
            acc += v * v
        prof.append((acc / max(1, len(chunk[::4]))) ** 0.5 / 32768.0)
    return prof


def pick_window(profile: list[float], block: float, need: float, total: float) -> float:
    """挑連續 need 秒、能量最穩定（min RMS 最大）的窗，避開頭尾 5%。"""
    wins = int(need / block)
    if len(profile) <= wins:
        return 0.0
    lo = int(len(profile) * 0.05)
    hi = max(lo + 1, len(profile) - wins - int(len(profile) * 0.05))
    best, best_key = 0.0, -1.0
    for i in range(lo, hi):
        w = profile[i : i + wins]
        key = min(w) * 0.7 + (sum(w) / len(w)) * 0.3
        if key > best_key:
            best_key, best = key, i * block
    return best


def astats(path: Path) -> dict:
    out = run(["ffmpeg", "-v", "info", "-i", str(path), "-af", "astats=metadata=1:reset=0",
               "-f", "null", "-"]).stderr
    vals = {}
    for key in ("RMS level dB", "Peak level dB", "Flat factor", "Noise floor dB"):
        m = re.findall(rf"{key}:\s*(-?[\d.]+|-?inf)", out)
        if m:
            vals[key.replace(" ", "_")] = m[-1]
    return vals


def fetch_one(src: dict, force: bool = False) -> dict:
    cid, cat = src["id"], src["cat"]
    outdir = CLIP_DIR / cat
    outdir.mkdir(parents=True, exist_ok=True)
    final = outdir / f"{cid}.mp3"
    if final.is_file() and not force:
        meta = json.loads((outdir / f"{cid}.json").read_text()) if (outdir / f"{cid}.json").is_file() else {}
        return {"id": cid, "cat": cat, "file": str(final.relative_to(ROOT)), "cached": True, **meta}

    url = f"https://www.youtube.com/watch?v={src['video']}"
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        # 先抓 metadata，決定下載窗口
        info_raw = run(["yt-dlp", "--no-warnings", "--no-playlist", "-J", url], timeout=180).stdout
        if not info_raw.strip():
            raise RuntimeError("metadata 取得失敗")
        info = json.loads(info_raw)
        vdur = float(info.get("duration") or 0)

        # 只下載需要的一小段（長影片省頻寬）
        if vdur and vdur > 120:
            start = max(0, int(src.get("start") or 0) - 15)
            end = min(int(vdur), start + 70)
            section = ["--download-sections", f"*{start}-{end}"]
            offset = float(start)
        else:
            section, offset = [], 0.0

        tmpl = str(tdp / "src.%(ext)s")
        dl = run(["yt-dlp", "--no-warnings", "--no-playlist", "-f", "bestaudio/best",
                  "-x", "--audio-format", "wav", "--postprocessor-args", f"-ar {SR} -ac 1",
                  *section, "-o", tmpl, url], timeout=900)
        wav = next(iter(tdp.glob("src.wav")), None)
        if wav is None:
            raise RuntimeError("下載失敗：" + (dl.stderr or "")[-400:])

        total = probe_duration(wav)
        if src.get("start") is None:
            prof = rms_profile(wav)
            start_in = pick_window(prof, 0.5, CLIP_SECONDS, total)
            method = "auto-energy"
        else:
            start_in = float(src["start"]) - offset
            method = "manual"
        start_in = max(0.0, min(start_in, max(0.0, total - CLIP_SECONDS)))

        cut = run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start_in:.2f}", "-t", f"{CLIP_SECONDS}",
                   "-i", str(wav), "-ac", "1", "-ar", str(SR), "-c:a", "libmp3lame",
                   "-b:a", "96k", str(final)])
        if not final.is_file():
            raise RuntimeError("切檔失敗：" + cut.stderr[-400:])

        meta = {
            "video": src["video"],
            "url": url,
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "video_duration": vdur,
            "clip_start_in_video": round(offset + start_in, 2),
            "clip_seconds": round(probe_duration(final), 2),
            "window_method": method,
            "note": src.get("note"),
            "astats": astats(final),
        }
        (outdir / f"{cid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                                            encoding="utf-8")
    return {"id": cid, "cat": cat, "file": str(final.relative_to(ROOT)), **meta}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()

    if not shutil.which("yt-dlp") or not shutil.which("ffmpeg"):
        sys.exit("需要 yt-dlp 與 ffmpeg")

    cfg = json.loads(SCENES.read_text(encoding="utf-8"))
    sources = cfg["sources"]
    if args.ids:
        wanted = set(args.ids)
        sources = [s for s in sources if s["id"] in wanted]
        if not sources:
            sys.exit("找不到指定的 id")

    ok, failed = [], []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(fetch_one, s, args.force): s for s in sources}
        for fut, src in futures.items():
            try:
                rec = fut.result()
                ok.append(rec)
                print(f"✅ {src['id']:16s} {rec.get('title', '')[:50]} @ {rec.get('clip_start_in_video')}s")
            except Exception as exc:  # noqa: BLE001
                failed.append({"id": src["id"], "cat": src["cat"], "error": str(exc)[:300]})
                print(f"❌ {src['id']:16s} {str(exc)[:120]}")

    if MANIFEST.is_file():
        prev = json.loads(MANIFEST.read_text(encoding="utf-8"))
        by_id = {c["id"]: c for c in prev.get("clips", [])}
    else:
        by_id = {}
    for rec in ok:
        by_id[rec["id"]] = rec
    manifest = {
        "clip_seconds": CLIP_SECONDS,
        "categories": cfg["categories"],
        "clips": sorted(by_id.values(), key=lambda r: (r["cat"], r["id"])),
        "failed": failed,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    by_cat: dict[str, int] = {}
    for c in manifest["clips"]:
        by_cat[c["cat"]] = by_cat.get(c["cat"], 0) + 1
    print("\n=== 統計 ===")
    for cat in cfg["categories"]:
        print(f"{cat:14s} {by_cat.get(cat, 0)}")
    print(f"總計 {len(manifest['clips'])} 段，失敗 {len(failed)} 段 → {MANIFEST.relative_to(ROOT)}")
    if failed:
        for f in failed:
            print("  failed:", f["id"], f["error"][:120])


if __name__ == "__main__":
    main()
