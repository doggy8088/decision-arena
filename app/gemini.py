"""Gemini API 用戶端（App 專用）。

只依賴標準函式庫。提供：
  - decide()        → gemini-decision-1（noul／choice／score）
  - generate()      → 生成式模型（預設 gemini-4-argon），支援 JSON schema
  - estimate_cost() → 依 usage 估算美元成本

價格為 2026-11 官方牌價（Argon 為 2026-11-30 前促銷價），只當估算用。
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DECISION_MODEL = "gemini-decision-1"
JUDGE_MODEL = "gemini-4-argon"

# per 1M tokens: (text in, audio in, text out)
PRICES = {
    "gemini-decision-1": (0.10, 0.10, 0.0),
    "gemini-4-argon": (2.00, 2.00, 10.00),
    "gemini-3.8-flash": (0.75, 3.00, 3.75),
    "gemini-3.1-flash-lite": (0.25, 0.50, 1.50),
}


class GeminiError(RuntimeError):
    pass


def api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise GeminiError("缺少 GEMINI_API_KEY 環境變數")
    return key


def _post(path: str, body: dict, timeout: int = 180) -> dict:
    request = urllib.request.Request(
        f"{API_BASE}/{path}?key={api_key()}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise GeminiError(f"HTTP {exc.code}：{raw[:300]}") from exc
    except urllib.error.URLError as exc:
        raise GeminiError(f"網路錯誤：{exc.reason}") from exc

    if "error" in payload:
        raise GeminiError(payload["error"].get("message", "unknown error"))
    return payload


def decide(audio: bytes, mime: str, questions: dict, timeout: int = 120) -> dict:
    """Decisions API：音訊必須是扁平結構 {type, mime_type, data}。"""
    body = {
        "model": DECISION_MODEL,
        "input": [{"type": "audio", "mime_type": mime, "data": base64.b64encode(audio).decode()}],
        "questions": questions,
    }
    result = _post("decisions", body, timeout=timeout)
    result["_elapsed"] = None
    return result


def generate(
    prompt: str,
    audio: bytes | None = None,
    mime: str = "audio/webm",
    model: str = JUDGE_MODEL,
    thinking: str | None = "low",
    response_schema: dict | None = None,
    temperature: float = 0,
    timeout: int = 180,
) -> dict:
    parts: list[dict] = [{"text": prompt}]
    if audio is not None:
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(audio).decode()}})
    gen_cfg: dict = {"temperature": temperature}
    if thinking:
        gen_cfg["thinkingConfig"] = {"thinkingLevel": thinking}
    if response_schema:
        gen_cfg["responseMimeType"] = "application/json"
        gen_cfg["responseSchema"] = response_schema

    result = _post(f"models/{model}:generateContent", {"contents": [{"parts": parts}],
                                                       "generationConfig": gen_cfg}, timeout=timeout)
    try:
        candidate = result["candidates"][0]
        text = "".join(p.get("text", "") for p in candidate["content"]["parts"]).strip()
    except (KeyError, IndexError) as exc:
        raise GeminiError("回應沒有內容：" + json.dumps(result, ensure_ascii=False)[:300]) from exc
    return {"text": text, "usage": result.get("usageMetadata", {}),
            "finish_reason": candidate.get("finishReason"), "blocked": not text}


def estimate_cost(model: str, usage: dict) -> float:
    """依 usageMetadata 估成本（美元）。

    Decisions 回 snake_case（input_tokens_by_modality / total_input_tokens），
    生成式模型回 camelCase（promptTokensDetails / promptTokenCount），兩種都要吃。
    """
    if not usage:
        return 0.0
    price = PRICES.get(model)
    if not price:
        return 0.0
    text_in, audio_in, text_out = price

    by_mod: dict[str, int] = {}
    for d in usage.get("input_tokens_by_modality") or usage.get("inputTokensByModality") or []:
        by_mod[d.get("modality", "")] = d.get("tokens") or d.get("tokenCount") or 0
    if not by_mod:
        for d in usage.get("promptTokensDetails") or []:
            by_mod[d.get("modality", "").lower()] = d.get("tokenCount") or 0

    if by_mod:
        tin = by_mod.get("text", 0)
        ain = by_mod.get("audio", 0)
    else:
        total = usage.get("total_input_tokens") or usage.get("promptTokenCount") or 0
        tin, ain = total, 0

    tout = (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0)
    tout += usage.get("total_output_tokens") or 0
    return (tin * text_in + ain * audio_in + tout * text_out) / 1_000_000


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = round((time.perf_counter() - self.t0) * 1000)
        return False
