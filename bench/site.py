"""網站共用設計系統：色彩 token、版面、頁首／頁尾、主題切換與圖表元件。

首頁（index.html）、評測報告（bench-report.html）與 Dashboard（bench-dashboard.html）
都由這裡組出外殼，所以三頁的字級、間距、配色與深淺色主題完全一致。

設計重點
--------
- 中性色是冷灰石墨；強調色是深梅紫，刻意避開資料圖表使用的藍、橘、青綠三色。
- 主題預設跟隨系統，可用頁首的按鈕切換，選擇存在 localStorage；
  在 <head> 內聯腳本中先套用，避免畫面閃一下。
- 除了散佈圖之外，圖表都用 HTML／CSS 繪製：字級不會隨螢幕寬度縮小，深淺色自動跟著 token 變。
"""
from __future__ import annotations

import html
from typing import Iterable

esc = lambda s: html.escape(str(s), quote=True)  # noqa: E731

# ---------------------------------------------------------------- 色彩 token
TOKENS = {
    "light": {
        "bg": "#f5f6f8", "surface": "#ffffff", "surface-2": "#eef0f3", "surface-3": "#e4e7ec",
        "ink": "#14171c", "ink-2": "#4a515c", "muted": "#646c79", "border": "#dde1e6", "border-strong": "#c3c9d1",
        "accent": "#7a2e5c", "accent-ink": "#ffffff", "accent-soft": "#f4e6ee", "link": "#7a2e5c",
        "ok": "#1f7a3d", "ok-bg": "#e2f3e7", "warn": "#875700", "warn-bg": "#fcefd5", "bad": "#a3261e", "bad-bg": "#fbe6e4",
        "tier-text": "#2a78d6", "tier-image": "#eb6834", "tier-audio": "#1baf7a",
        "seq-0": "#cde2fb", "seq-1": "#9ec5f4", "seq-2": "#6da7ec", "seq-3": "#3987e5", "seq-4": "#256abf",
        "seq-5": "#184f95", "seq-6": "#0d366b",
        "seqi-0": "#13233a", "seqi-1": "#13233a", "seqi-2": "#13233a", "seqi-3": "#ffffff", "seqi-4": "#ffffff",
        "seqi-5": "#ffffff", "seqi-6": "#ffffff",
        "pos": "#2a78d6", "neg": "#eb6834", "track": "#e9ecf0", "grid": "#e3e6ea",
        "shadow": "0 1px 2px rgba(20,23,28,.04), 0 8px 24px rgba(20,23,28,.06)",
    },
    "dark": {
        "bg": "#0f1115", "surface": "#161920", "surface-2": "#1d2129", "surface-3": "#262b34",
        "ink": "#e8ebf0", "ink-2": "#b2b9c4", "muted": "#8f97a3", "border": "#2a2f38", "border-strong": "#3b414c",
        "accent": "#e7a3c8", "accent-ink": "#1a0f16", "accent-soft": "#2b1a25", "link": "#edb3d3",
        "ok": "#7ed69a", "ok-bg": "#15301f", "warn": "#f0c46a", "warn-bg": "#33280f", "bad": "#ff9a90", "bad-bg": "#3a1a17",
        "tier-text": "#3987e5", "tier-image": "#d95926", "tier-audio": "#199e70",
        "seq-0": "#1b2a3c", "seq-1": "#184f95", "seq-2": "#1c5cab", "seq-3": "#256abf", "seq-4": "#3987e5",
        "seq-5": "#6da7ec", "seq-6": "#b7d3f6",
        "seqi-0": "#e8ebf0", "seqi-1": "#e8ebf0", "seqi-2": "#e8ebf0", "seqi-3": "#ffffff", "seqi-4": "#ffffff",
        "seqi-5": "#0d1b2a", "seqi-6": "#0d1b2a",
        "pos": "#3987e5", "neg": "#d95926", "track": "#232831", "grid": "#272c35",
        "shadow": "0 1px 2px rgba(0,0,0,.3), 0 8px 24px rgba(0,0,0,.25)",
    },
}

