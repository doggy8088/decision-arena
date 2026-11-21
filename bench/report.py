"""由 results/ 產生單檔 HTML 報告 bench-report.html（CSS 內嵌、支援深色模式）。

合併規則：同一個 (模型, 任務, 題項) 出現在多次執行時，以 run id 排序較後者為準。
手寫的結論與註記放在 ``results/notes.json``（``{"summary": [...], "notes": [...]}``）。
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from . import metrics, providers
from .runner import CAPS_FILE, RESULTS_DIR, load_caps
from .schema import ROOT, SCENARIOS, load_tasks

OUT = ROOT / "bench-report.html"
NOTES = RESULTS_DIR / "notes.json"

STATUS_LABEL = {
    "supported": ("支援", "ok"), "ignored": ("收下但沒在看", "bad"), "rejected": ("拒收", "bad"),
    "error": ("探針失敗", "warn"), "unprobed": ("未探測", "muted"),
}


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def pct(x) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def f3(x) -> str:
    return "–" if x is None else f"{x:.3f}"


def load_runs(run_ids: list[str] | None = None):
    runs_dir = RESULTS_DIR / "runs"
    dirs = sorted(d for d in runs_dir.iterdir() if d.is_dir()) if runs_dir.is_dir() else []
    if run_ids:
        dirs = [d for d in dirs if d.name in run_ids]
    records: dict[tuple, dict] = {}
    cells: dict[tuple, dict] = {}
    metas = []
    for d in sorted(dirs, key=lambda p: json.loads((p / "meta.json").read_text())["created"]):
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        metas.append(meta)
        for c in meta.get("cells", []):
            cells[(c["model"], c["task"])] = c
        for line in (d / "records.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            r["run_id"] = meta["run_id"]
            records[(r["model"], r["task"], r["item"])] = r
    return list(records.values()), cells, metas


def cell_metrics(task, recs):
    if task.scored:
        labels = task.question.labels
        # 單題覆寫選項（形近字、台灣選擇題）時，逐題用自己的選項計算多類別指標
        if any(it.question for it in task.items):
            per = {it.id: task.question_for(it).labels for it in task.items}
            m = metrics.classification_per_item(recs, per)
        else:
            m = metrics.classification(recs, labels, task.positive)
    else:
        pol = {it.pair: int(it.vars.get("polarity", 1)) for it in task.items}
        m = metrics.swap_symmetry(recs, task.positive, pol)
    m["latency_ms"] = metrics.median(r.get("latency_ms") for r in recs if r.get("ok") and not r.get("cached"))
    if m["latency_ms"] is None:
        m["latency_ms"] = metrics.median(r.get("latency_ms") for r in recs if r.get("ok"))
    m["cost_usd"] = sum(r.get("cost_usd") or 0 for r in recs)
    m["errors"] = sorted({(r.get("error") or "")[:120] for r in recs if not r.get("ok")})[:3]
    return m


def build_report(run_ids: list[str] | None = None, out: Path = OUT) -> Path:
    tasks = load_tasks()
    provs = providers.get()
    caps = load_caps()
    records, cells, metas = load_runs(run_ids)
    notes = json.loads(NOTES.read_text(encoding="utf-8")) if NOTES.is_file() else {}

    by_cell: dict[tuple, list] = {}
    for r in records:
        by_cell.setdefault((r["model"], r["task"]), []).append(r)
    results = {k: cell_metrics(next(t for t in tasks if t.id == k[1]), v)
               for k, v in by_cell.items() if any(t.id == k[1] for t in tasks)}
    ran_models = sorted({k[0] for k in results})
    model_cols = [p for p in provs] + [p for p in providers.get(
        [m for m in ran_models if m not in providers.REGISTRY], include_mocks=True)]
    total_cost = sum(m["cost_usd"] for m in results.values())
    total_calls = sum(len(v) for v in by_cell.values())

    def cell_status(model, task):
        if (model, task.id) in results:
            return None
        c = cells.get((model, task.id))
        if c and not c["run"]:
            r = c["reason"]
            if r.startswith("no_key"):
                return ("缺金鑰", "muted")
            if r.startswith("modality:"):
                st = r.split("=")[1]
                return (STATUS_LABEL.get(st, (st, "muted"))[0], STATUS_LABEL.get(st, ("", "muted"))[1])
        return ("未執行", "muted")

    def headline(task, m):
        if task.scored:
            return f"{m.get('correct', 0)}/{m['n_ok']}", m.get("accuracy")
        return f"|Δ| {f3(m.get('mean_abs_delta'))}", None

    parts: list[str] = []
    w = parts.append

    # ---------------------------------------------------------- 標頭
    created = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    w(f"""<header class="hero"><p class="eyebrow">Decision Model Benchmark</p>
