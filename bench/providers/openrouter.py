"""OpenRouter Decisions（alpha）：一把金鑰呼叫多家決策模型。

2026-11-22 實測確認：
- ``POST https://openrouter.ai/api/alpha/decisions``，``Authorization: Bearer $OPENROUTER_API_KEY``
- body ``{model, state, questions}``；``state`` 可為字串或陣列，陣列元素：
  - 文字：直接放字串
  - 圖片：``{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}``
  - 音訊：``{"type":"input_audio","input_audio":{"data":"<raw b64>","format":"mp3"}}``
- 題型 ``noul`` / ``choice``（``criteria`` 為 ``{key: 說明}``），回應同 System One：
  ``answers.<name>.noul``、``answers.<name>.probabilities``
- ``usage.cost`` 直接給美元成本（含上游費用），本 adapter 優先採用。

OpenRouter 會把同一份 body 轉成各家格式，所以 Gemini、GPT-6 Luna 也走這裡；
但各家實際讀不讀圖／音訊仍以模態探針為準（例如 Clef 只讀 state 前約 2,000 個文字 token）。
"""
from __future__ import annotations

import re

from ..schema import Part, Question
from .base import Answer, ModelInfo, Provider, ProviderError, Request

URL = "https://openrouter.ai/api/alpha/decisions"
QNAME = "q"
SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
AUDIO_FORMAT = {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/flac": "flac", "audio/ogg": "ogg"}


def option_keys(options: dict[str, str]) -> dict[str, str]:
    """標籤 → 送出用的鍵。非 ASCII 標籤（形近字、注音）改用 opt0、opt1…，說明文字保留原標籤。"""
    if all(SAFE_KEY.match(k) for k in options):
        return {k: k for k in options}
    return {k: f"opt{i}" for i, k in enumerate(options)}


class OpenRouterDecision(Provider):
    info: ModelInfo

    def part(self, p: Part):
        if p.type == "text":
            return p.text
        data = self.b64(p)
        if p.type == "image":
            return {"type": "image_url", "image_url": {"url": f"data:{p.mime};base64,{data}"}}
        return {"type": "input_audio", "input_audio": {"data": data, "format": AUDIO_FORMAT.get(p.mime, "mp3")}}

    def question(self, q: Question) -> dict:
        if q.type == "binary":
            return {"type": "noul", "instructions": q.instructions}
        keys = option_keys(q.options)
        crit = {}
        for label, desc in q.options.items():
            crit[keys[label]] = desc if keys[label] == label else f"{label} — {desc}"
        return {"type": "choice", "instructions": q.instructions, "criteria": crit}

    def build_request(self, parts: list[Part], question: Question) -> Request:
        state = [self.part(p) for p in parts]
        if len(state) == 1 and isinstance(state[0], str):
            state = state[0]
        return Request(URL, {"Authorization": f"Bearer {self.env('OPENROUTER_API_KEY')}"},
                       {"model": self.info.api_model, "state": state,
                        "questions": {QNAME: self.question(question)}})

    def parse_response(self, data: dict, question: Question) -> Answer:
        if "error" in data:
            raise ProviderError(str(data["error"])[:300], permanent=True)
        ans = (data.get("answers") or {}).get(QNAME)
        if not ans:
            raise ProviderError(f"回應沒有 answers.{QNAME}：{str(data)[:200]}")
        if ans.get("type") == "refusal":
            raise ProviderError(f"模型拒答：{str(ans)[:200]}", permanent=True)
        if question.type == "binary":
            p = float(ans["noul"])
            probs = {"yes": p, "no": 1.0 - p}
        else:
            back = {v: k for k, v in option_keys(question.options).items()}
            probs = {back.get(k, k): float(v) for k, v in (ans.get("probabilities") or {}).items()}
            if not probs:
                raise ProviderError(f"choice 沒有 probabilities：{str(ans)[:200]}")
        usage = data.get("usage") or {}
        a = Answer(probs, usage.get("input_tokens"), {"usage": usage, "provider": data.get("provider"),
                                                       "model": data.get("model")})
        if usage.get("cost") is not None:
            a.raw["cost_usd"] = float(usage["cost"])
        return a


def _model(id_, vendor, slug, mods, price, notes="", docs=""):
    info = ModelInfo(id=id_, vendor=vendor, api_model=slug, documented_modalities=tuple(mods),
                     env_keys=("OPENROUTER_API_KEY",), usd_per_m_input=price, notes=notes,
                     docs=docs or f"https://openrouter.ai/{slug.split(':')[0]}")
    return type(f"OR_{re.sub(r'[^A-Za-z0-9]', '_', id_)}", (OpenRouterDecision,), {"info": info})


T, TI, TIA = ("text",), ("text", "image"), ("text", "image", "audio")
# (本專案代號, 廠商, OpenRouter slug, 官方文件模態, 每百萬 input token 美元, 備註)
# 模態與價格依 2026-11-22 盤點（廠商文件 + OpenRouter /models），DI = Artificial Analysis Decision Index v2.1。
CATALOG = [
    ("bison-1", "Base Labs (Baseten)", "baseten/bison-1", TI, 0.10, "DI v2.1 75.9（榜首）；開放權重，基底 Gemma 4 31B"),
    ("d1.2-ultra", "Liquid AI", "liquid/d1.2-ultra", TIA, 0.042, "DI 74.8；官方文件列音訊，但 OpenRouter 標 text+image"),
    ("drex-max", "Nace.AI", "nace-ai/drex-max", TI, 0.06, "DI 72.6（Drex Max v1.1）"),
    ("mammoth-1", "Base Labs (Baseten)", "baseten/mammoth-1", TI, 0.10, "DI 71.4；tech report 稱只用文字訓練，與文件矛盾"),
    ("pplx-decider-v1.3", "Perplexity", "perplexity/pplx-decider-v1.3:free", TI, 0.0, "DI 70.4；開放權重；OpenRouter 免費版"),
    ("d1.2", "Liquid AI", "liquid/d1.2", TIA, 0.02, "DI 68.7"),
    ("microsoft-decision-1.1", "Microsoft", "microsoft/microsoft-decision-1.1", TI, 0.042,
     "DI 67.8；本專案先前證實無音訊通道"),
    ("elephant-1", "Base Labs (Baseten)", "baseten/elephant-1", TI, 0.035, "DI 66.4；9B"),
    ("jev-1.14", "TypeSafe", "typesafe/jev-1.14", TI, 0.042, "DI 66.2；System One 格式原型；圖片為實驗性"),
    ("pplx-decider-flash-v1.3", "Perplexity", "perplexity/pplx-decider-flash-v1.3:free", TI, 0.0, "DI 64.1；4B"),
    ("microsoft-decision-1", "Microsoft", "microsoft/microsoft-decision-1", T, 0.042, "DI 62.1；上一代"),
    ("drex-v2.0", "Nace.AI", "nace-ai/drex-v2.0", T, 0.06, "DI 61.6；開放權重"),
    ("clef", "Cloudflare", "cloudflare/clef", TI, 0.192, "DI 60.3；只讀 state 前約 2,000 文字 token"),
    ("gpt-6-luna-decisions", "OpenAI", "openai/gpt-6-luna-decisions", TI, 0.10, "DI 60.2；不支援音訊"),
    ("clef-omni", "Cloudflare", "cloudflare/clef-omni", ("text", "image", "audio", "video"), 0.15, "DI 57.8；全模態"),
    ("heygen-decision-1", "HeyGen", "heygen/heygen-decision-1", ("text", "image", "audio", "video"), 0.07,
     "未列入 AA 榜；全模態"),
    ("heygen-decision-1-turbo", "HeyGen", "heygen/heygen-decision-1-turbo", ("text", "image", "audio", "video"),
     0.042, "未列入 AA 榜"),
    ("solar-decide", "Upstage", "upstage/solar-decide", T, 0.05, "未列入 AA 榜；韓國廠商"),
    ("clef-flash", "Cloudflare", "cloudflare/clef-flash", TI, 0.019, "未列入 AA 榜；9B 開放權重"),
    ("span-02", "Respan", "respan/span-02", TI, 0.01, "未列入 AA 榜"),
    ("reflex", "Morph", "morph/reflex", TI, 0.042, "未列入 AA 榜"),
    ("classify-1", "ScaleDown", "scaledown/classify-1", ("text", "image", "pdf"), 0.04, "未列入 AA 榜；1M context"),
    ("pplx-decider-v1.2", "Perplexity", "perplexity/pplx-decider-v1.2", TI, 0.02, "DI 69.8；上一版"),
    ("pplx-decider-flash-v1.2", "Perplexity", "perplexity/pplx-decider-flash-v1.2", TI, 0.01, "DI 60.1；上一版 4B"),
    ("drex-max-finance", "Nace.AI", "nace-ai/drex-max-finance", TI, 0.06, "未列入 AA 榜；金融領域版"),
    ("groundhog-1", "Base Labs (Baseten)", "baseten/groundhog-1", TI, 0.035, "未列入 AA 榜；開放權重"),
    ("joey-1", "Base Labs (Baseten)", "baseten/joey-1", TI, 0.01, "未列入 AA 榜；開放權重"),
    ("solar-decide-flash", "Upstage", "upstage/solar-decide-flash", T, 0.05, "未列入 AA 榜"),
    ("span-01", "Respan", "respan/span-01", T, 0.02, "未列入 AA 榜"),
    ("span-01-lite", "Respan", "respan/span-01-lite", T, 0.0, "未列入 AA 榜"),
    ("tev1-4b-experimental", "Together AI", "togethercomputer/tev1-4b-experimental", T, 0.042,
     "未列入 AA 榜；實驗性 4B 開放權重"),
    ("kev-4b", "Jared Palmer", "jaredpalmer/kev-4b", T, 0.042, "未列入 AA 榜；個人發布的 4B 開放權重"),
    ("decisions-fast", "Parallel", "parallel/decisions-fast", T, 0.0, "未列入 AA 榜；會上網查證，每次請求 US$0.001"),
]
# 刻意不跑：cloudflare/clairic（抽取型，走另一個端點）、已退役或改道的舊版
# （liquid/d1、d1.1、d1-ultra、typesafe/jev-1.13、nace-ai/drex-v1.5）、別名（~typesafe/jev-latest 等）。

MODELS = [_model(*row) for row in CATALOG]