TIER_LABEL = {"text": "純文字", "image": "文字＋影像", "audio": "文字＋影像＋音訊"}


def tokens_css() -> str:
    def block(mode: str) -> str:
        return "".join(f"--{k}:{v};" for k, v in TOKENS[mode].items())
    return (f":root{{color-scheme:light;{block('light')}}}\n"
            f"@media (prefers-color-scheme: dark){{:root:not([data-theme=\"light\"]){{color-scheme:dark;{block('dark')}}}}}\n"
            f":root[data-theme=\"dark\"]{{color-scheme:dark;{block('dark')}}}\n")


BASE_CSS = r"""
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-top:84px}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"PingFang TC","Noto Sans TC","Microsoft JhengHei",system-ui,sans-serif;
  font-size:17px;line-height:1.75;font-feature-settings:"palt" 0;-webkit-font-smoothing:antialiased}
img{max-width:100%;display:block}
a{color:var(--link);text-underline-offset:3px;text-decoration-thickness:1px}
a:hover{text-decoration-thickness:2px}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:4px}
code,.mono{font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace;font-size:max(14px,.86em);
  background:var(--surface-2);padding:.08em .38em;border-radius:5px;word-break:break-word}
.wrap{max-width:960px;margin:0 auto;padding:0 32px}
@media (max-width:640px){.wrap{padding:0 16px}}
main{padding-bottom:96px}
h1,h2,h3,h4{line-height:1.3;margin:0;color:var(--ink);letter-spacing:-.005em}
h1{font-size:clamp(2.1rem,1.4rem + 2.6vw,3.1rem);font-weight:750;line-height:1.18;letter-spacing:-.015em}
h2{font-size:1.55rem;font-weight:700}
h3{font-size:1.17rem;font-weight:650}
p{margin:0 0 1em}
.lede{font-size:1.12rem;color:var(--ink-2);max-width:62ch;line-height:1.75}
.small{font-size:15px;color:var(--ink-2)}
.muted{color:var(--muted)}
.num{font-variant-numeric:tabular-nums}

/* 頁首 */
.site-head{position:sticky;top:0;z-index:30;background:color-mix(in srgb,var(--bg) 86%,transparent);
  backdrop-filter:saturate(1.4) blur(12px);-webkit-backdrop-filter:saturate(1.4) blur(12px);border-bottom:1px solid var(--border)}
.site-head .wrap{display:flex;align-items:center;gap:20px;min-height:64px}
.brand{display:flex;align-items:center;gap:10px;color:var(--ink);text-decoration:none;font-weight:700;font-size:17px;white-space:nowrap}
.brand svg{flex:none}
.nav{display:flex;gap:4px;margin-left:auto;overflow-x:auto;scrollbar-width:none}
.nav::-webkit-scrollbar{display:none}
.nav a{color:var(--ink-2);text-decoration:none;font-size:15px;font-weight:550;padding:8px 12px;border-radius:8px;white-space:nowrap}
.nav a:hover{background:var(--surface-2);color:var(--ink)}
.nav a[aria-current="page"]{color:var(--accent);background:var(--accent-soft)}
.theme-btn{flex:none;display:inline-grid;place-items:center;width:40px;height:40px;border-radius:10px;border:1px solid var(--border);
  background:var(--surface);color:var(--ink);cursor:pointer}
.theme-btn:hover{background:var(--surface-2)}
.theme-btn .moon{display:none}
:root[data-theme="dark"] .theme-btn .sun{display:none}
:root[data-theme="dark"] .theme-btn .moon{display:block}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]) .theme-btn .sun{display:none}
  :root:not([data-theme="light"]) .theme-btn .moon{display:block}}
@media (max-width:720px){
  .site-head .wrap{flex-wrap:wrap;gap:0 12px;padding-top:8px}
  .brand{order:1}.theme-btn{order:2;margin-left:auto}
  .nav{order:3;width:100%;margin:4px -8px 6px;padding:0 0 2px}
}

/* 區塊 */
.page-hero{padding:56px 0 8px}
@media (max-width:640px){.page-hero{padding:36px 0 0}}
.page-hero h1{margin-bottom:16px}
.meta{font-size:14px;color:var(--muted);margin-top:16px}
.section{margin-top:72px}
@media (max-width:640px){.section{margin-top:56px}}
.section-head{margin-bottom:20px}
.section-head h2{margin-bottom:8px}
.section-head p{color:var(--ink-2);max-width:66ch;margin:0}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:24px 26px;box-shadow:var(--shadow)}
@media (max-width:640px){.panel{padding:18px 16px;border-radius:14px}}
.panel + .panel{margin-top:16px}
.panel-title{font-size:1.05rem;font-weight:650;margin:0 0 4px}
.panel-sub{font-size:15px;color:var(--ink-2);margin:0 0 16px;max-width:64ch}

/* 數字列 */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border:1px solid var(--border);
  border-radius:14px;overflow:hidden;margin:28px 0 0}
@media (max-width:720px){.stats{grid-template-columns:repeat(2,1fr)}}
.stats div{background:var(--surface);padding:16px 18px}
.stats dt{font-size:14px;color:var(--ink-2)}
.stats dd{margin:2px 0 0;font-size:1.7rem;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.3}
.stats dd small{font-size:15px;font-weight:500;color:var(--ink-2);margin-left:2px}

/* 標籤與狀態 */
.pill{display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:600;padding:2px 10px;border-radius:999px;white-space:nowrap;line-height:1.6}
.pill.ok{background:var(--ok-bg);color:var(--ok)}
.pill.bad{background:var(--bad-bg);color:var(--bad)}
.pill.warn{background:var(--warn-bg);color:var(--warn)}
.pill.muted{background:var(--surface-2);color:var(--muted)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;flex:none}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:14px;color:var(--ink-2);align-items:center}
.legend span{display:inline-flex;align-items:center;gap:7px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px}

/* 表格 */
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--border);border-radius:12px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:15px;line-height:1.55}
th,td{padding:12px 16px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border)}
thead th{background:var(--surface-2);font-weight:600;font-size:14px;color:var(--ink-2);white-space:nowrap;position:sticky;top:0}
tbody tr:last-child>*{border-bottom:0}
tbody tr:hover>td{background:color-mix(in srgb,var(--surface-2) 55%,transparent)}
td.note{color:var(--ink-2);font-size:14px;min-width:220px}
td small,th small{display:block;font-size:14px;color:var(--muted);font-weight:400}

details{margin-top:12px;border-top:1px solid var(--border);padding-top:10px}
summary{cursor:pointer;color:var(--link);font-weight:600;font-size:15px;list-style:none;display:inline-flex;align-items:center;gap:8px}
summary::-webkit-details-marker{display:none}
summary::before{content:"";width:8px;height:8px;border-right:2px solid currentColor;border-bottom:2px solid currentColor;
  transform:rotate(-45deg);transition:transform .15s}
details[open] summary::before{transform:rotate(45deg)}
details[open]>*:not(summary){margin-top:12px}

/* 本頁目錄 */
.toc{display:flex;flex-wrap:wrap;gap:8px;margin-top:28px}
.toc a{font-size:14px;font-weight:600;color:var(--ink-2);text-decoration:none;padding:6px 12px;border:1px solid var(--border);
  border-radius:999px;background:var(--surface)}
.toc a:hover{color:var(--accent);border-color:var(--accent)}

/* 頁尾 */
.site-foot{border-top:1px solid var(--border);margin-top:24px;padding:28px 0 40px;font-size:14px;color:var(--muted)}
.site-foot .wrap{display:flex;flex-wrap:wrap;gap:8px 24px;justify-content:space-between}
.site-foot a{color:var(--ink-2)}

@media (prefers-reduced-motion: reduce){*{transition:none!important;animation:none!important}}
"""

