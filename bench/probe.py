"""模態能力探針：判斷某模型「真的看得到／聽得到」某種輸入，而不只是收下。

背景：Microsoft Decision 1.1 對 ``type:"audio"`` 會回 200，但只是把 base64 當文字
tokenize，等於沒有音訊通道。光看「有沒有報錯」會誤判，所以每個模態做兩件事：

1. **無效資料探針**：送一段根本不是合法媒體的位元組（``fixtures/invalid.*``）。
   真正會解碼的端點應該回 4xx；回 200 代表它可能沒在解碼（只當參考，不單獨定案）。
2. **成對對照探針**：一組答案顯而易見的正例／負例（說話 vs 靜音、紅圖 vs 藍圖）。
   正例的 P(yes) 全部都要比負例高出 ``MARGIN`` 以上，才判定 ``supported``。

最終狀態：
- ``supported``：成對對照通過
- ``ignored``：請求成功，但分不出正負例（收下但沒在看）
- ``rejected``：合法媒體被 4xx 拒絕（不支援這個模態或格式不對）
- ``error``：網路或伺服器錯誤，無法判定
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .providers.base import Provider, ProviderError
from .runner import CAPS_FILE, RESULTS_DIR, load_caps
from .schema import Part, Question

MARGIN = 0.2
FIX = "bench/fixtures"

PROBES = {
    "audio": {
        "question": Question("binary", "Does this audio contain a human voice speaking?"),
        "positive": [f"{FIX}/speech_zh.mp3", f"{FIX}/speech_en.mp3"],
        "negative": ["data/negative/silence.mp3", "data/negative/noise.mp3"],
        "invalid": f"{FIX}/invalid.mp3",
    },
    "image": {
        "question": Question("binary", "Is this image filled mostly with the color red?"),
        "positive": [f"{FIX}/red.png", f"{FIX}/red_dark.png"],
        "negative": [f"{FIX}/blue.png", f"{FIX}/green.png"],
        "invalid": f"{FIX}/invalid.png",
    },
}


def _p_yes(provider: Provider, path: str, modality: str, question: Question) -> float:
    ans = provider.decide([Part(modality, path=path)], question)
    total = sum(ans.probs.values()) or 1.0
    return ans.probs.get("yes", 0.0) / total


def probe_modality(provider: Provider, modality: str) -> dict:
    spec = PROBES[modality]
    q = spec["question"]
    ev: dict = {"date": datetime.now(timezone.utc).date().isoformat()}

    try:
        _p_yes(provider, spec["invalid"], modality, q)
        ev["invalid_data"] = "accepted"
    except ProviderError as exc:
        ev["invalid_data"] = f"rejected({exc.status})" if exc.status else f"error({str(exc)[:80]})"
    except (KeyError, TypeError, ValueError) as exc:
        ev["invalid_data"] = f"parse_error({str(exc)[:60]})"

    pos, neg = [], []
    try:
        pos = [_p_yes(provider, p, modality, q) for p in spec["positive"]]
        neg = [_p_yes(provider, p, modality, q) for p in spec["negative"]]
    except ProviderError as exc:
        ev["error"] = str(exc)[:300]
        ev["status"] = "rejected" if exc.permanent else "error"
        return ev
    except (KeyError, TypeError, ValueError) as exc:
        ev["error"] = f"解析失敗：{exc}"[:300]
        ev["status"] = "error"
        return ev
    ev["positive"] = [round(x, 4) for x in pos]
    ev["negative"] = [round(x, 4) for x in neg]
    ev["margin"] = round(min(pos) - max(neg), 4)
    ev["status"] = "supported" if ev["margin"] >= MARGIN else "ignored"
    return ev


def probe(providers: list[Provider], modalities: list[str], log=print, workers: int = 8) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    caps = load_caps()

    def one(prov: Provider):
        if not prov.available:
            log(f"  - {prov.info.id}：缺少 {','.join(prov.missing_env())}，略過")
            return prov, {}
        out = {}
        for mod in modalities:
            ev = probe_modality(prov, mod)
            out[mod] = ev
            log(f"  {prov.info.id} × {mod}: {ev['status']}  "
                f"(margin={ev.get('margin')}, invalid={ev.get('invalid_data')})")
        return prov, out

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for prov, out in pool.map(one, providers):
            if out:
                caps.setdefault(prov.info.id, {}).update(out)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CAPS_FILE.write_text(json.dumps(caps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return caps