<h1>Decision 模型評測</h1>
<p class="lede">市面上「一次前向傳播、直接給校準機率」的決策模型（decision models），在多模態與五類情境下的實測。
所有模型共用同一套任務檔與評分程式，數字由 <code>python3 -m bench report</code> 從 <code>results/</code> 直接產生。</p>
<dl class="kpis">
<div><dt>已實測模型</dt><dd>{len([m for m in ran_models if not m.startswith('mock')])}</dd></div>
<div><dt>任務</dt><dd>{len(tasks)}</dd></div>
<div><dt>請求數</dt><dd>{total_calls:,}</dd></div>
<div><dt>總花費</dt><dd>US${total_cost:.3f}</dd></div>
</dl><p class="meta">產生時間 {esc(created)}｜執行批次 {len(metas)} 次</p></header>""")

    # ---------------------------------------------------------- 結論
    if notes.get("summary"):
        w('<section><h2>重點結論</h2><div class="cards">')
        for s in notes["summary"]:
            w(f'<article class="card tone-{esc(s.get("tone", "info"))}"><h3>{esc(s["title"])}</h3>'
              f'<p>{s["body"]}</p></article>')
        w("</div></section>")

    # ---------------------------------------------------------- 模型名冊
    w('<section><h2>模型名冊與模態探針</h2>'
      '<p>「文件模態」是官方文件列出的輸入；「探針」是我們實測的結果：送一組答案顯而易見的正負例（說話 vs 靜音、紅圖 vs 藍圖），'
      '正例機率必須全部高出負例 0.2 以上才算<strong>支援</strong>。收下請求但分不出正負例，記為<strong>收下但沒在看</strong>，'
      '該模態的任務一律不計分。</p><div class="table-wrap"><table><thead><tr>'
      '<th>模型</th><th>廠商</th><th>金鑰</th><th>文件模態</th><th>影像探針</th><th>音訊探針</th><th>備註</th></tr></thead><tbody>')
    for p in provs:
        info = p.info
        key = '<span class="pill ok">有</span>' if p.available else \
            f'<span class="pill muted">缺 {esc(",".join(p.missing_env()))}</span>'
        probe_cells = []
        for mod in ("image", "audio"):
            ev = caps.get(info.id, {}).get(mod)
            if not ev:
                probe_cells.append('<span class="pill muted">未探測</span>')
                continue
            lab, tone = STATUS_LABEL.get(ev["status"], (ev["status"], "muted"))
            extra = f'<small>margin {ev["margin"]:+.2f}</small>' if ev.get("margin") is not None else ""
            probe_cells.append(f'<span class="pill {tone}">{esc(lab)}</span>{extra}')
        docs = f' <a href="{esc(info.docs)}">文件</a>' if info.docs else ""
        w(f"<tr><td><code>{esc(info.id)}</code></td><td>{esc(info.vendor)}</td><td>{key}</td>"
          f"<td>{esc(', '.join(info.documented_modalities))}</td><td>{probe_cells[0]}</td><td>{probe_cells[1]}</td>"
          f"<td class='note'>{esc(info.notes)}{docs}</td></tr>")
    w("</tbody></table></div>")
    if notes.get("unlisted"):
        w('<p class="small">尚未接上的模型：' + "、".join(esc(x) for x in notes["unlisted"]) + "</p>")
    w("</section>")

    # ---------------------------------------------------------- 總覽矩陣
    w('<section><h2>總覽：模型 × 任務</h2><p>格子內是「答對數／有效題數」與正確率；色塊越飽和表示越準。'
      '灰色格子標示沒跑的原因。台灣政經的立場對稱題不計正確率，顯示成對陳述的平均機率差 |Δ|（0 最好）。</p>'
      '<div class="table-wrap"><table class="matrix"><thead><tr><th>情境</th><th>任務</th>')
    for p in model_cols:
        w(f"<th><code>{esc(p.info.id)}</code></th>")
    w("</tr></thead><tbody>")
    for scen, scen_name in SCENARIOS.items():
        st = [t for t in tasks if t.scenario == scen]
        for i, t in enumerate(st):
            w("<tr>")
            if i == 0:
                w(f'<th rowspan="{len(st)}" class="scen">{esc(scen_name)}</th>')
            w(f'<td class="tname"><a href="#{esc(t.id)}">{esc(t.title)}</a><small>n={len(t.items)}</small></td>')
            for p in model_cols:
                m = results.get((p.info.id, t.id))
                if m is None:
                    lab, tone = cell_status(p.info.id, t)
                    w(f'<td class="cell muted"><span class="pill {tone}">{esc(lab)}</span></td>')
                    continue
                if not m.get("n_ok"):
                    w(f'<td class="cell muted"><span class="pill bad">請求被拒</span><small>{m["n_err"]} 筆</small></td>')
                    continue
                main, acc = headline(t, m)
                level = "" if acc is None else f" lv{min(4, int(acc * 5))}"
                err = f'<small class="warn-t">{m["n_err"]} 筆失敗</small>' if m.get("n_err") else ""
                sub = f"<small>{pct(acc)}</small>" if acc is not None else ""
                w(f'<td class="cell{level}"><strong>{esc(main)}</strong>{sub}{err}</td>')
            w("</tr>")
    w("</tbody></table></div></section>")

    # ---------------------------------------------------------- 各情境明細
    for scen, scen_name in SCENARIOS.items():
        st = [t for t in tasks if t.scenario == scen]
        if not st:
            continue
        w(f'<section><h2>{esc(scen_name)}</h2>')
        for t in st:
            w(f'<article class="task" id="{esc(t.id)}"><h3>{esc(t.title)} <code>{esc(t.id)}</code></h3>'
              f'<p>{esc(t.description)}</p><p class="q"><span>題目</span>{esc(t.question.instructions)}</p>')
            rows = [(p, results.get((p.info.id, t.id))) for p in model_cols]
            rows = [(p, m) for p, m in rows if m]
            if not rows:
                w('<p class="small muted-t">尚無結果。</p></article>')
                continue
            w('<div class="table-wrap"><table><thead><tr><th>模型</th>')
            if t.scored:
                w("<th>答對</th><th>正確率</th><th>AUC</th><th>Brier</th><th>ECE</th><th>P(正解)</th>")
            else:
                w("<th>成對數</th><th>平均 |Δ|</th><th>最大 |Δ|</th><th>偏向 a 側</th><th>平均 P(是)</th>")
            w("<th>延遲中位數</th><th>花費</th></tr></thead><tbody>")
            for p, m in rows:
                w(f"<tr><td><code>{esc(p.info.id)}</code></td>")
                if t.scored:
                    w(f"<td>{m.get('correct', 0)}/{m['n_ok']}</td><td>{pct(m.get('accuracy'))}</td>"
                      f"<td>{f3(m.get('auc'))}</td><td>{f3(m.get('brier'))}</td><td>{f3(m.get('ece'))}</td>"
                      f"<td>{f3(m.get('p_gold'))}</td>")
                else:
                    w(f"<td>{len(m.get('pairs', []))}</td><td>{f3(m.get('mean_abs_delta'))}</td>"
                      f"<td>{f3(m.get('max_abs_delta'))}</td><td>{f3(m.get('favor_a'))}</td>"
                      f"<td>{f3(m.get('mean_p_yes'))}</td>")
                lat = "–" if m.get("latency_ms") is None else f"{m['latency_ms']:.0f} ms"
                w(f"<td>{lat}</td><td>${m['cost_usd']:.4f}</td></tr>")
            w("</tbody></table></div>")
            # 各類召回（choice 任務、類別 ≤ 8）
            if t.scored and t.question.type == "choice" and not any(it.question for it in t.items):
                labs = t.question.labels
                w('<details><summary>各類召回</summary><div class="table-wrap"><table><thead><tr><th>模型</th>')
                w("".join(f"<th>{esc(l)}</th>" for l in labs) + "</tr></thead><tbody>")
                for p, m in rows:
                    rec = m.get("recall", {})
                    w(f"<tr><td><code>{esc(p.info.id)}</code></td>" + "".join(
                        f"<td>{rec[l][0]}/{rec[l][1]}</td>" if l in rec else "<td>–</td>" for l in labs) + "</tr>")
                w("</tbody></table></div></details>")
            if not t.scored:
                texts = {it.id: it.inputs[0].text for it in t.items}
                pair_items = {(it.pair, it.group): it.id for it in t.items}
                w('<details><summary>逐對明細</summary><div class="table-wrap"><table><thead><tr><th>陳述 a</th>'
                  '<th>陳述 b</th>' + "".join(f"<th>{esc(p.info.id)}<br>P(a)／P(b)</th>" for p, _ in rows) +
                  "</tr></thead><tbody>")
                pids = sorted({it.pair for it in t.items})
                for pid in pids:
                    w(f"<tr><td>{esc(texts.get(pair_items.get((pid, 'a')), ''))}</td>"
                      f"<td>{esc(texts.get(pair_items.get((pid, 'b')), ''))}</td>")
                    for _p, m in rows:
                        pr = next((x for x in m.get("pairs", []) if x["pair"] == pid), None)
                        w(f"<td>{pr['a']:.2f}／{pr['b']:.2f}</td>" if pr else "<td>–</td>")
                    w("</tr>")
                w("</tbody></table></div></details>")
            errs = [(p, m["errors"]) for p, m in rows if m.get("errors")]
            for p, e in errs:
                w(f'<p class="small warn-t"><code>{esc(p.info.id)}</code> 失敗訊息：{esc("；".join(e))}</p>')
            w("</article>")
        w("</section>")

    # ---------------------------------------------------------- 註記與方法
    if notes.get("notes"):
        w('<section><h2>觀察與註記</h2>')
        for n in notes["notes"]:
            w(f'<article class="callout"><h3>{esc(n["title"])}</h3><p>{n["body"]}</p></article>')
        w("</section>")
    w("""<section><h2>方法與指標</h2><div class="table-wrap"><table><tbody>