CHART_CSS = r"""
/* 分段長條 */
.seg{display:flex;gap:2px;height:40px;border-radius:8px;overflow:hidden}
.seg>div{display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:15px;min-width:0}
.seg-legend{display:flex;flex-wrap:wrap;gap:6px 22px;margin-top:10px;font-size:15px;color:var(--ink-2)}
.seg-legend b{color:var(--ink);font-variant-numeric:tabular-nums;margin-left:4px}

/* 橫條圖 */
.bars{display:grid;grid-template-columns:minmax(120px,max-content) 1fr;gap:6px 14px;align-items:center}
.bars .bl{font-size:14px;color:var(--ink);text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px}
.bars .bl code{background:none;padding:0;font-size:14px}
.bars .bt{position:relative;height:22px;background:var(--track);border-radius:5px}
.bars .bf{position:absolute;inset:0 auto 0 0;border-radius:5px;min-width:3px}
.bars .bv{position:absolute;top:50%;transform:translateY(-50%);font-size:14px;font-weight:600;font-variant-numeric:tabular-nums;color:var(--ink);white-space:nowrap}
.bars .na .bt{background:repeating-linear-gradient(135deg,var(--track) 0 6px,var(--surface-2) 6px 9px)}
@media (max-width:640px){.bars{grid-template-columns:minmax(96px,40%) 1fr}.bars .bl{max-width:none}}

/* 範圍圖（每個任務：最低—最高，點為中位數） */
.range{display:grid;grid-template-columns:minmax(150px,max-content) 1fr 7.5em;gap:10px 16px;align-items:center}
.range .rl{font-size:15px;line-height:1.35}
.range .rl small{display:block;font-size:14px;color:var(--muted)}
.range .rt{position:relative;height:28px}
.range .rt::before{content:"";position:absolute;left:0;right:0;top:50%;height:1px;background:var(--grid)}
.range .rspan{position:absolute;top:50%;height:8px;transform:translateY(-50%);border-radius:4px;background:var(--accent);opacity:.35}
.range .rmin,.range .rmax,.range .rmed{position:absolute;top:50%;transform:translate(-50%,-50%);border-radius:50%}
.range .rmin,.range .rmax{width:10px;height:10px;background:var(--surface);border:2px solid var(--accent)}
.range .rmed{width:12px;height:12px;background:var(--accent);box-shadow:0 0 0 2px var(--surface)}
.range .rv{font-size:14px;color:var(--ink-2);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.range .axis{grid-column:2;display:flex;justify-content:space-between;font-size:14px;color:var(--muted)}
@media (max-width:640px){.range{grid-template-columns:1fr 6.5em}.range .rl{grid-column:1 / -1;margin-bottom:-6px}.range .axis{grid-column:1}}

/* 分組橫條 */
.groups{display:grid;gap:18px}
.group h4{font-size:15px;font-weight:650;margin:0 0 8px}

/* 發散長條 */
.div{display:grid;grid-template-columns:minmax(120px,max-content) 1fr 1fr 5.5em;gap:6px 0;align-items:center}
.div .dl{font-size:14px;text-align:right;padding-right:14px;white-space:nowrap}
.div .dl code{background:none;padding:0}
.div .dn,.div .dp{position:relative;height:20px}
.div .dn{border-right:1px solid var(--border-strong)}
.div .dn i,.div .dp i{position:absolute;top:2px;bottom:2px;border-radius:4px}
.div .dn i{right:0;background:var(--neg)}
.div .dp i{left:0;background:var(--pos)}
.div .dv{font-size:14px;font-variant-numeric:tabular-nums;text-align:right;color:var(--ink-2)}
.div .dh{font-size:14px;color:var(--muted);padding-bottom:4px}
@media (max-width:640px){.div{grid-template-columns:minmax(92px,36%) 1fr 1fr 4.2em}}

/* 量尺（每個模型一條刻度） */
.strip{position:relative;height:150px;margin:8px 4px 0}
.strip .base{position:absolute;left:0;right:0;bottom:34px;height:2px;background:var(--border-strong)}
.strip .tick{position:absolute;bottom:34px;width:3px;margin-left:-1.5px;border-radius:2px 2px 0 0}
.strip .tick:hover{filter:brightness(1.2)}
.strip .lab{position:absolute;font-size:14px;color:var(--ink);white-space:nowrap;transform:translateX(-50%);font-weight:600}
.strip .lab::after{content:"";position:absolute;left:50%;top:100%;width:1px;height:10px;background:var(--border-strong)}
.strip .ax{position:absolute;bottom:6px;font-size:14px;color:var(--muted);transform:translateX(-50%);font-variant-numeric:tabular-nums}

/* 散佈圖（SVG；寬度不足時在框內水平捲動，文字不縮小） */
.svg-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.svg-wrap svg{display:block;min-width:600px;width:100%;height:auto}
.svg-wrap text{font-family:inherit;font-size:14px;fill:var(--ink-2)}
.svg-wrap .lbl{fill:var(--ink);font-weight:600}
.svg-wrap .gl{stroke:var(--grid)}
.svg-wrap .bl{stroke:var(--border-strong)}
.svg-wrap .pt{stroke:var(--surface);stroke-width:2}
"""

