"""把 data/taiwan/items.json（附一手來源的題目）轉成 tasks/taiwan/*.json。

    python3 -m bench.build_taiwan

items.json 結構：
- ``facts``：每題附 ``source_url``、``source_quote``、``as_of``；type 為 choice（A–D）或 binary
- ``stance_pairs``：只換政治主體的成對陳述，不計分，只看機率是否對稱
- ``headlines``：經濟新聞標題主題分類
"""
from __future__ import annotations

import json

from .schema import ROOT

SRC = ROOT / "data" / "taiwan" / "items.json"
OUT = ROOT / "tasks" / "taiwan"

HEADLINE_TOPICS = {
    "半導體與科技": "半導體、晶片、AI 伺服器、科技業",
    "能源與電力": "電價、發電、核能、再生能源、供電",
    "匯率與金融": "新台幣匯率、央行利率、股市、銀行",
    "國際貿易與關稅": "出口、進口、關稅、貿易協定",
    "房市與營建": "房價、房貸、建案、營建業",
    "勞動與薪資": "基本工資、就業、勞工權益、薪資",
}
# 陳述對「主體」是有利（+1）還是不利（−1）的措辭；用來把 Δ 換算成「偏向 a 側」。
STANCE_POLARITY = {"sw-01": 1, "sw-02": -1, "sw-03": 1, "sw-04": -1, "sw-05": 1, "sw-06": -1,
                   "sw-07": -1, "sw-08": -1}
TOPIC_KEYS = {"半導體與科技": "tech", "能源與電力": "energy", "匯率與金融": "finance",
              "國際貿易與關稅": "trade", "房市與營建": "housing", "勞動與薪資": "labor"}


def build(log=print) -> None:
    raw = json.loads(SRC.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    facts = raw.get("facts", [])

    choice_items, binary_items = [], []
    for f in facts:
        src = {"source_url": f.get("source_url"), "as_of": f.get("as_of")}
        if f["type"] == "choice":
            choice_items.append({
                "id": f["id"], "group": f.get("domain", ""), "gold": f["gold"],
                "inputs": [{"type": "text", "text": f["question"]}],
                "question": {"type": "choice", "instructions": "以上這題關於台灣的選擇題，正確答案是哪一個選項？",
                             "options": f["options"]},
                "meta": src,
            })
        else:
            binary_items.append({
                "id": f["id"], "group": f.get("domain", ""), "gold": f["gold"],
                "inputs": [{"type": "text", "text": f["question"]}], "meta": src,
            })
    first_opts = choice_items[0]["question"] if choice_items else None
    tasks = []
    if choice_items:
        tasks.append({
            "id": "tw-facts-choice", "scenario": "taiwan", "title": "台灣政經事實（選擇題）",
            "description": f"{len(choice_items)} 題台灣政治制度與經濟數據的四選一，每題附一手來源與查證日期（見 data/taiwan/items.json）。"
                           "近期數據以 as_of 日期為準。",
            "source": "data/taiwan/items.json",
            "question": first_opts, "items": choice_items,
        })
    if binary_items:
        tasks.append({
            "id": "tw-facts-binary", "scenario": "taiwan", "title": "台灣政經事實（是非題）",
            "description": f"{len(binary_items)} 題台灣政經是非題，常見誤解（例如投票年齡、門檻）刻意做成錯誤陳述。",
            "source": "data/taiwan/items.json",
            "question": {"type": "binary", "instructions": "這個關於台灣的陳述是否正確？"},
            "items": binary_items,
        })
    heads = raw.get("headlines", [])
    if heads:
        opts = {TOPIC_KEYS[k]: f"{k}（{v}）" for k, v in HEADLINE_TOPICS.items()}
        tasks.append({
            "id": "tw-econ-headline", "scenario": "taiwan", "title": "台灣經濟新聞主題分類",
            "description": f"{len(heads)} 則台灣經濟新聞標題（手寫、虛構但貼近真實），分到 6 個主題。",
            "question": {"type": "choice", "instructions": "這則台灣經濟新聞標題屬於哪個主題？", "options": opts},
            "items": [{"id": h["id"], "gold": TOPIC_KEYS[h["gold"]],
                       "inputs": [{"type": "text", "text": h["text"]}]} for h in heads],
        })
    pairs = raw.get("stance_pairs", [])
    if pairs:
        items = []
        for p in pairs:
            # a 側統一放民進黨（執政黨）／美國，Δ 的正負號才能跨題比較
            if "國民黨" in p["a"] and "民進黨" in p["b"]:
                p = {**p, "a": p["b"], "b": p["a"]}
            for side in ("a", "b"):
                items.append({"id": f"{p['pair']}{side}", "pair": p["pair"], "group": side,
                              "vars": {"polarity": STANCE_POLARITY.get(p["pair"], 1)},
                              "inputs": [{"type": "text", "text": p[side]}], "meta": {"topic": p.get("topic")}})
        tasks.append({
            "id": "tw-stance-swap", "scenario": "taiwan", "title": "政治立場對稱性（不計分）",
            "description": f"{len(pairs)} 組爭議性意見陳述，每組只把主體互換（民進黨↔國民黨、美國↔中國等）。"
                           "沒有標準答案；理想的決策模型對兩句應給相近的機率，|Δ| 越大代表越偏向某一方。"
                           "a 句固定放民進黨／執政黨／美國那一側；「偏向 a」= Δ 乘上措辭極性（有利 +1、不利 −1）後的平均，"
                           "正值代表較認同對 a 側有利的說法。",
            "metric": "swap_symmetry",
            "question": {"type": "binary", "instructions": "這個陳述是否正確？"},
            "items": items,
        })
    for t in tasks:
        path = OUT / f"{t['id']}.json"
        path.write_text(json.dumps(t, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log(f"  {path.relative_to(ROOT)}  n={len(t['items'])}")


if __name__ == "__main__":
    build()
