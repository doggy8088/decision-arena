"""產生網站首頁 index.html（與 Dashboard 同源的資料，數字不手打）。

    python3 -m bench site     # 一次產生首頁、評測報告與 Dashboard
"""
from __future__ import annotations

from pathlib import Path

from .dashboard import build_data
from .schema import ROOT
from .site import TIER_LABEL, esc, hbars, legend_tiers, page, range_rows, seg_bar, strip, tier_var

OUT = ROOT / "index.html"
IMG = "assets/site"

SCEN_SPOT = {"audio": "spot-audio", "image": "spot-image", "zh_text": "spot-text", "agent": "spot-agent", "taiwan": "spot-taiwan"}
SCEN_BLURB = {
    "audio": "辨音、音場分類、發音練習判斷",
    "image": "形近字、注音字卡、數方塊、App 錯誤畫面、圖文一致",
    "zh_text": "繁中評論情緒、詐騙簡訊、客服意圖路由",
    "agent": "工具選擇、是否轉真人、LLM-as-judge",
    "taiwan": "政治制度與經濟數據、新聞分類、立場對稱",
}

HOME_CSS = r"""
.hero{position:relative;padding:72px 0 40px;overflow:hidden}
.hero .wrap{position:relative;z-index:1}
.hero-copy{max-width:31rem}
.hero h1{margin-bottom:20px}
.hero-art{position:absolute;inset:0 0 0 auto;width:min(68%,880px);pointer-events:none}
.hero-art img{width:100%;height:100%;object-fit:cover;object-position:right center;
  -webkit-mask-image:linear-gradient(90deg,transparent 0,#000 28%),linear-gradient(180deg,#000 62%,transparent 100%);
  -webkit-mask-composite:source-in;
  mask-image:linear-gradient(90deg,transparent 0,#000 28%),linear-gradient(180deg,#000 62%,transparent 100%);mask-composite:intersect}
.hero-art .dark{display:none}
:root[data-theme="dark"] .hero-art .light{display:none}
:root[data-theme="dark"] .hero-art .dark{display:block}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]) .hero-art .light{display:none}
  :root:not([data-theme="light"]) .hero-art .dark{display:block}}
.cta{display:flex;flex-wrap:wrap;gap:12px;margin-top:28px}
.btn{display:inline-flex;align-items:center;gap:8px;min-height:46px;padding:0 20px;border-radius:12px;font-weight:650;
  font-size:16px;text-decoration:none;border:1px solid var(--border-strong);color:var(--ink);background:var(--surface)}
.btn:hover{background:var(--surface-2);text-decoration:none}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.btn.primary:hover{filter:brightness(1.08);background:var(--accent)}
@media (max-width:860px){
  .hero{padding:40px 0 8px}
  .hero-art{position:relative;inset:auto;width:auto;height:220px;margin:28px -16px 0}
  .hero-art img{-webkit-mask-image:linear-gradient(180deg,transparent 0,#000 25%,#000 70%,transparent 100%);
    mask-image:linear-gradient(180deg,transparent 0,#000 25%,#000 70%,transparent 100%);object-position:center}
  .hero-copy{max-width:none}
}
.split{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
@media (max-width:860px){.split{grid-template-columns:1fr}}
.finding h3{margin-bottom:6px}
.finding p{color:var(--ink-2);font-size:16px;margin-bottom:18px}
.scen{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px}
.scen article{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:18px 20px 20px;display:flex;flex-direction:column}
.scen img{width:84px;height:84px;object-fit:contain;margin:-4px 0 6px -6px}
.scen h3{margin-bottom:4px}
.scen p{font-size:15px;color:var(--ink-2);margin:0 0 14px}
.scen .best{margin-top:auto;font-size:14px;color:var(--ink-2);border-top:1px solid var(--border);padding-top:12px}
.scen .best b{color:var(--ink);font-variant-numeric:tabular-nums;font-size:16px}
.archive{list-style:none;margin:0;padding:0;border-top:1px solid var(--border)}
.archive li{border-bottom:1px solid var(--border)}
.archive a{display:grid;grid-template-columns:1fr auto;gap:4px 24px;padding:18px 4px;text-decoration:none;color:var(--ink)}
.archive a:hover strong{color:var(--accent)}
.archive strong{font-weight:650}
.archive span{color:var(--ink-2);font-size:15px;grid-column:1}
.archive em{font-style:normal;font-size:14px;color:var(--muted);grid-row:1 / span 2;grid-column:2;align-self:center}
@media (max-width:640px){.archive em{display:none}}
"""