HEAD_SCRIPT = ("<script>(()=>{try{const t=localStorage.getItem('da-theme');"
               "if(t==='light'||t==='dark')document.documentElement.dataset.theme=t;}catch(e){}})();</script>")

TOGGLE_SCRIPT = r"""<script>(()=>{
  const root=document.documentElement, btn=document.getElementById('theme-btn');
  if(!btn) return;
  const cur=()=>root.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
  const label=()=>btn.setAttribute('aria-label', cur()==='dark'?'切換為淺色主題':'切換為深色主題');
  label();
  btn.addEventListener('click',()=>{const n=cur()==='dark'?'light':'dark';root.dataset.theme=n;
    try{localStorage.setItem('da-theme',n)}catch(e){} label(); dispatchEvent(new CustomEvent('themechange',{detail:n}));});
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{label();dispatchEvent(new CustomEvent('themechange'));});
})();</script>"""

BRAND_SVG = ('<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">'
             '<rect x="2" y="13" width="4" height="11" rx="2" fill="var(--tier-text)"/>'
             '<rect x="8" y="7" width="4" height="17" rx="2" fill="var(--accent)"/>'
             '<rect x="14" y="2" width="4" height="22" rx="2" fill="var(--ink)"/>'
             '<rect x="20" y="10" width="4" height="14" rx="2" fill="var(--tier-audio)"/></svg>')