<tr><th>正確率</th><td>取機率最高的答案跟標註比對。只算成功回應的題目；失敗另計。</td></tr>
<tr><th>AUC</th><td>只用在是非題：隨機抽一個正例和一個負例，正例的 P(是) 比較高的機率。0.5 = 無鑑別力，1 = 完全分得開。和門檻無關，最能看出「機率有沒有資訊量」。</td></tr>
<tr><th>Brier</th><td>每題對所有選項的平方誤差總和再平均。0 最好；是非題擲硬幣 = 0.5。</td></tr>
<tr><th>ECE</th><td>校準誤差：把最高機率分 10 格，看「宣稱的信心」和「實際正確率」差多少。0 最好。</td></tr>
<tr><th>P(正解)</th><td>模型給正確答案的平均機率。</td></tr>
<tr><th>|Δ|（立場對稱）</th><td>兩句只換了政治主體（例如民進黨 ↔ 國民黨）的陳述，模型回答「是」的機率差。沒有標準答案，只看是否對稱。</td></tr>
<tr><th>題目設計</th><td>每個請求只問一題（標準化成 binary／choice，再由各 adapter 翻成自家欄位）。標註一律人工或由程式決定，不取自任何受測模型。</td></tr>
<tr><th>快取與預算</th><td>原始回應以「不含金鑰的請求內容」雜湊快取；每次執行有美元上限，超過即停止。</td></tr>
</tbody></table></div></section>""")

    body = "\n".join(parts)
    out.write_text(PAGE.replace("{{BODY}}", body), encoding="utf-8")
    return out


PAGE = """<!doctype html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Decision 模型評測</title>
<style>
:root{
  --bg:#f7f7f5; --surface:#ffffff; --surface-2:#f0f1ef; --text:#1c1f22; --text-2:#4a5057; --border:#dcdfe2;
  --accent:#0f6e6e; --accent-soft:#e2f1f0; --link:#0b5f5f;
  --ok:#1f7a3d; --ok-bg:#e3f4e8; --bad:#a3261e; --bad-bg:#fbe7e5; --warn:#8a5a00; --warn-bg:#fdf1d9;
  --muted:#5b6168; --muted-bg:#eceef0;
  --lv0:#ffffff; --lv1:#e6f3f2; --lv2:#c9e6e3; --lv3:#a3d4cf; --lv4:#7cc2bb;
  --code-bg:#eef0ee;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#121416; --surface:#1a1d20; --surface-2:#22262a; --text:#e8eaec; --text-2:#b4bac0; --border:#33383d;
    --accent:#5cc4bb; --accent-soft:#163331; --link:#7dd6cd;
    --ok:#7ed69a; --ok-bg:#16301f; --bad:#ff9a90; --bad-bg:#3a1a17; --warn:#f0c46a; --warn-bg:#352a12;
    --muted:#a6adb4; --muted-bg:#262a2e;
    --lv0:#1a1d20; --lv1:#173230; --lv2:#1c4440; --lv3:#225852; --lv4:#2a6e66;
    --code-bg:#262a2e;
  }
}
:root[data-theme="dark"]{
  --bg:#121416; --surface:#1a1d20; --surface-2:#22262a; --text:#e8eaec; --text-2:#b4bac0; --border:#33383d;
  --accent:#5cc4bb; --accent-soft:#163331; --link:#7dd6cd;
  --ok:#7ed69a; --ok-bg:#16301f; --bad:#ff9a90; --bad-bg:#3a1a17; --warn:#f0c46a; --warn-bg:#352a12;
  --muted:#a6adb4; --muted-bg:#262a2e;
  --lv0:#1a1d20; --lv1:#173230; --lv2:#1c4440; --lv3:#225852; --lv4:#2a6e66;
  --code-bg:#262a2e;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:"PingFang TC","Noto Sans TC","Microsoft JhengHei",system-ui,sans-serif;
  font-size:17px;line-height:1.75}
