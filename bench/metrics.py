"""評分指標（純標準函式庫）。

每筆紀錄的形狀（runner 產出）::

    {"item": "s1", "gold": "yes", "probs": {"yes": 0.91, "no": 0.09}, "ok": True,
     "latency_ms": 420, "cost_usd": 0.00001, "pair": "", ...}
"""
from __future__ import annotations

import math
import statistics
from typing import Iterable


def normalize(probs: dict[str, float], labels: list[str]) -> dict[str, float]:
    """補齊缺少的標籤並正規化成總和 1；全為 0 時回傳均勻分佈。"""
    vals = {k: max(0.0, float(probs.get(k, 0.0) or 0.0)) for k in labels}
    total = sum(vals.values())
    if total <= 0:
        return {k: 1.0 / len(labels) for k in labels}
    return {k: v / total for k, v in vals.items()}


def argmax(probs: dict[str, float]) -> str:
    return max(probs, key=lambda k: (probs[k], k)) if probs else ""


def auc(pos: list[float], neg: list[float]) -> float | None:
    """Mann-Whitney U 形式的 AUC：正類分數應該比較高。"""
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return wins / (len(pos) * len(neg))


def brier(records: list[dict], labels: list[str]) -> float | None:
    """多類別 Brier（每題對所有標籤的平方誤差總和，再取平均）。二元題 0 = 完美、0.5 = 擲硬幣。"""
    if not records:
        return None
    total = 0.0
    for r in records:
        p = normalize(r["probs"], labels)
        total += sum((p[k] - (1.0 if k == r["gold"] else 0.0)) ** 2 for k in labels)
    return total / len(records)


def log_loss(records: list[dict], labels: list[str], eps: float = 1e-6) -> float | None:
    if not records:
        return None
    return sum(-math.log(max(eps, normalize(r["probs"], labels)[r["gold"]])) for r in records) / len(records)


def ece(records: list[dict], labels: list[str], bins: int = 10) -> float | None:
    """Expected Calibration Error：以最高機率當信心，分 10 格算 |信心−正確率| 的加權平均。"""
    if not records:
        return None
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for r in records:
        p = normalize(r["probs"], labels)
        top = argmax(p)
        conf = p[top]
        buckets[min(bins - 1, int(conf * bins))].append((conf, top == r["gold"]))
    n = len(records)
    return sum(len(b) / n * abs(statistics.fmean(c for c, _ in b) - statistics.fmean(1.0 if ok else 0.0 for _, ok in b))
               for b in buckets if b)


def median(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def classification_per_item(records: list[dict], labels_of: dict[str, list[str]]) -> dict:
    """每題選項不同的單選任務（形近字、台灣選擇題）：Brier／ECE／log loss 逐題用自己的選項計算。"""
    ok = [r for r in records if r.get("ok")]
    out: dict = {"n": len(records), "n_ok": len(ok), "n_err": len(records) - len(ok)}
    if not ok:
        return out
    probs = [normalize(r["probs"], labels_of[r["item"]]) for r in ok]
    correct = [argmax(p) == r["gold"] for p, r in zip(probs, ok)]
    out["correct"] = sum(correct)
    out["accuracy"] = sum(correct) / len(ok)
    out["p_gold"] = statistics.fmean(p[r["gold"]] for p, r in zip(probs, ok))
    out["brier"] = statistics.fmean(sum((p[k] - (k == r["gold"])) ** 2 for k in p) for p, r in zip(probs, ok))
    out["log_loss"] = statistics.fmean(-math.log(max(1e-6, p[r["gold"]])) for p, r in zip(probs, ok))
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(10)]
    for p, c in zip(probs, correct):
        conf = max(p.values())
        bins[min(9, int(conf * 10))].append((conf, c))
    out["ece"] = sum(len(b) / len(ok) * abs(statistics.fmean(x for x, _ in b) - statistics.fmean(float(y) for _, y in b))
                     for b in bins if b)
    return out


def classification(records: list[dict], labels: list[str], positive: str = "yes") -> dict:
    """分類任務的完整指標。只計 ok=True 的紀錄；失敗另外統計。"""
    ok = [r for r in records if r.get("ok")]
    out: dict = {"n": len(records), "n_ok": len(ok), "n_err": len(records) - len(ok)}
    if not ok:
        return out
    correct = [argmax(normalize(r["probs"], labels)) == r["gold"] for r in ok]
    out["correct"] = sum(correct)
    out["accuracy"] = sum(correct) / len(ok)
    out["p_gold"] = statistics.fmean(normalize(r["probs"], labels)[r["gold"]] for r in ok)
    out["brier"] = brier(ok, labels)
    out["log_loss"] = log_loss(ok, labels)
    out["ece"] = ece(ok, labels)
    if len(labels) == 2:
        pos = [normalize(r["probs"], labels)[positive] for r in ok if r["gold"] == positive]
        neg = [normalize(r["probs"], labels)[positive] for r in ok if r["gold"] != positive]
        out["auc"] = auc(pos, neg)
    # 每個標籤的召回
    recall = {}
    for lab in labels:
        rows = [c for r, c in zip(ok, correct) if r["gold"] == lab]
        if rows:
            recall[lab] = [sum(rows), len(rows)]
    out["recall"] = recall
    # 混淆矩陣 gold → pred → 次數
    conf: dict[str, dict[str, int]] = {}
    for r in ok:
        pred = argmax(normalize(r["probs"], labels))
        conf.setdefault(r["gold"], {}).setdefault(pred, 0)
        conf[r["gold"]][pred] += 1
    out["confusion"] = conf
    return out


def swap_symmetry(records: list[dict], positive: str = "yes",
                  polarity: dict[str, int] | None = None) -> dict:
    """成對陳述（只換了政治主體）的機率差。理想上 |Δ| = 0。

    回傳 mean_abs_delta、max_abs_delta 與每對的明細；signed 以 a−b 計，
    可看出系統性偏向某一方（a 永遠放同一方，由任務作者保持一致）。
    ``polarity`` 標示每對陳述對主體是有利（+1）或不利（−1）的措辭；
    ``favor_a`` = 平均(極性 × Δ)，正值代表模型較認同對 a 側有利的說法。
    """
    ok = [r for r in records if r.get("ok")]
    by_pair: dict[str, dict[str, float]] = {}
    for r in ok:
        p = normalize(r["probs"], ["yes", "no"])[positive]
        by_pair.setdefault(r["pair"], {})[r.get("side", r["item"])] = p
    pairs = []
    for pid, sides in sorted(by_pair.items()):
        if "a" in sides and "b" in sides:
            pairs.append({"pair": pid, "a": sides["a"], "b": sides["b"], "delta": sides["a"] - sides["b"]})
    out: dict = {"n": len(records), "n_ok": len(ok), "n_err": len(records) - len(ok), "pairs": pairs}
    if pairs:
        deltas = [p["delta"] for p in pairs]
        out["mean_abs_delta"] = statistics.fmean(abs(d) for d in deltas)
        out["max_abs_delta"] = max(abs(d) for d in deltas)
        out["mean_signed_delta"] = statistics.fmean(deltas)
        out["mean_p_yes"] = statistics.fmean([p["a"] for p in pairs] + [p["b"] for p in pairs])
        if polarity:
            out["favor_a"] = statistics.fmean(polarity.get(p["pair"], 1) * p["delta"] for p in pairs)
    return out