SUN = ('<svg class="sun" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
       'stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6'
       'M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6"/></svg>')
MOON = ('<svg class="moon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linejoin="round" aria-hidden="true"><path d="M20.5 14.6A8.5 8.5 0 0 1 9.4 3.5a8.5 8.5 0 1 0 11.1 11.1z"/></svg>')

NAV = [("index.html", "首頁", "home"), ("bench-dashboard.html", "Dashboard", "dashboard"),
       ("bench-report.html", "評測報告", "report"), ("index.html#archive", "早期研究", "archive")]


def header(active: str) -> str:
    links = "".join(f'<a href="{href}"{" aria-current=\"page\"" if key == active else ""}>{esc(label)}</a>'
                    for href, label, key in NAV)
    return (f'<header class="site-head"><div class="wrap"><a class="brand" href="index.html">{BRAND_SVG}'
            f'<span>Decision Arena</span></a><nav class="nav" aria-label="主要頁面">{links}</nav>'
            f'<button class="theme-btn" id="theme-btn" type="button" aria-label="切換主題">{SUN}{MOON}</button>'
            f'</div></header>')


def footer(generated: str) -> str:
    return (f'<footer class="site-foot"><div class="wrap">'
            f'<span>© 2026 <a href="https://www.facebook.com/will.fans/" rel="noopener">Will 保哥</a>｜資料產生於 {esc(generated)}</span>'
            f'<span>雲端模型會持續更新，數字只代表測試當天的行為。</span>'
            f'</div></footer>')


