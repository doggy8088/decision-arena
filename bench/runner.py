"""執行評測：模型 × 任務 × 題項，含快取、預算上限、模態守門。

- 快取：``out/bench/cache/<model>/<sha256>.json``，鍵是「不含金鑰的請求內容」，
  重跑或重新出報告不會重複花錢。
- 預算：所有執行緒共用一個計數器，超過上限就停止送出新請求。
- 模態守門：任務需要的非文字模態（image／audio），必須在 ``results/capabilities.json``
  裡被探針判定為 ``supported`` 才會跑；否則整格記成 skipped，避免把
  「端點收下但沒解碼」的假結果當成分數（Microsoft Decision 1.1 的音訊就是這樣）。
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .providers.base import Answer, Provider, ProviderError
from .schema import ROOT, Item, Task

CACHE_DIR = ROOT / "out" / "bench" / "cache"
RESULTS_DIR = ROOT / "results"
CAPS_FILE = RESULTS_DIR / "capabilities.json"


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    cap_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reserve(self, estimate: float) -> None:
        with self._lock:
            if self.spent_usd + estimate > self.cap_usd:
                raise BudgetExceeded(f"預算上限 US${self.cap_usd:.2f}，已花 US${self.spent_usd:.4f}")
            self.spent_usd += estimate
            self.calls += 1

    def settle(self, estimate: float, actual: float) -> None:
        with self._lock:
            self.spent_usd += actual - estimate


def load_caps() -> dict:
    if CAPS_FILE.is_file():
        return json.loads(CAPS_FILE.read_text(encoding="utf-8"))
    return {}


def modality_status(caps: dict, model: str, modality: str) -> str:
    if modality == "text":
        return "supported"
    return (caps.get(model, {}).get(modality) or {}).get("status", "unprobed")


def _cache_path(model: str, payload: dict) -> Path:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return CACHE_DIR / model / f"{digest}.json"


def _media_bytes(item: Item) -> int:
    return sum((ROOT / p.path).stat().st_size for p in item.inputs if p.path)


def call(provider: Provider, task: Task, item: Item, budget: Budget | None,
         use_cache: bool = True) -> dict:
    """單一題項：回傳一筆紀錄（不拋例外，預算用完除外）。"""
    question = task.question_for(item)
    rec = {"model": provider.info.id, "task": task.id, "item": item.id, "gold": item.gold,
           "pair": item.pair, "side": item.group, "ok": False}
    try:
        req = provider.build_request(list(item.inputs), question)
    except (OSError, ValueError) as exc:
        rec["error"] = f"建立請求失敗：{exc}"
        return rec
    path = _cache_path(provider.info.id, req.cache_payload())
    t0 = time.perf_counter()
    data = None
    if use_cache and path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        data, rec["cached"], rec["latency_ms"] = cached["data"], True, cached.get("latency_ms")
    estimate = 0.0
    if data is None:
        chars = sum(len(p.text) for p in item.inputs) + len(question.instructions) + _media_bytes(item) // 100
        estimate = provider.estimate_cost(None, chars)
        if budget:
            budget.reserve(estimate)
        try:
            data = provider.send(req)
        except ProviderError as exc:
            if budget:
                budget.settle(estimate, 0.0)
            rec.update(error=str(exc)[:400], status=exc.status,
                       latency_ms=round((time.perf_counter() - t0) * 1000))
            return rec
        rec["latency_ms"] = round((time.perf_counter() - t0) * 1000)
        rec["cached"] = False
    try:
        ans: Answer = provider.parse_response(data, question)
    except (ProviderError, KeyError, TypeError, ValueError) as exc:
        if budget and not rec.get("cached"):
            budget.settle(estimate, estimate)
        rec["error"] = f"解析失敗：{exc}"[:400]
        return rec
    # 回傳的選項必須和題目標籤一一對應、機率總和約為 1；否則視為對應錯誤，不計分
    labels = set(question.labels)
    total = sum(ans.probs.values())
    if set(ans.probs) != labels or abs(total - 1.0) > 0.02:
        if budget and not rec.get("cached"):
            budget.settle(estimate, estimate)
        rec["error"] = f"標籤或機率不符：回傳 {sorted(ans.probs)} 總和 {total:.3f}，預期 {sorted(labels)}"[:400]
        return rec
    cost = ans.raw.get("cost_usd", provider.estimate_cost(ans.input_tokens))
    if budget and not rec.get("cached"):
        budget.settle(estimate, cost)
    if use_cache and not rec.get("cached"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"data": data, "latency_ms": rec["latency_ms"]}, ensure_ascii=False),
                        encoding="utf-8")
    rec.update(ok=True, probs=ans.probs, input_tokens=ans.input_tokens, cost_usd=cost)
    return rec


def plan(providers: list[Provider], tasks: list[Task], caps: dict, force: bool = False) -> list[dict]:
    """列出每個模型 × 任務是否會跑、不跑的原因。"""
    cells = []
    for prov in providers:
        for task in tasks:
            cell = {"model": prov.info.id, "task": task.id, "run": True, "reason": ""}
            if not prov.available:
                cell.update(run=False, reason="no_key:" + ",".join(prov.missing_env()))
            else:
                for mod in sorted(task.modalities - {"text"}):
                    status = modality_status(caps, prov.info.id, mod)
                    if status != "supported" and not force:
                        cell.update(run=False, reason=f"modality:{mod}={status}")
                        break
            cells.append(cell)
    return cells


def run(providers: list[Provider], tasks: list[Task], *, limit: int = 0, budget_usd: float = 5.0,
        workers: int = 4, model_workers: int = 6, force: bool = False, use_cache: bool = True, run_id: str = "",
        log=print) -> Path:
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_DIR / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    caps = load_caps()
    cells = plan(providers, tasks, caps, force)
    budget = Budget(budget_usd)
    by_id = {p.info.id: p for p in providers}
    task_by_id = {t.id: t for t in tasks}
    records: list[dict] = []
    stopped = ""

    lock = threading.Lock()

    def run_model(model_id: str) -> None:
        nonlocal stopped
        for cell in [c for c in cells if c["model"] == model_id]:
            if stopped:
                return
            if not cell["run"]:
                log(f"  - 略過 {cell['model']} × {cell['task']}（{cell['reason']}）")
                continue
            prov, task = by_id[cell["model"]], task_by_id[cell["task"]]
            items = list(task.items[:limit] if limit else task.items)
            if task.metric == "swap_symmetry" and limit:
                keep = {it.pair for it in items}
                items = [it for it in task.items if it.pair in keep]
            try:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    rows = list(pool.map(lambda it: call(prov, task, it, budget, use_cache), items))
            except BudgetExceeded as exc:
                stopped = str(exc)
                log(f"  ! {exc}，停止。")
                return
            with lock:
                records.extend(rows)
            ok = sum(r["ok"] for r in rows)
            log(f"  ✓ {cell['model']} × {cell['task']}：{ok}/{len(rows)} 成功，累計 US${budget.spent_usd:.4f}")
            # 連續整格失敗（例如模型下架、金鑰無權限）就不再浪費時間
            if rows and ok == 0 and all(r.get("status") in (401, 403, 404) for r in rows):
                log(f"  ! {model_id} 回 {rows[0].get('status')}，略過其餘任務")
                return

    with ThreadPoolExecutor(max_workers=max(1, model_workers)) as pool:
        list(pool.map(run_model, list(by_id)))

    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    meta = {"run_id": run_id, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "models": [p.info.id for p in providers], "tasks": [t.id for t in tasks],
            "limit": limit, "budget_usd": budget_usd, "spent_usd": round(budget.spent_usd, 6),
            "calls": budget.calls, "stopped": stopped, "cells": cells}
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_dir
