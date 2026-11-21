"""Provider 註冊表。新增模型：寫一個 Provider 子類別，加進 REGISTRY。"""
from __future__ import annotations

from .base import ModelInfo, Provider, ProviderError
from .gemini import GeminiDecision
from .mock import MockBlind, MockOracle
from .openrouter import MODELS as OPENROUTER_MODELS

REGISTRY: dict[str, type[Provider]] = {
    cls.info.id: cls
    for cls in (GeminiDecision, *OPENROUTER_MODELS)
}

MOCKS: dict[str, type[Provider]] = {cls.info.id: cls for cls in (MockOracle, MockBlind)}


def get(model_ids: list[str] | None = None, include_mocks: bool = False) -> list[Provider]:
    table = {**REGISTRY, **(MOCKS if include_mocks else {})}
    ids = model_ids or list(REGISTRY)
    unknown = [m for m in ids if m not in table and m not in MOCKS]
    if unknown:
        raise SystemExit(f"未知的模型：{unknown}；可用：{list(REGISTRY)}")
    return [({**table, **MOCKS})[m]() for m in ids]


__all__ = ["REGISTRY", "MOCKS", "get", "Provider", "ProviderError", "ModelInfo"]