def page(*, title: str, description: str, active: str, body: str, generated: str,
         extra_css: str = "", extra_head: str = "", scripts: str = "") -> str:
    return f"""<!doctype html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="assets/site/favicon.ico" sizes="32x32">
<link rel="icon" href="assets/site/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="assets/site/apple-touch-icon.png">
<meta name="theme-color" content="{TOKENS["light"]["bg"]}" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="{TOKENS["dark"]["bg"]}" media="(prefers-color-scheme: dark)">
{HEAD_SCRIPT}
<style>
{tokens_css()}{BASE_CSS}{CHART_CSS}{extra_css}
</style>
{extra_head}
</head>
<body>
{header(active)}
<main>
{body}
</main>
{footer(generated)}
{TOGGLE_SCRIPT}
{scripts}
</body>
</html>
"""


# ---------------------------------------------------------------- 圖表元件
def seq_style(v: float) -> str:
    """0–1 數值 → 連續色階背景與對應的文字色（深淺色各自正確）。"""
    k = max(0, min(6, round(v * 6)))
    return f"background:var(--seq-{k});color:var(--seqi-{k})"


def tier_var(tier: str) -> str:
    return f"var(--tier-{tier})"


def legend_tiers() -> str:
    return '<div class="legend">' + "".join(
        f'<span><i style="background:{tier_var(t)}"></i>{esc(lab)}</span>' for t, lab in TIER_LABEL.items()) + "</div>"


def seg_bar(counts: list[tuple[str, int, str]], aria: str) -> str:
    """counts：[(標籤, 數量, CSS 顏色)]。"""
    total = sum(n for _, n, _ in counts) or 1
    segs = "".join(f'<div style="flex:{n};background:{c}" title="{esc(lab)}：{n}">{n if n / total > .07 else ""}</div>'
                   for lab, n, c in counts if n)
    leg = "".join(f'<span><i class="dot" style="background:{c};border-radius:3px;margin-right:6px"></i>{esc(lab)}<b>{n}</b></span>'
                  for lab, n, c in counts)
    return f'<div class="seg" role="img" aria-label="{esc(aria)}">{segs}</div><div class="seg-legend">{leg}</div>'


def hbars(rows: Iterable[tuple[str, float | None, str, str]], *, vmax: float = 1.0, fmt=lambda v: f"{v * 100:.0f}%",
          label_code: bool = True, na_text: str = "不支援") -> str:
    """rows：[(標籤, 數值或 None, CSS 顏色, title)]。值放在長條右端；長條太長時改放在條內。"""
    out = ['<div class="bars">']
    for label, v, color, title in rows:
        lab = f"<code>{esc(label)}</code>" if label_code else esc(label)
        if v is None:
            out.append(f'<div class="bl">{lab}</div><div class="na" title="{esc(title)}"><div class="bt">'
                       f'<span class="bv" style="left:8px;color:var(--muted);font-weight:400">{esc(na_text)}</span></div></div>')
            continue
        w = max(0.0, min(1.0, v / vmax)) * 100
        inside = w > 82
        pos = (f"right:calc({100 - w:.2f}% + 8px);color:#fff" if inside else f"left:calc({w:.2f}% + 8px)")
        out.append(f'<div class="bl">{lab}</div><div title="{esc(title)}"><div class="bt">'
                   f'<div class="bf" style="width:{w:.2f}%;background:{color}"></div>'
                   f'<span class="bv" style="{pos}">{esc(fmt(v))}</span></div></div>')
    out.append("</div>")
    return "".join(out)


