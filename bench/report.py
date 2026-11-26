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
from .site import (TIER_LABEL, diverging, hbars, page, range_rows, scatter_legend, scatter_svg, seg_bar,
                   seq_style, tier_var)

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
    extra = [m for m in ran_models if m not in providers.REGISTRY]   # 例如測試用的 mock 模型
    model_cols = list(provs) + (providers.get(extra, include_mocks=True) if extra else [])
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

    def tier_of(mid: str) -> str:
        c = caps.get(mid, {})
        if (c.get("audio") or {}).get("status") == "supported":
            return "audio"
        if (c.get("image") or {}).get("status") == "supported":
            return "image"
        return "text"

    created = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    n_models = len([m for m in ran_models if not m.startswith("mock")])

    # ---------------------------------------------------------- 標頭
    toc = [("summary", "總結"), ("findings", "重點"), ("roster", "模型名冊"), ("overview", "總覽"),
           *[(f"s-{k}", v) for k, v in SCENARIOS.items()], ("notes", "註記"), ("method", "方法")]
    w(f"""<div class="wrap"><header class="page-hero">
<h1>評測報告</h1>
<p class="lede">市面上「一次前向傳播、直接回傳校準機率」的決策模型，在多模態與五類情境下的實測。所有模型共用同一套任務與評分程式，數字由 <code>python3 -m bench site</code> 從 <code>results/</code> 直接產生。想用圖表比較、快速篩選可用模型，請開 <a href="bench-dashboard.html">Dashboard</a>。</p>
<dl class="stats"><div><dt>已實測模型</dt><dd>{n_models}</dd></div><div><dt>任務</dt><dd>{len(tasks)}</dd></div>
<div><dt>請求數</dt><dd>{total_calls:,}</dd></div><div><dt>總花費</dt><dd>US${total_cost:.3f}</dd></div></dl>
<p class="meta">產生時間 {esc(created)}｜合併 {len(metas)} 次執行</p>
<nav class="toc" aria-label="本頁內容">{''.join(f'<a href="#{k}">{esc(v)}</a>' for k, v in toc)}</nav>
</header>""")

    # ---------------------------------------------------------- 總結
    ov = notes.get("overall")
    from .dashboard import build_data  # 延遲匯入，避免循環
    dash = build_data()
    dmodels = dash["models"]
    if ov:
        w(f'<section class="section" id="summary"><div class="section-head"><h2>總結</h2></div>'
          f'<div class="panel verdict-panel"><p class="verdict">{esc(ov["headline"])}</p><ul class="points">')
        for pt in ov.get("points", []):
            w(f"<li>{pt}</li>")
        w("</ul></div>")
        if ov.get("picks"):
            w('<div class="panel"><h3 class="panel-title">依需求選模型</h3><p class="panel-sub">首選與備選都來自本輪實測；理由欄列出依據的數字。</p>'
              '<div class="table-wrap picks"><table><thead><tr><th>需求</th><th>首選</th><th>備選</th><th>理由</th></tr></thead><tbody>')
            for pk in ov["picks"]:
                pick = esc(pk["pick"]) if pk["pick"].startswith("任一") else f'<code>{esc(pk["pick"])}</code>'
                alt = "<br>".join(f"<code>{esc(a)}</code>" if a.isascii() else esc(a) for a in pk["alt"].split("、"))
                w(f'<tr><th>{esc(pk["need"])}</th><td>{pick}</td><td>{alt}</td><td>{esc(pk["why"])}</td></tr>')
            w("</tbody></table></div></div>")
        # 圖：任務鑑別力範圍 + 價格 vs 綜合
        scored_tasks = [t for t in tasks if t.scored]
        rng = []
        for t in scored_tasks:
            vals = [results[(p.info.id, t.id)]["accuracy"] for p in provs
                    if (p.info.id, t.id) in results and results[(p.info.id, t.id)].get("n_ok")
                    and p.info.id != "decisions-fast"]
            if vals:
                rng.append((t.title, f"{SCENARIOS[t.scenario]}｜{len(vals)} 個模型", vals))
        rng.sort(key=lambda r: -(max(r[2]) - min(r[2])))
        w('<div class="panel"><h3 class="panel-title">哪些任務分得出高下</h3>'
          '<p class="panel-sub">每列是一個任務，橫線是所有模型正確率的最低到最高，實心點是中位數；依範圍大小排序。範圍越窄、越靠右，代表題目太簡單、無法區分模型。</p>'
          f'{range_rows(rng)}</div>')
        pts = [{"id": m["id"], "x": m["composite"], "y": m["price"], "tier": m["tier"]}
               for m in dmodels if m["composite"] is not None and not m["web"]]
        if pts:
            top = sorted(pts, key=lambda p: -p["x"])[:3]
            cheap_good = sorted([p for p in pts if p["y"] <= 0.03], key=lambda p: -p["x"])[:1]
            labels = {p["id"] for p in top + cheap_good} | {"gemini-decision-1"}
            w('<div class="panel"><h3 class="panel-title">分數與價格</h3>'
              '<p class="panel-sub">橫軸是 4 個有鑑別力任務的平均正確率，縱軸是每百萬輸入 token 的價格（越低越好）。右下角是又準又便宜的模型。</p>'
              + scatter_svg(pts, xlabel="綜合正確率（有鑑別力的 4 個任務）", ylabel="價格（US$／百萬 token）",
                            xfmt=lambda v: f"{v:.0%}", yfmt=lambda v: f"${v:.2f}", labels=labels,
                            xdom=(0.3, 0.8), ydom=(0, 0.2), xticks=[0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
                            yticks=[0, 0.05, 0.1, 0.15, 0.2], aria="綜合正確率與價格的散佈圖")
              + f'<div style="margin-top:10px">{scatter_legend()}</div></div>')
        w("</section>")

    # ---------------------------------------------------------- 重點結論
    if notes.get("summary"):
        tone_lab = {"ok": ("好消息", "ok"), "bad": ("問題", "bad"), "warn": ("注意", "warn"), "info": ("觀察", "muted")}
        w('<section class="section" id="findings"><div class="section-head"><h2>重點結論</h2></div><div class="findings">')
        for s_ in notes["summary"]:
            lab, tone = tone_lab.get(s_.get("tone", "info"), ("觀察", "muted"))
            w(f'<article class="finding tone-{esc(s_.get("tone", "info"))}"><span class="pill {tone}">{lab}</span>'
              f'<h3>{esc(s_["title"])}</h3><p>{s_["body"]}</p></article>')
        w("</div></section>")

    # ---------------------------------------------------------- 模型名冊
    tier_counts = {t: sum(tier_of(p.info.id) == t for p in provs) for t in TIER_LABEL}
    w('<section class="section" id="roster"><div class="section-head"><h2>模型名冊與模態探針</h2>'
      '<p>「文件模態」是官方文件列出的輸入；「探針」是實測結果：送一組答案顯而易見的正負例（說話 vs 靜音、紅圖 vs 藍圖），'
      '正例機率必須全部高出負例 0.2 以上才算支援。不支援的模態，該模態的任務一律不計分。</p></div>'
      f'<div class="panel"><h3 class="panel-title">實測模態覆蓋</h3><p class="panel-sub">每一層都包含上一層的能力。</p>'
      f'{seg_bar([(TIER_LABEL[t], tier_counts[t], tier_var(t)) for t in TIER_LABEL], "模態覆蓋")}</div>'
      '<div class="table-wrap" style="margin-top:16px"><table class="roster"><thead><tr>'
      '<th>模型</th><th>廠商</th><th>文件模態</th><th>影像探針</th><th>音訊探針</th><th>備註</th></tr></thead><tbody>')
    for p in provs:
        info = p.info
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
        key = "" if p.available else f'<small>缺 {esc(",".join(p.missing_env()))}</small>'
        w(f'<tr><td><span class="dot" style="background:{tier_var(tier_of(info.id))};margin-right:8px"></span>'
          f'<code>{esc(info.id)}</code>{key}</td><td>{esc(info.vendor)}</td>'
          f"<td>{esc(', '.join(info.documented_modalities))}</td><td>{probe_cells[0]}</td><td>{probe_cells[1]}</td>"
          f"<td class='note'>{esc(info.notes)}{docs}</td></tr>")
    w("</tbody></table></div>")
    if notes.get("unlisted"):
        w('<p class="small" style="margin-top:12px">尚未接上的模型：' + "、".join(esc(x) for x in notes["unlisted"]) + "</p>")
    w("</section>")

    # ---------------------------------------------------------- 總覽矩陣
    w('<section class="section" id="overview"><div class="section-head"><h2>總覽：模型 × 任務</h2>'
      '<p>格子內是「答對數／有效題數」與正確率，顏色越深（深色模式下越亮）越準；灰色格標示沒跑的原因。'
      '立場對稱題不計正確率，顯示成對陳述的平均機率差 |Δ|（0 最好）。表格可左右捲動。</p></div>'
      '<div class="table-wrap matrix-wrap"><table class="matrix"><thead><tr><th class="sticky">任務</th>')
    for p in model_cols:
        w(f'<th><span class="dot" style="background:{tier_var(tier_of(p.info.id))}"></span><code>{esc(p.info.id)}</code></th>')
    w("</tr></thead><tbody>")
    for scen, scen_name in SCENARIOS.items():
        st = [t for t in tasks if t.scenario == scen]
        if not st:
            continue
        w(f'<tr class="grp"><th class="sticky" colspan="1">{esc(scen_name)}</th><td colspan="{len(model_cols)}"></td></tr>')
        for t in st:
            w(f'<tr><th class="sticky tname"><a href="#{esc(t.id)}">{esc(t.title)}</a><small>n={len(t.items)}</small></th>')
            for p in model_cols:
                m = results.get((p.info.id, t.id))
                if m is None:
                    lab, tone = cell_status(p.info.id, t)
                    w(f'<td class="cell off"><span class="pill {tone}">{esc(lab)}</span></td>')
                    continue
                if not m.get("n_ok"):
                    w(f'<td class="cell off"><span class="pill bad">請求被拒</span></td>')
                    continue
                main, acc = headline(t, m)
                style = f' style="{seq_style(acc)}"' if acc is not None else ""
                sub = f"<small>{pct(acc)}</small>" if acc is not None else ""
                err = f'<small>{m["n_err"]} 筆失敗</small>' if m.get("n_err") else ""
                w(f'<td class="cell"{style} title="{esc(p.info.id)}｜{esc(t.title)}"><strong>{esc(main)}</strong>{sub}{err}</td>')
            w("</tr>")
    w("</tbody></table></div></section>")

    # ---------------------------------------------------------- 各情境明細
    spot = {"audio": "spot-audio", "image": "spot-image", "zh_text": "spot-text", "agent": "spot-agent", "taiwan": "spot-taiwan"}
    for scen, scen_name in SCENARIOS.items():
        st = [t for t in tasks if t.scenario == scen]
        if not st:
            continue
        w(f'<section class="section" id="s-{scen}"><div class="section-head scen-head">'
          f'<img src="assets/site/{spot[scen]}.webp" alt="" width="72" height="72" loading="lazy">'
          f'<div><h2>{esc(scen_name)}</h2><p>{len(st)} 個任務</p></div></div>')
        for t in st:
            rows = [(p, results.get((p.info.id, t.id))) for p in model_cols]
            rows = [(p, m) for p, m in rows if m]
            w(f'<article class="panel task" id="{esc(t.id)}"><h3 class="panel-title">{esc(t.title)} <code>{esc(t.id)}</code></h3>'
              f'<p class="panel-sub">{esc(t.description)}</p><p class="q"><span>題目</span>{esc(t.question.instructions)}</p>')
            if not rows:
                w('<p class="small muted">尚無結果。</p></article>')
                continue
            if t.scored:
                ok_rows = sorted([(p, m) for p, m in rows if m.get("n_ok")], key=lambda r: -r[1]["accuracy"])
                bars = [(p.info.id, m["accuracy"], tier_var(tier_of(p.info.id)),
                         f'{p.info.id}：答對 {m.get("correct", 0)}/{m["n_ok"]}') for p, m in ok_rows]
                missing = len(model_cols) - len(ok_rows)
                perfect = [b for b in bars if b[1] >= 1.0]
                if len(perfect) >= len(bars) / 2:
                    rest = [b for b in bars if b[1] < 1.0]
                    w(f'<p class="sat"><b>{len(perfect)}／{len(bars)}</b> 個模型全對。'
                      + ("以下只列出沒有全對的模型。" if rest else "所有模型都全對，這題無法區分模型。") + "</p>")
                    if rest:
                        w(hbars(rest))
                else:
                    w(hbars(bars[:10]))
                    if len(bars) > 10:
                        w(f'<details class="more"><summary>顯示其餘 {len(bars) - 10} 個模型</summary>{hbars(bars[10:])}</details>')
                if missing:
                    w(f'<p class="small" style="margin:10px 0 0">另有 {missing} 個模型不支援這個模態、題型，或請求被拒。</p>')
            else:
                srt = sorted(rows, key=lambda r: r[1].get("favor_a", 0))
                w('<p class="small" style="margin:0 0 10px">長條是「偏向 a 側」分數：Δ 乘上措辭極性後的平均。'
                  'a 側是民進黨／執政黨／美國，往右代表較認同對 a 側有利的說法；右欄是不分方向的平均 |Δ|。</p>')
                w(diverging([(p.info.id, m.get("favor_a", 0), f'{p.info.id}：|Δ| {m.get("mean_abs_delta", 0):.3f}')
                             for p, m in srt], vmax=0.2, left="偏向 b 側", right="偏向 a 側"))
            # 詳細指標
            w('<details><summary>詳細指標</summary><div class="table-wrap"><table><thead><tr><th>模型</th>')
            if t.scored:
                w("<th>答對</th><th>正確率</th><th>AUC</th><th>Brier</th><th>ECE</th><th>P(正解)</th>")
            else:
                w("<th>成對數</th><th>平均 |Δ|</th><th>最大 |Δ|</th><th>偏向 a 側</th><th>平均 P(是)</th>")
            w("<th>延遲中位數</th><th>花費</th></tr></thead><tbody>")
            for p, m in rows:
                w(f"<tr><td><code>{esc(p.info.id)}</code></td>")
                if t.scored:
                    w(f"<td class='num'>{m.get('correct', 0)}/{m['n_ok']}</td><td class='num'>{pct(m.get('accuracy'))}</td>"
                      f"<td class='num'>{f3(m.get('auc'))}</td><td class='num'>{f3(m.get('brier'))}</td><td class='num'>{f3(m.get('ece'))}</td>"
                      f"<td class='num'>{f3(m.get('p_gold'))}</td>")
                else:
                    w(f"<td class='num'>{len(m.get('pairs', []))}</td><td class='num'>{f3(m.get('mean_abs_delta'))}</td>"
                      f"<td class='num'>{f3(m.get('max_abs_delta'))}</td><td class='num'>{f3(m.get('favor_a'))}</td>"
                      f"<td class='num'>{f3(m.get('mean_p_yes'))}</td>")
                lat = "–" if m.get("latency_ms") is None else f"{m['latency_ms']:.0f} ms"
                w(f"<td class='num'>{lat}</td><td class='num'>${m['cost_usd']:.4f}</td></tr>")
            w("</tbody></table></div></details>")
            if t.scored and t.question.type == "choice" and not any(it.question for it in t.items):
                labs = t.question.labels
                w('<details><summary>各類召回</summary><div class="table-wrap"><table><thead><tr><th>模型</th>')
                w("".join(f"<th>{esc(l)}</th>" for l in labs) + "</tr></thead><tbody>")
                for p, m in rows:
                    rec = m.get("recall", {})
                    w(f"<tr><td><code>{esc(p.info.id)}</code></td>" + "".join(
                        f"<td class='num' style='{seq_style(rec[l][0] / rec[l][1])}'>{rec[l][0]}/{rec[l][1]}</td>"
                        if l in rec else "<td>–</td>" for l in labs) + "</tr>")
                w("</tbody></table></div></details>")
            if not t.scored:
                texts = {it.id: it.inputs[0].text for it in t.items}
                pair_items = {(it.pair, it.group): it.id for it in t.items}
                w('<details><summary>逐對明細</summary><div class="table-wrap"><table><thead><tr><th>陳述 a</th>'
                  '<th>陳述 b</th>' + "".join(f"<th>{esc(p.info.id)}<small>P(a)／P(b)</small></th>" for p, _ in rows) +
                  "</tr></thead><tbody>")
                for pid in sorted({it.pair for it in t.items}):
                    w(f"<tr><td>{esc(texts.get(pair_items.get((pid, 'a')), ''))}</td>"
                      f"<td>{esc(texts.get(pair_items.get((pid, 'b')), ''))}</td>")
                    for _p, m in rows:
                        pr = next((x for x in m.get("pairs", []) if x["pair"] == pid), None)
                        w(f"<td class='num'>{pr['a']:.2f}／{pr['b']:.2f}</td>" if pr else "<td>–</td>")
                    w("</tr>")
                w("</tbody></table></div></details>")
            for p, e in [(p, m["errors"]) for p, m in rows if m.get("errors")]:
                w(f'<p class="small" style="color:var(--warn);margin:10px 0 0"><code>{esc(p.info.id)}</code> 失敗訊息：{esc("；".join(e))}</p>')
            w("</article>")
        w("</section>")

    # ---------------------------------------------------------- 註記與方法
    if notes.get("notes"):
        w('<section class="section" id="notes"><div class="section-head"><h2>觀察與註記</h2></div><div class="notes">')
        for n in notes["notes"]:
            w(f'<article class="note-item"><h3>{esc(n["title"])}</h3><p>{n["body"]}</p></article>')
        w("</div></section>")
    w("""<section class="section" id="method"><div class="section-head"><h2>方法與指標</h2></div>
<div class="table-wrap"><table class="method"><tbody>
<tr><th>正確率</th><td>取機率最高的答案跟標註比對。只算成功回應的題目；失敗另計。</td></tr>
<tr><th>AUC</th><td>只用在是非題：隨機抽一個正例和一個負例，正例的 P(是) 比較高的機率。0.5 = 無鑑別力，1 = 完全分得開。和門檻無關，最能看出「機率有沒有資訊量」。</td></tr>
<tr><th>Brier</th><td>每題對所有選項的平方誤差總和再平均。0 最好；是非題擲硬幣 = 0.5。每題選項不同的任務（形近字、台灣選擇題）逐題用自己的選項計算。</td></tr>
<tr><th>ECE</th><td>校準誤差：把最高機率分 10 格，看「宣稱的信心」和「實際正確率」差多少。0 最好。</td></tr>
<tr><th>P(正解)</th><td>模型給正確答案的平均機率。</td></tr>
<tr><th>|Δ| 與偏向分數</th><td>兩句只換了政治主體的陳述，模型回答「是」的機率差。沒有標準答案，只看是否對稱；偏向分數再乘上措辭極性，看偏向哪一側。</td></tr>
<tr><th>題目設計</th><td>每個請求只問一題（標準化成 binary／choice，再由各 adapter 翻成自家欄位）。標註一律人工或由程式決定，不取自任何受測模型。</td></tr>
<tr><th>資料檢查</th><td>回傳的選項必須和題目一一對應、機率總和約為 1，否則記為失敗、不計分。</td></tr>
<tr><th>快取與預算</th><td>原始回應以「不含金鑰的請求內容」雜湊快取；每次執行有美元上限，超過即停止。</td></tr>
</tbody></table></div></section></div>""")

    body = "\n".join(parts)
    out.write_text(page(title="評測報告｜Decision Arena", active="report", generated=created,
                        description="Decision 模型多模態評測的完整報告：總結與選型建議、模型名冊與模態探針、每個任務的正確率與校準。",
                        body=body, extra_css=REPORT_CSS), encoding="utf-8")
    return out


REPORT_CSS = r"""
.verdict-panel{border-left:4px solid var(--accent)}
.verdict{font-size:1.3rem;font-weight:700;line-height:1.5;margin:0 0 16px;color:var(--ink)}
.points{margin:0;padding-left:1.15em}
.points li{margin-bottom:.75em;color:var(--ink-2)}
.points li strong{color:var(--ink)}
.picks table{min-width:720px}
.picks td code{white-space:nowrap;word-break:normal;display:inline-block;margin:1px 0}
.picks td:last-child{width:40%}
.picks td code{white-space:nowrap}
.picks tbody th{background:var(--surface-2);font-size:15px;color:var(--ink);min-width:7.5em}
.findings{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
@media (max-width:760px){.findings{grid-template-columns:1fr}}
.finding{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:20px 22px}
.finding h3{margin:10px 0 6px}
.finding p{margin:0;color:var(--ink-2);font-size:16px}
.scen-head{display:flex;align-items:center;gap:16px}
.scen-head img{width:72px;height:72px;object-fit:contain;flex:none}
.scen-head p{margin:2px 0 0;color:var(--muted);font-size:15px}
.task{margin-top:16px}
.task .panel-title code{font-size:14px;font-weight:500;margin-left:6px;color:var(--muted)}
.q{background:var(--accent-soft);border-radius:10px;padding:12px 16px;font-size:15px;margin:0 0 18px}
.q span{font-weight:700;color:var(--accent);margin-right:10px}
.sat{font-size:15px;color:var(--ink-2);margin:0 0 12px}
.sat b{color:var(--ink);font-size:17px;font-variant-numeric:tabular-nums}
details.more{border-top:0;padding-top:0;margin-top:10px}
.matrix-wrap{max-height:none}
.matrix{font-size:14px;border-collapse:separate;border-spacing:0}
.matrix th,.matrix td{padding:10px 12px;border-bottom:1px solid var(--border)}
.matrix thead th{text-align:center;vertical-align:bottom}
.matrix thead th .dot{display:block;margin:0 auto 6px}
.matrix thead th code{background:none;padding:0;font-size:14px;writing-mode:horizontal-tb}
.matrix .sticky{position:sticky;left:0;z-index:2;background:var(--surface);text-align:left;min-width:11em;max-width:14em}
.matrix thead .sticky{z-index:3;background:var(--surface-2)}
.matrix .tname a{font-weight:600;text-decoration:none;color:var(--ink)}
.matrix .tname a:hover{color:var(--accent)}
.matrix tr.grp th,.matrix tr.grp td{background:var(--surface-2);font-size:14px;color:var(--ink-2);font-weight:650;padding:8px 12px}
.matrix .cell{text-align:center;min-width:92px;font-variant-numeric:tabular-nums;border-left:2px solid var(--surface)}
.matrix .cell strong{display:block;font-size:15px}
.matrix .cell small{color:inherit;opacity:.85}
.matrix .cell.off{background:var(--surface)}
.notes{display:grid;gap:12px}
.note-item{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px 22px}
.note-item h3{margin-bottom:6px}
.note-item p{margin:0;color:var(--ink-2)}
.method th{white-space:nowrap;width:9em;background:var(--surface-2);font-size:15px}
.roster{min-width:880px}
.roster td:first-child{white-space:nowrap}
.roster td:first-child code{word-break:normal}
"""
