#!/usr/bin/env python3
"""發音練習 Web App 後端（僅標準函式庫）。

端點：
  GET  /                    前端頁面
  GET  /api/sentences       題庫
  GET  /api/health          環境檢查
  POST /api/assess          送出錄音 → Decisions + Argon 雙模型判讀
  POST /api/feedback        研究回饋（哪個模型準、小朋友反應、備註）
  GET  /api/records         最近的紀錄
  GET  /api/export          匯出 CSV
  GET  /api/stats           累計成本與次數

啟動：
  export GEMINI_API_KEY=...
  python3 app/server.py --port 8765
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import assess  # noqa: E402
import gemini  # noqa: E402

APP = Path(__file__).resolve().parent
STATIC = APP / "static"
DATA = APP / "data"
RECORDINGS = DATA / "recordings"
RECORDS = DATA / "records.jsonl"
FEEDBACK = DATA / "feedback.jsonl"
LEDGER = DATA / "cost.json"
SENTENCES = APP / "sentences.json"

TZ = timezone(timedelta(hours=8))
MAX_BODY = 12 * 1024 * 1024
AUDIO_EXT = {
    "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3",
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/flac": "flac", "audio/aac": "aac",
    "audio/opus": "opus",
}

_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def record_id() -> str:
    return datetime.now(TZ).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with _lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def add_cost(kind: str, usd: float) -> dict:
    with _lock:
        state = {"decisions_usd": 0.0, "argon_usd": 0.0, "calls": 0, "assessments": 0}
        if LEDGER.is_file():
            try:
                state.update(json.loads(LEDGER.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        state[f"{kind}_usd"] = round(state.get(f"{kind}_usd", 0.0) + usd, 6)
        state["calls"] = state.get("calls", 0) + 1
        state["assessments"] = state.get("assessments", 0) + (1 if kind == "argon" else 0)
        LEDGER.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        return state


def total_cost() -> float:
    if not LEDGER.is_file():
        return 0.0
    try:
        s = json.loads(LEDGER.read_text(encoding="utf-8"))
        return round(s.get("decisions_usd", 0) + s.get("argon_usd", 0), 6)
    except json.JSONDecodeError:
        return 0.0


PAD_SECONDS = 0.6


def prepare_audio(audio: bytes, mime: str) -> tuple[bytes, str, dict]:
    """轉成 mp3 並補尾靜音。

    實測（見 README）：Gemini 對「結尾沒有靜音」的短音檔會漏聽最後 1–3 個字，
    補 0.6 秒靜音後就恢復正常。孩子唸完常立刻按停止，這個補償是必要的。
    沒有 ffmpeg 就原樣送出，並在回傳值標記。
    """
    ff = shutil.which("ffmpeg")
    if not ff:
        return audio, mime, {"padded": False, "converted": False, "reason": "no ffmpeg"}
    ext = AUDIO_EXT.get(mime, "webm")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in.{ext}"
        dst = Path(td) / "out.mp3"
        src.write_bytes(audio)
        proc = subprocess.run(
            [ff, "-v", "error", "-y", "-i", str(src),
             "-af", f"apad=pad_dur={PAD_SECONDS}", "-ac", "1", "-ar", "24000",
             "-c:a", "libmp3lame", "-b:a", "96k", str(dst)],
            capture_output=True, timeout=60,
        )
        if proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 800:
            return dst.read_bytes(), "audio/mpeg", {"padded": True, "converted": True}
        return audio, mime, {"padded": False, "converted": False,
                             "reason": proc.stderr.decode(errors="replace")[-200:]} 



class Handler(BaseHTTPRequestHandler):
    server_version = "PronunciationLab/1.0"

    def log_message(self, fmt, *args):  # 安靜一點，只留錯誤
        if args and str(args[1]).startswith(("4", "5")):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------- helpers ----------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, payload: dict):
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("空的要求內容")
        if length > MAX_BODY:
            raise ValueError("錄音檔過大（上限 12MB）")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _static(self, rel: str):
        path = (STATIC / rel).resolve()
        if not str(path).startswith(str(STATIC.resolve())) or not path.is_file():
            self._json(404, {"error": "not found"})
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        if path.suffix in (".html", ".css"):
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    # ---------- routes ----------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._static("index.html")
        elif path == "/api/sentences":
            self._json(200, json.loads(SENTENCES.read_text(encoding="utf-8")))
        elif path == "/api/health":
            self._json(200, {
                "ok": bool(os.environ.get("GEMINI_API_KEY")),
                "decisions_model": gemini.DECISION_MODEL,
                "judge_model": gemini.JUDGE_MODEL,
                "cost_usd": total_cost(),
                "server_time": now_iso(),
            })
        elif path == "/api/stats":
            state = {"decisions_usd": 0.0, "argon_usd": 0.0, "calls": 0, "assessments": 0}
            if LEDGER.is_file():
                state.update(json.loads(LEDGER.read_text(encoding="utf-8")))
            state["cost_usd"] = round(state.get("decisions_usd", 0) + state.get("argon_usd", 0), 6)
            feedback = {f.get("record_id"): f for f in read_jsonl(FEEDBACK)}
            state["records"] = len(read_jsonl(RECORDS))
            state["rated"] = len(feedback)
            self._json(200, state)
        elif path == "/api/records":
            limit = 50
            if "limit=" in self.path:
                try:
                    limit = max(1, min(500, int(self.path.split("limit=")[1].split("&")[0])))
                except ValueError:
                    pass
            recs = read_jsonl(RECORDS)[-limit:][::-1]
            fb = {f.get("record_id"): f for f in read_jsonl(FEEDBACK)}
            for r in recs:
                r["feedback"] = fb.get(r.get("record_id"))
            self._json(200, {"records": recs})
        elif path == "/api/export":
            self._export()
        elif path.startswith("/recordings/"):
            name = Path(path).name
            target = RECORDINGS / name
            if not target.is_file():
                self._json(404, {"error": "not found"})
                return
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), ctype)
        else:
            self._static(path.lstrip("/"))

    def _export(self):
        recs = read_jsonl(RECORDS)
        fb = {f.get("record_id"): f for f in read_jsonl(FEEDBACK)}
        buf = io.StringIO()
        cols = ["record_id", "created_at", "sentence", "lang", "speaker", "audio_file",
                "decisions_p_correct", "decisions_level", "decisions_cost_usd", "decisions_ms",
                "decisions_words_wrong", "argon_overall", "argon_transcript",
                "argon_words_wrong", "argon_cost_usd", "argon_ms", "agreement_rate",
                "fb_decisions", "fb_argon", "fb_blind", "fb_child", "fb_note"]
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for r in recs:
            d = (r.get("result") or {}).get("decisions") or {}
            a = (r.get("result") or {}).get("argon") or {}
            ag = (r.get("result") or {}).get("agreement") or {}
            f = fb.get(r.get("record_id")) or {}
            writer.writerow({
                "record_id": r.get("record_id"),
                "created_at": r.get("created_at"),
                "sentence": r.get("sentence"),
                "lang": r.get("lang"),
                "speaker": r.get("speaker"),
                "audio_file": r.get("audio_file"),
                "decisions_p_correct": d.get("p_correct"),
                "decisions_level": d.get("level"),
                "decisions_cost_usd": d.get("cost_usd"),
                "decisions_ms": d.get("latency_ms"),
                "decisions_words_wrong": ",".join(w["token"] for w in d.get("words", [])
                                                  if w.get("verdict") not in ("correct", None)),
                "argon_overall": a.get("overall"),
                "argon_transcript": a.get("transcript"),
                "argon_words_wrong": ",".join(w["token"] for w in a.get("words", [])
                                              if w.get("status") not in ("correct", None)),
                "argon_cost_usd": a.get("cost_usd"),
                "argon_ms": a.get("latency_ms"),
                "agreement_rate": ag.get("rate") or (ag.get("decisions_vs_blind") or {}).get("rate"),
                "fb_decisions": f.get("decisions_verdict"),
                "fb_argon": f.get("argon_verdict"),
                "fb_blind": f.get("blind_verdict"),
                "fb_child": f.get("child_reaction"),
                "fb_note": f.get("note"),
            })
        body = buf.getvalue().encode("utf-8-sig")
        self._send(200, body, "text/csv; charset=utf-8",
                   {"Content-Disposition": 'attachment; filename="pronunciation-research.csv"'})

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            payload = self._body()
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
            return

        if path == "/api/assess":
            self._assess(payload)
        elif path == "/api/feedback":
            self._feedback(payload)
        else:
            self._json(404, {"error": "not found"})

    def _assess(self, payload: dict):
        import base64

        sentence = (payload.get("sentence") or "").strip()
        lang = payload.get("lang") or "en"
        if not sentence:
            self._json(400, {"error": "缺少句子"})
            return
        if lang not in ("en", "zh"):
            self._json(400, {"error": "lang 只能是 en 或 zh"})
            return
        b64 = payload.get("audio") or ""
        try:
            audio = base64.b64decode(b64.split(",")[-1])
        except Exception:  # noqa: BLE001
            self._json(400, {"error": "音訊 base64 解析失敗"})
            return
        if len(audio) < 800:
            self._json(400, {"error": "錄音太短或為空，請重新錄音"})
            return

        mime = (payload.get("mime") or "audio/webm").split(";")[0].strip()
        mime = mime if mime in AUDIO_EXT else "audio/webm"
        thinking = payload.get("thinking") if payload.get("thinking") in ("low", "high") else "low"

        rid = record_id()
        RECORDINGS.mkdir(parents=True, exist_ok=True)
        audio_name = f"{rid}.{AUDIO_EXT[mime]}"
        (RECORDINGS / audio_name).write_bytes(audio)

        send_audio, send_mime, prep = prepare_audio(audio, mime)

        t0 = time.perf_counter()
        try:
            result = assess.assess(send_audio, send_mime, sentence, lang, thinking=thinking)
        except gemini.GeminiError as exc:
            self._json(502, {"error": f"模型呼叫失敗：{exc}", "record_id": rid})
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"error": f"內部錯誤：{exc}", "record_id": rid})
            return
        elapsed = round((time.perf_counter() - t0) * 1000)

        state = add_cost("decisions", (result["decisions"] or {}).get("cost_usd") or 0)
        state = add_cost("argon", (result["argon"] or {}).get("cost_usd") or 0)

        record = {
            "record_id": rid,
            "created_at": now_iso(),
            "sentence": sentence,
            "lang": lang,
            "sentence_id": payload.get("sentence_id"),
            "speaker": payload.get("speaker") or "",
            "speaker_note": payload.get("speaker_note") or "",
            "audio_file": f"recordings/{audio_name}",
            "audio_bytes": len(audio),
            "audio_ms": payload.get("audio_ms"),
            "mime": mime,
            "sent_mime": send_mime,
            "audio_prep": prep,
            "thinking": thinking,
            "wall_ms": elapsed,
            "result": result,
        }
        append_jsonl(RECORDS, record)

        self._json(200, {
            "record_id": rid,
            "sentence": sentence,
            "lang": lang,
            "wall_ms": elapsed,
            "result": result,
            "cost_usd": result.get("cost_usd"),
            "total_cost_usd": round(state.get("decisions_usd", 0) + state.get("argon_usd", 0), 6),
        })

    def _feedback(self, payload: dict):
        rid = payload.get("record_id")
        if not rid:
            self._json(400, {"error": "缺少 record_id"})
            return
        entry = {
            "record_id": rid,
            "created_at": now_iso(),
            "decisions_verdict": payload.get("decisions_verdict"),
            "argon_verdict": payload.get("argon_verdict"),
            "blind_verdict": payload.get("blind_verdict"),
            "child_reaction": payload.get("child_reaction"),
            "rater": payload.get("rater") or "",
            "note": (payload.get("note") or "")[:2000],
        }
        append_jsonl(FEEDBACK, entry)
        self._json(200, {"ok": True, "saved": entry})


def main() -> None:
    ap = argparse.ArgumentParser(description="發音練習 Web App")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("缺少 GEMINI_API_KEY 環境變數")
    for p in (STATIC / "index.html", SENTENCES):
        if not p.is_file():
            sys.exit(f"缺少檔案：{p}")

    DATA.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    print(f"發音練習 App 已啟動 → http://{args.host}:{args.port}")
    print(f"資料目錄：{DATA}")
    print(f"目前已花費：US${total_cost():.4f}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
