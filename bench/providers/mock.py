"""離線測試用的假模型，不呼叫網路。

- ``MockOracle``：看得到 item 的 ``vars["_gold"]``（測試時注入），永遠以 0.9 答對。
- ``MockBlind``：對任何輸入都回均勻分佈，模擬「收下媒體但沒解碼」的端點。
"""
from __future__ import annotations

from ..schema import Part, Question
from .base import Answer, ModelInfo, Provider, Request


class _Mock(Provider):
    def build_request(self, parts: list[Part], question: Question) -> Request:
        body = {"parts": [{"type": p.type, "text": p.text, "path": p.path} for p in parts],
                "question": question.to_dict()}
        return Request(url=f"mock://{self.info.id}", headers={}, body=body)


class MockOracle(_Mock):
    info = ModelInfo("mock-oracle", "Mock", "mock-oracle", ("text", "image", "audio"), (), 0.0)

    def send(self, req: Request) -> dict:
        labels = (["yes", "no"] if req.body["question"]["type"] == "binary"
                  else list(req.body["question"]["options"]))
        gold = next((p["text"].split("GOLD=")[1].split()[0] for p in req.body["parts"]
                     if "GOLD=" in p["text"]), labels[0])
        rest = (1 - 0.9) / (len(labels) - 1)
        return {"probs": {k: (0.9 if k == gold else rest) for k in labels}, "tokens": 10}

    def parse_response(self, data: dict, question: Question) -> Answer:
        return Answer(data["probs"], data["tokens"])


class MockBlind(_Mock):
    info = ModelInfo("mock-blind", "Mock", "mock-blind", ("text",), (), 0.0)

    def send(self, req: Request) -> dict:
        q = req.body["question"]
        labels = ["yes", "no"] if q["type"] == "binary" else list(q["options"])
        return {"probs": {k: 1 / len(labels) for k in labels}, "tokens": 10}

    def parse_response(self, data: dict, question: Question) -> Answer:
        return Answer(data["probs"], data["tokens"])
