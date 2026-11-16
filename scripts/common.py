"""共用工具：載入標註、呼叫 Gemini API。

只使用 Python 標準函式庫（urllib），不需要安裝任何套件。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "out"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        sys.exit("缺少 GEMINI_API_KEY 環境變數。請先 export GEMINI_API_KEY=...")
    return key


def load_clips() -> list[dict]:
    raw = json.loads((DATA / "labels.json").read_text(encoding="utf-8"))
    clips = raw["clips"]
    for clip in clips:
        if not (ROOT / clip["file"]).is_file():
            sys.exit(f"找不到音檔：{clip['file']}")
    return clips


def b64_audio(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def _post(url: str, body: dict, timeout: int = 180) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            raise RuntimeError(f"HTTP {exc.code}：{payload[:300]}")


def generate(model: str, prompt: str, audio: Path, thinking: str | None = None) -> str:
    """呼叫 generateContent，回傳模型輸出的純文字。"""
    body: dict = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": "audio/mpeg", "data": b64_audio(audio)}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0},
    }
    if thinking:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking}

    result = _post(f"{API_BASE}/models/{model}:generateContent?key={api_key()}", body)
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "unknown error"))
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        raise RuntimeError("回應沒有文字內容：" + json.dumps(result, ensure_ascii=False)[:300])


def decide(audio: Path, questions: dict) -> dict:
    """呼叫 Decisions API（gemini-decision-1）。

    音訊必須用扁平結構：{"type":"audio","mime_type":..., "data":<base64>}。
    實測 inline_data / inlineData / content 都會被拒絕。
    """
    body = {
        "model": "gemini-decision-1",
        "input": [{"type": "audio", "mime_type": "audio/mpeg", "data": b64_audio(audio)}],
        "questions": questions,
    }
    result = _post(f"{API_BASE}/decisions?key={api_key()}", body)
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "unknown error"))
    return result


def save(name: str, payload: dict) -> Path:
    OUT.mkdir(exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def fmt_probs(probabilities: dict) -> str:
    if not probabilities:
        return "-"
    ordered = sorted(probabilities.items(), key=lambda kv: -kv[1])
    return " ".join(f"{k}={v:.2f}" for k, v in ordered)
