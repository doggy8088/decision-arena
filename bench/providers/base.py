"""Provider 介面：把標準化題目送到各家決策模型，回傳標準化機率。

新增一個模型 = 繼承 ``Provider``、實作 ``build_request`` 與 ``parse_response``，
再到 ``providers/__init__.py`` 的 REGISTRY 登記。HTTP、重試、快取、計價都在這一層處理。
"""
from __future__ import annotations

import base64
import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..schema import Part, Question


class ProviderError(RuntimeError):
    """呼叫失敗。``permanent=True`` 代表重試也沒用（4xx 類）。"""

    def __init__(self, message: str, status: int | None = None, permanent: bool = False):
        super().__init__(message)
        self.status = status
        self.permanent = permanent


@dataclass
class Request:
    url: str
    headers: dict[str, str]
    body: dict

    def cache_payload(self) -> dict:
        """用來算快取鍵的內容：不含金鑰。"""
        return {"url": self.url.split("?")[0], "body": self.body}


@dataclass
class Answer:
    probs: dict[str, float]
    input_tokens: int | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ModelInfo:
    id: str                       # 本專案內的代號
    vendor: str
    api_model: str                # 送給 API 的 model 字串
    documented_modalities: tuple[str, ...]   # 官方文件列出的輸入模態
    env_keys: tuple[str, ...]     # 需要的環境變數
    usd_per_m_input: float        # 每百萬輸入 token 的價格（估算用）
    usd_per_question: float = 0.0  # 若官方按題計價
    notes: str = ""
    docs: str = ""


class Provider:
    info: ModelInfo
    timeout = 120
    retries = 4

    # ---- 子類別實作 -------------------------------------------------
    def build_request(self, parts: list[Part], question: Question) -> Request:  # pragma: no cover
        raise NotImplementedError

    def parse_response(self, data: dict, question: Question) -> Answer:  # pragma: no cover
        raise NotImplementedError

    # ---- 共用 -------------------------------------------------------
    def env(self, name: str) -> str:
        return os.environ.get(name, "").strip()

    def missing_env(self) -> list[str]:
        return [k for k in self.info.env_keys if not self.env(k)]

    @property
    def available(self) -> bool:
        return not self.missing_env()

    @staticmethod
    def b64(part: Part) -> str:
        return base64.b64encode(part.read_bytes()).decode()

    def estimate_cost(self, input_tokens: int | None, fallback_chars: int = 0) -> float:
        tokens = input_tokens if input_tokens is not None else max(1, fallback_chars // 3)
        return tokens / 1e6 * self.info.usd_per_m_input + self.info.usd_per_question

    def send(self, req: Request) -> dict:
        """POST JSON，暫時性錯誤指數退避重試；4xx（429 除外）立即拋出。"""
        last: ProviderError | None = None
        for attempt in range(self.retries):
            http = urllib.request.Request(
                req.url, data=json.dumps(req.body).encode("utf-8"),
                headers={"Content-Type": "application/json", **req.headers}, method="POST")
            try:
                with urllib.request.urlopen(http, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", errors="replace")[:500]
                permanent = 400 <= exc.code < 500 and exc.code not in (408, 429)
                last = ProviderError(f"HTTP {exc.code}: {text}", exc.code, permanent)
                if permanent:
                    raise last
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last = ProviderError(f"{type(exc).__name__}: {exc}")
            except json.JSONDecodeError as exc:
                last = ProviderError(f"回應不是 JSON：{exc}")
            time.sleep(min(10, 0.8 * 2 ** attempt) + random.random() * 0.5)
        assert last is not None
        raise last

    def decide(self, parts: list[Part], question: Question) -> Answer:
        req = self.build_request(parts, question)
        data = self.send(req)
        return self.parse_response(data, question)
