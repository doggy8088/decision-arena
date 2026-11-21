"""Google Gemini Decisions API（gemini-decision-1）。

已在本專案實測確認的格式（研究一～三）：
- ``POST {base}/decisions?key=...``，body ``{model, input:[...], questions:{name:{...}}}``
- 媒體輸入必須是扁平結構 ``{"type":"audio","mime_type":...,"data":<base64>}``；
  ``inline_data`` / ``inlineData`` 都會被拒絕。圖片沿用同一結構（type=image）。
- 是非題型別叫 ``noul``，回 ``answers[name]["noul"]`` = P(yes)；
  單選題 ``choice`` 帶 ``criteria``，回 ``answers[name]["probabilities"]``。
- 用量在 ``usage.total_input_tokens``。
"""
from __future__ import annotations

from ..schema import Part, Question
from .base import Answer, ModelInfo, Provider, ProviderError, Request
from .openrouter import option_keys

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
QNAME = "q"


class GeminiDecision(Provider):
    info = ModelInfo(
        id="gemini-decision-1",
        vendor="Google",
        api_model="gemini-decision-1",
        documented_modalities=("text", "image", "audio", "video", "pdf"),
        env_keys=("GEMINI_API_KEY",),
        usd_per_m_input=0.10,
        docs="https://aistudio.google.com/docs/decisions-api",
        notes="2026-11-11 推出；本專案研究一～三的主角。",
    )

    def part(self, p: Part) -> dict:
        if p.type == "text":
            return {"type": "text", "text": p.text}
        return {"type": p.type, "mime_type": p.mime, "data": self.b64(p)}

    def question(self, q: Question) -> dict:
        if q.type == "binary":
            return {"type": "noul", "instructions": q.instructions}
        keys = option_keys(q.options)
        crit = {keys[k]: (v if keys[k] == k else f"{k} — {v}") for k, v in q.options.items()}
        return {"type": "choice", "instructions": q.instructions, "criteria": crit}

    def build_request(self, parts: list[Part], question: Question) -> Request:
        return Request(
            url=f"{API_BASE}/decisions?key={self.env('GEMINI_API_KEY')}",
            headers={},
            body={"model": self.info.api_model, "input": [self.part(p) for p in parts],
                  "questions": {QNAME: self.question(question)}},
        )

    def parse_response(self, data: dict, question: Question) -> Answer:
        if "error" in data:
            raise ProviderError(str(data["error"].get("message", data["error"]))[:300], permanent=True)
        ans = (data.get("answers") or {}).get(QNAME)
        if ans is None:
            raise ProviderError(f"回應沒有 answers.{QNAME}：{str(data)[:200]}")
        if question.type == "binary":
            p = float(ans["noul"])
            probs = {"yes": p, "no": 1.0 - p}
        else:
            back = {v: k for k, v in option_keys(question.options).items()}
            probs = {back.get(k, k): float(v) for k, v in (ans.get("probabilities") or {}).items()}
            if not probs:
                raise ProviderError(f"choice 沒有 probabilities：{str(ans)[:200]}")
        usage = data.get("usage") or {}
        return Answer(probs, usage.get("total_input_tokens"), {"usage": usage})
