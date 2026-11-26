"""由 results/ 產生互動式 dashboard：bench-dashboard.html。

    python3 -m bench dashboard

與 bench-report.html 同源（同樣的合併規則與指標），差別在於：
- 用圖表呈現「模型 × 模態」「模型 × 情境」與各指標之間的關係；
- 一排篩選器（需要的模態、焦點指標、最低分數、價格上限……）即時縮小可用模型清單。

資料以 JSON 內嵌在單一 HTML 檔中，不依賴任何外部腳本，可離線開啟。
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime
from pathlib import Path

from . import providers
from .report import cell_metrics, load_runs
from .runner import load_caps
from .schema import ROOT, SCENARIOS, load_tasks

OUT = ROOT / "bench-dashboard.html"
TEMPLATE = Path(__file__).with_name("dashboard_template.html")

# 有鑑別力的任務：種子題組中，模型之間差距最大的四個（其餘多數任務接近滿分）
DISCRIMINATIVE = ["image-zh-char", "image-zhuyin", "tw-facts-choice", "tw-facts-binary"]
WEB_GROUNDED = {"decisions-fast"}


def _di(notes: str) -> float | None:
    m = re.search(r"DI(?: v2\.1)? (\d+(?:\.\d+)?)", notes)
    return float(m.group(1)) if m else None


def build_data() -> dict:
    tasks = load_tasks()
    task_by_id = {t.id: t for t in tasks}
    caps = load_caps()
    records, _cells, metas = load_runs()
    by_cell: dict[tuple, list] = {}
    for r in records:
        by_cell.setdefault((r["model"], r["task"]), []).append(r)

    models = []
    for prov in providers.get():
        info = prov.info
        mid = info.id
        mods = {"text": True}
        for mod in ("image", "audio"):
            mods[mod] = (caps.get(mid, {}).get(mod) or {}).get("status") == "supported"
        tier = "audio" if mods["audio"] else "image" if mods["image"] else "text"

        task_res = {}
        for t in tasks:
            recs = by_cell.get((mid, t.id))
            if not recs:
                continue
            m = cell_metrics(t, recs)
            if t.scored:
                if not m.get("n_ok"):
                    task_res[t.id] = {"status": "rejected", "n": m["n"]}
                    continue
                task_res[t.id] = {"acc": round(m["accuracy"], 4), "n": m["n_ok"],
                                  "auc": None if m.get("auc") is None else round(m["auc"], 4),
                                  "brier": None if m.get("brier") is None else round(m["brier"], 4)}
            else:
                task_res[t.id] = {"delta": round(m.get("mean_abs_delta", 0), 4),
                                  "favor": round(m.get("favor_a", 0), 4), "n": len(m.get("pairs", []))}

        def avg(ids):
            vals = [task_res[i]["acc"] for i in ids if "acc" in task_res.get(i, {})]
            return round(statistics.fmean(vals), 4) if vals else None

        scenario_scores = {s: avg([t.id for t in tasks if t.scenario == s and t.scored]) for s in SCENARIOS}
        swap = task_res.get("tw-stance-swap", {})
        lat = [r["latency_ms"] for r in records
               if r["model"] == mid and r.get("ok") and r.get("latency_ms") and not r.get("cached")]
        models.append({
            "id": mid, "vendor": info.vendor, "tier": tier, "mods": mods,
            "doc_mods": list(info.documented_modalities),
            "price": info.usd_per_m_input, "free": info.usd_per_m_input == 0 and mid not in WEB_GROUNDED,
            "web": mid in WEB_GROUNDED,
            "latency": round(statistics.median(lat)) if lat else None,
            "di": _di(info.notes), "notes": info.notes,
            # 四項都有數據才算綜合（純文字模型只能跑其中兩項，混算會不公平）
            "composite": avg(DISCRIMINATIVE) if all("acc" in task_res.get(i, {}) for i in DISCRIMINATIVE) else None,
            "neutral": None if "delta" not in swap else round(1 - swap["delta"], 4),
            "scenarios": scenario_scores, "tasks": task_res,
        })

    return {
        "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        "runs": len(metas),
        "requests": len(records),
        "cost": round(sum(r.get("cost_usd") or 0 for r in records), 4),
        "scenarios": SCENARIOS,
        "discriminative": DISCRIMINATIVE,
        "tasks": [{"id": t.id, "title": t.title, "scenario": t.scenario, "scored": t.scored,
                   "n": len(t.items), "modalities": sorted(t.modalities)} for t in tasks],
        "models": models,
    }


def _section(text: str, name: str) -> str:
    start, end = f"<!--{name}-->", f"<!--/{name}-->"
    return text[text.index(start) + len(start):text.index(end)]


def _section(text: str, name: str) -> str:
    start, end = f"<!--{name}-->", f"<!--/{name}-->"
    return text[text.index(start) + len(start):text.index(end)]


def build_dashboard(out: Path = OUT) -> Path:
    from .site import page
    data = build_data()
    tpl = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    script = _section(tpl, "SCRIPT").replace("/*__DATA__*/null", payload)
    out.write_text(page(title="Dashboard｜Decision Arena", active="dashboard", generated=data["generated"], path="bench-dashboard.html",
                        description="互動式 Decision 模型 Dashboard：依模態、情境、分數與價格篩選可用模型。",
                        body=_section(tpl, "BODY"), extra_css=_section(tpl, "CSS"), scripts=script), encoding="utf-8")
    return out