def build_home(out: Path = OUT) -> Path:
    data = build_data()
    models = data["models"]
    by_id = {m["id"]: m for m in models}
    tiers = {t: sum(m["tier"] == t for m in models) for t in TIER_LABEL}
    comp = sorted([(m["id"], m["composite"], m["tier"]) for m in models if m["composite"] is not None],
                  key=lambda r: -r[1])
    labels = {c[0] for c in comp[:2]} | {"gemini-decision-1", comp[-1][0]}

    parts = []
    w = parts.append

    # ------------------------------------------------------------ hero
    w(f"""<section class="hero"><div class="hero-art" aria-hidden="true">
<img class="light" src="{IMG}/hero-light.webp" alt="" width="1536" height="864" fetchpriority="high">
<img class="dark" src="{IMG}/hero-dark.webp" alt="" width="1536" height="864"></div>
<div class="wrap"><div class="hero-copy">
<h1>{len(models)} 個決策模型，<br>同一套考題。</h1>
<p class="lede">決策模型（decision models）不生成文字，一次就回傳每個答案的機率。我們用語音、影像、繁中文字、Agent 守門與台灣政經五類情境測它們，並先確認模型真的看得到圖、聽得到聲音才計分。</p>
<div class="cta"><a class="btn primary" href="bench-dashboard.html">開啟 Dashboard</a><a class="btn" href="bench-report.html">閱讀評測報告</a></div>
</div></div></section>""")

    w(f"""<div class="wrap"><dl class="stats">
<div><dt>模型</dt><dd>{len(models)}</dd></div><div><dt>任務</dt><dd>{len(data['tasks'])}</dd></div>
<div><dt>請求數</dt><dd>{data['requests']:,}</dd></div><div><dt>總花費</dt><dd>US${data['cost']:.2f}</dd></div></dl>""")

    # ------------------------------------------------------------ 量尺
    w(f"""<section class="section"><div class="section-head"><h2>誰的分數比較高</h2>
<p>每條刻度是一個支援影像的模型，位置是它在 4 個最拉得開差距的任務（形近字、注音字卡、台灣選擇題、台灣是非題）上的平均正確率。高度越高表示同分的模型越多。</p></div>
<div class="panel">{strip([(i, v, t) for i, v, t in comp], labels, aria=f"{len(comp)} 個模型的綜合分數分布，最高 {comp[0][0]} {comp[0][1]:.0%}")}
<div style="margin-top:10px">{legend_tiers()}</div>
<p class="small" style="margin:12px 0 0">純文字模型只能跑其中 2 個任務，所以不列入這條量尺；它們的分數請見 Dashboard。</p></div></section>""")

    # ------------------------------------------------------------ 三個重點
    audio_ids = [m["id"] for m in models if m["mods"]["audio"]]
    pron = [(i, by_id[i]["tasks"].get("audio-pron-ok", {}).get("auc"), tier_var("audio"), f"{i}：發音練習 AUC")
            for i in audio_ids]
    pron.sort(key=lambda r: -(r[1] or 0))
    scored = [t for t in data["tasks"] if t["scored"]]
    rng = []
    for t in scored:
        vals = [m["tasks"][t["id"]]["acc"] for m in models if "acc" in m["tasks"].get(t["id"], {}) and not m["web"]]
        rng.append((t["title"], f"{len(vals)} 個模型", vals))
    rng.sort(key=lambda r: -(max(r[2]) - min(r[2])))
    w(f"""<section class="section"><div class="section-head"><h2>三個重點</h2>
<p>完整的分析與每個任務的數據在評測報告裡。</p></div>
<div class="panel finding"><h3>大部分任務分不出高下</h3>
<p>中文文字與 Agent 守門的題目幾乎全員滿分；真正拉開差距的是繁中細節（形近字、注音）與 2025 年後的台灣新事實。下圖依「最高減最低」排序，橫線是所有模型的範圍，實心點是中位數。</p>
{range_rows(rng[:9])}</div>
<div class="split">
<div class="panel finding"><h3>聽得到的只有 {len(audio_ids)} 個</h3>
<p>{len(models)} 個模型中只有這幾個能處理音訊。發音練習 50 段的鑑別力（AUC，1 代表完全分得開）：</p>
{hbars(pron, fmt=lambda v: f"{v:.2f}")}</div>
<div class="panel finding"><h3>模態覆蓋</h3>
<p>依實測結果分層，每一層都包含上一層的能力。純文字模型無法處理影像與音訊題。</p>
{seg_bar([(TIER_LABEL[t], tiers[t], tier_var(t)) for t in TIER_LABEL], "模態覆蓋")}</div></div></section>""")

    # ------------------------------------------------------------ 五類情境
    cards = []
    for key, name in data["scenarios"].items():
        cands = [(m["scenarios"][key], m["id"]) for m in models if m["scenarios"].get(key) is not None and not m["web"]]
        best = max(cands) if cands else None
        ties = sum(1 for v, _ in cands if best and abs(v - best[0]) < 1e-9)
        n_tasks = sum(1 for t in scored if t["scenario"] == key)
        if not best:
            best_html = ""
        elif ties > 1:
            best_html = f'最高平均 <b>{best[0]:.0%}</b>，共 {ties} 個模型同分'
        else:
            best_html = f'最高平均 <b>{best[0]:.0%}</b>｜<code>{esc(best[1])}</code>'

        cards.append(f'<article><img src="{IMG}/{SCEN_SPOT[key]}.webp" alt="" width="84" height="84" loading="lazy">'
                     f'<h3>{esc(name)}</h3><p>{esc(SCEN_BLURB[key])}（{n_tasks} 個計分任務）</p>'
                     f'<div class="best">{best_html}</div></article>')
    w(f"""<section class="section"><div class="section-head"><h2>五類情境</h2>
<p>同一個模型在不同情境的表現差很多，請依你的用途挑模型。Dashboard 可以直接依情境排序與篩選。</p></div>
<div class="scen">{''.join(cards)}</div></section>""")

    # ------------------------------------------------------------ 早期研究
    w("""<section class="section" id="archive"><div class="section-head"><h2>早期研究</h2>
<p>這個專案一開始只研究 Gemini Decision 1，以下報告保留原貌。</p></div>
<ul class="archive">
<li><a href="report.html"><strong>Gemini Decision 1 的三項音訊研究</strong><span>單音節辨音、42 段音場分類、50 段發音判斷，與 Gemini 4 Argon 對照。</span><em>2026-11-17</em></a></li>
<li><a href="audit-report.html"><strong>注音音檔稽核</strong><span>以 flash-lite 全量檢查 2,934 個注音音檔。</span><em>2026-11-17</em></a></li>
<li><a href="ms-decision-report.html"><strong>Microsoft Decision 1.1 實測</strong><span>音訊支援查證與純文字任務對照。</span><em>2026-11-19</em></a></li>
</ul></section></div>""")

    html_text = page(title="Decision Arena", active="home", generated=data["generated"],
                     description=f"跨廠商 Decision 模型的多模態評測：{len(models)} 個模型在語音、影像、繁中文字、Agent 守門與台灣政經情境的實測。",
                     body="\n".join(parts), extra_css=HOME_CSS)
    out.write_text(html_text, encoding="utf-8")
    return out