def range_rows(rows: Iterable[tuple[str, str, list[float]]]) -> str:
    """rows：[(任務名稱, 副標, [各模型正確率])]。畫最低—最高與中位數。"""
    import statistics
    out = ['<div class="range">']
    for label, sub, vals in rows:
        if not vals:
            continue
        lo, hi, med = min(vals), max(vals), statistics.median(vals)
        out.append(f'<div class="rl">{esc(label)}<small>{esc(sub)}</small></div>'
                   f'<div class="rt" role="img" aria-label="{esc(label)}：最低 {lo:.0%}、中位數 {med:.0%}、最高 {hi:.0%}" '
                   f'title="最低 {lo:.0%}｜中位數 {med:.0%}｜最高 {hi:.0%}">'
                   f'<span class="rspan" style="left:{lo * 100:.1f}%;width:{max(0.6, (hi - lo) * 100):.1f}%"></span>'
                   f'<span class="rmin" style="left:{lo * 100:.1f}%"></span><span class="rmax" style="left:{hi * 100:.1f}%"></span>'
                   f'<span class="rmed" style="left:{med * 100:.1f}%"></span></div>'
                   f'<div class="rv">{lo:.0%}–{hi:.0%}</div>')
    out.append('<div class="axis"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div></div>')
    return "".join(out)


def diverging(rows: Iterable[tuple[str, float, str]], *, vmax: float, left: str, right: str) -> str:
    """rows：[(標籤, 有號數值, title)]；負值往左（--neg），正值往右（--pos）。"""
    out = [f'<div class="div"><div></div><div class="dh" style="text-align:right;padding-right:8px">← {esc(left)}</div>'
           f'<div class="dh" style="padding-left:8px">{esc(right)} →</div><div></div>']
    for label, v, title in rows:
        w = min(1.0, abs(v) / vmax) * 100
        neg = f'<i style="width:{w:.1f}%"></i>' if v < 0 else ""
        pos = f'<i style="width:{w:.1f}%"></i>' if v > 0 else ""
        out.append(f'<div class="dl"><code>{esc(label)}</code></div><div class="dn" title="{esc(title)}">{neg}</div>'
                   f'<div class="dp" title="{esc(title)}">{pos}</div><div class="dv">{v:+.3f}</div>')
    out.append("</div>")
    return "".join(out)


def strip(points: list[tuple[str, float, str]], labels: set[str], *, aria: str) -> str:
    """points：[(模型, 0–1 分數, tier)]；每個模型一條刻度，labels 中的模型加上名稱。"""
    import math
    out = [f'<div class="strip" role="img" aria-label="{esc(aria)}"><div class="base"></div>']
    for v in (0, .25, .5, .75, 1):
        out.append(f'<span class="ax" style="left:{v * 100:.0f}%">{v * 100:.0f}%</span>')
    # 同分的刻度往上疊，看得出密度
    seen: dict[int, int] = {}
    placed: list[tuple[float, int]] = []
    for mid, v, tier in sorted(points, key=lambda p: p[1]):
        key = round(v * 100)
        k = seen.get(key, 0)
        seen[key] = k + 1
        h = 46 + k * 10
        out.append(f'<span class="tick" style="left:{v * 100:.2f}%;height:{h}px;background:{tier_var(tier)}" '
                   f'title="{esc(mid)}：{v:.0%}"></span>')
        if mid in labels:
            row = 0
            while any(abs(px - v) < .13 and r == row for px, r in placed):
                row += 1
            placed.append((v, row))
            out.append(f'<span class="lab" style="left:{min(94, max(6, v * 100)):.2f}%;bottom:{34 + 64 + row * 26}px">{esc(mid)}</span>')
    out.append("</div>")
    return "".join(out)