main{max-width:960px;margin:0 auto;padding:48px 32px 96px}
@media (max-width:640px){main{padding:32px 16px 64px}}
h1,h2,h3{line-height:1.35;margin:0 0 .6em}
h1{font-size:2.2rem;letter-spacing:.01em}
h2{font-size:1.55rem;padding-top:8px;border-top:2px solid var(--border);padding-top:24px}
h3{font-size:1.15rem}
section{margin-top:56px}
p{margin:0 0 1em}
a{color:var(--link)}
code{font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace;font-size:max(14px,.88em);background:var(--code-bg);
  padding:.1em .4em;border-radius:4px;word-break:break-all}
small,.small{font-size:14px;color:var(--text-2)}
.hero .eyebrow{color:var(--accent);font-weight:600;letter-spacing:.08em;text-transform:uppercase;font-size:14px;margin:0 0 8px}
.lede{font-size:1.08rem;color:var(--text-2);max-width:68ch}
.meta{font-size:14px;color:var(--text-2)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:24px 0}
.kpis div{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px}
.kpis dt{font-size:14px;color:var(--text-2)}
.kpis dd{margin:0;font-size:1.6rem;font-weight:700;color:var(--accent)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.card{background:var(--surface);border:1px solid var(--border);border-left:5px solid var(--accent);border-radius:12px;padding:18px 20px}
.card p{margin:0;color:var(--text-2)}
.card.tone-bad{border-left-color:var(--bad)} .card.tone-ok{border-left-color:var(--ok)} .card.tone-warn{border-left-color:var(--warn)}
.callout{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin-bottom:16px}
.callout p:last-child{margin:0}
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--border);border-radius:12px;background:var(--surface);margin:12px 0 16px}
table{border-collapse:collapse;width:100%;font-size:15px;line-height:1.55}
th,td{padding:12px 16px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border)}
thead th{background:var(--surface-2);font-weight:600;white-space:nowrap}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:0}
td.note{color:var(--text-2);font-size:14px;min-width:200px}
td small,th small{display:block}
.matrix th{text-align:center}
.matrix td.cell{text-align:center}
.matrix td.tname{text-align:left;min-width:10em}
.matrix th.scen{background:var(--surface-2);writing-mode:horizontal-tb;white-space:nowrap;text-align:left}
.matrix td a{font-weight:600;text-decoration:none}
.cell{min-width:120px;background:var(--lv0)}
.cell strong{display:block;font-size:16px}
.cell.lv0{background:var(--lv0)} .cell.lv1{background:var(--lv1)} .cell.lv2{background:var(--lv2)}
.cell.lv3{background:var(--lv3)} .cell.lv4{background:var(--lv4)}
.cell.muted{background:var(--surface)}
.pill{display:inline-block;font-size:14px;padding:2px 10px;border-radius:999px;white-space:nowrap;font-weight:600}
.pill.ok{background:var(--ok-bg);color:var(--ok)} .pill.bad{background:var(--bad-bg);color:var(--bad)}
.pill.warn{background:var(--warn-bg);color:var(--warn)} .pill.muted{background:var(--muted-bg);color:var(--muted)}
.warn-t{color:var(--warn)} .muted-t{color:var(--muted)}
.task{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px 22px;margin:20px 0}
.task .table-wrap{background:var(--bg)}
.q{background:var(--accent-soft);border-radius:8px;padding:12px 16px}
.q span{display:inline-block;font-size:14px;font-weight:700;color:var(--accent);margin-right:10px}
details{margin:8px 0}
summary{cursor:pointer;color:var(--link);font-weight:600}
</style>
</head>
<body><main>
{{BODY}}
</main></body></html>
"""