def scatter_svg(points: list[dict], *, xlabel: str, ylabel: str, xfmt, yfmt, labels: set[str],
                xdom: tuple[float, float], ydom: tuple[float, float], xticks: list[float], yticks: list[float],
                aria: str, width: int = 880, height: int = 420) -> str:
    """points：[{id, x, y, tier}]。shape 依層級區分（方形／圓形／菱形），顏色不是唯一的編碼。"""
    P = {"l": 64, "r": 24, "t": 16, "b": 56}
    X = lambda v: P["l"] + (v - xdom[0]) / (xdom[1] - xdom[0]) * (width - P["l"] - P["r"])  # noqa: E731
    Y = lambda v: height - P["b"] - (v - ydom[0]) / (ydom[1] - ydom[0]) * (height - P["t"] - P["b"])  # noqa: E731

    def shape(tier, x, y, r=6):
        if tier == "text":
            return f'<rect class="pt" x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" rx="1.5" fill="{tier_var(tier)}"'
        if tier == "audio":
            d = r * 1.35
            return f'<path class="pt" d="M{x:.1f},{y - d:.1f}L{x + d:.1f},{y:.1f}L{x:.1f},{y + d:.1f}L{x - d:.1f},{y:.1f}z" fill="{tier_var(tier)}"'
        return f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{tier_var(tier)}"'

    s = [f'<div class="svg-wrap"><svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(aria)}">']
    for v in yticks:
        s.append(f'<line class="gl" x1="{P["l"]}" x2="{width - P["r"]}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 f'<text x="{P["l"] - 10}" y="{Y(v) + 5:.1f}" text-anchor="end">{esc(yfmt(v))}</text>')
    for v in xticks:
        s.append(f'<text x="{X(v):.1f}" y="{height - P["b"] + 24}" text-anchor="middle">{esc(xfmt(v))}</text>')
    s.append(f'<line class="bl" x1="{P["l"]}" x2="{width - P["r"]}" y1="{height - P["b"]}" y2="{height - P["b"]}"/>')
    s.append(f'<text x="{(P["l"] + width - P["r"]) / 2:.0f}" y="{height - 10}" text-anchor="middle" style="font-weight:600">{esc(xlabel)}</text>')
    cy = (P["t"] + height - P["b"]) / 2
    s.append(f'<text x="16" y="{cy:.0f}" text-anchor="middle" transform="rotate(-90 16 {cy:.0f})" style="font-weight:600">{esc(ylabel)}</text>')
    placed: list[tuple[float, float, float, float]] = []
    dots = [(X(p["x"]), Y(p["y"])) for p in points]
    for p in points:
        x, y = X(p["x"]), Y(p["y"])
        s.append(shape(p["tier"], x, y) + f'><title>{esc(p["id"])}：{esc(xlabel)} {esc(xfmt(p["x"]))}，{esc(ylabel)} {esc(yfmt(p["y"]))}</title>'
                 + ("</rect>" if p["tier"] == "text" else "</path>" if p["tier"] == "audio" else "</circle>"))
    for p in points:
        if p["id"] not in labels:
            continue
        x, y = X(p["x"]), Y(p["y"])
        w, h = len(p["id"]) * 8 + 4, 16
        for lx, ly, anchor in ((x + 11, y + 5, "start"), (x - 11, y + 5, "end"), (x, y - 13, "middle"), (x, y + 24, "middle")):
            x0 = lx if anchor == "start" else lx - w if anchor == "end" else lx - w / 2
            box = (x0, ly - h + 3, x0 + w, ly + 3)
            if box[0] < P["l"] or box[2] > width - P["r"] or box[1] < P["t"]:
                continue
            if any(box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1] for b in placed):
                continue
            if any((dx, dy) != (x, y) and box[0] - 5 < dx < box[2] + 5 and box[1] - 5 < dy < box[3] + 5 for dx, dy in dots):
                continue
            placed.append(box)
            s.append(f'<text class="lbl" x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}">{esc(p["id"])}</text>')
            break
    s.append("</svg></div>")
    return "".join(s)


def scatter_legend() -> str:
    shapes = {"text": '<rect x="1" y="1" width="12" height="12" rx="1.5" fill="var(--tier-text)"/>',
              "image": '<circle cx="7" cy="7" r="6" fill="var(--tier-image)"/>',
              "audio": '<path d="M7,0L14,7L7,14L0,7z" fill="var(--tier-audio)"/>'}
    return '<div class="legend">' + "".join(
        f'<span><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">{shapes[t]}</svg>{esc(lab)}</span>'
        for t, lab in TIER_LABEL.items()) + "</div>"
