"""早期研究報告的共用外殼：套上網站的頁首、頁尾、色彩 token 與深淺色切換。

三份早期報告（report.html、audit-report.html、ms-decision-report.html）各有自己的
產生器（scripts/build_*.py）與元件樣式；這裡只負責：

- 把舊樣式用到的變數名稱（--acc、--rust、--card…）對應到網站的 token，
  所以元件顏色會跟著主題切換，不必逐一改寫模板；
- 提供三份報告共用的區塊樣式（封面、數字卡、卡片、提示框、本頁目錄、浮動提示）；
- 用 site.page() 組出完整頁面，導覽列標示「早期研究」。
"""
from __future__ import annotations

from .site import page

MONO = '"SF Mono",ui-monospace,Menlo,Consolas,monospace'

LEGACY_CSS = r"""
/* 舊變數 → 網站 token。Decisions／Argon 對照用資料色（藍／橘），對錯用狀態色。 */
:root{--acc:var(--pos);--acc-2:var(--neg);--good:var(--ok);--card:var(--surface);--card2:var(--surface);
  --line:var(--border);--line2:var(--border-strong);--ink-3:var(--muted);--ink2:var(--ink-2);--ink3:var(--muted);
  --rust:var(--bad);--moss:var(--ok);--amber:var(--warn);--rule:var(--border);--rule2:var(--border-strong);
  --paper:var(--bg);--rust-bg:var(--bad-bg);--moss-bg:var(--ok-bg);--serif:inherit;--mono:__MONO__}

/* 封面 */
.lg .page-hero h1 em{display:block;font-style:normal;font-size:.6em;font-weight:650;color:var(--ink-2);margin-top:10px;letter-spacing:0}
.lg .page-hero .meta{margin:0 0 14px}
.lg .page-hero .lede b{color:var(--ink);font-weight:650}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1px;background:var(--border);
  border:1px solid var(--border);border-radius:14px;overflow:hidden;margin:28px 0 0}
.kpi{background:var(--surface);padding:16px 18px}
.kpi .v{font-size:1.7rem;font-weight:700;line-height:1.3;font-variant-numeric:tabular-nums;color:var(--ink)}
.kpi .v small,.kpi .v .cur{font-size:15px;font-weight:500;color:var(--ink-2);margin:0 2px}
.kpi .l,.kpi .k{font-size:15px;color:var(--ink);font-weight:600;margin-top:2px}
.kpi .s{font-size:14px;color:var(--muted);margin-top:2px;line-height:1.5}
.kpi.bad .v{color:var(--bad)}

/* 區塊 */
.lg section:not(.page-hero){margin-top:72px}
@media (max-width:640px){.lg section:not(.page-hero){margin-top:56px}}
.lg .sec-head,.lg section>.wrap>h2{margin-bottom:20px}
.lg h2{margin-bottom:8px}
.lg .sec-head p,.lg .lead{color:var(--ink-2);max-width:66ch;margin:0 0 20px;font-size:17px}
.lg h3{font-size:1.05rem;font-weight:650;margin:0 0 4px;color:var(--ink);letter-spacing:0;text-transform:none}
.lg .hint{font-size:15px;color:var(--ink-2);margin:0 0 16px;max-width:64ch}
.card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:24px 26px;box-shadow:var(--shadow);margin-top:16px}
.lg .sec-head + .card,.lg .lead + .card{margin-top:0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;align-items:start}
.grid2>.card{margin-top:0}
@media (max-width:820px){.grid2{grid-template-columns:1fr}}
@media (max-width:640px){.card{padding:18px 16px;border-radius:14px}}
.callout{border:1px solid var(--border);border-left:4px solid var(--accent);border-radius:12px;background:var(--surface);
  padding:16px 20px;margin:16px 0 0;font-size:16px;color:var(--ink-2)}
.callout b{color:var(--ink)}
.callout.warn{border-left-color:var(--warn);background:var(--warn-bg)}
.callout.bad{border-left-color:var(--bad);background:var(--bad-bg)}
.callout.moss{border-left-color:var(--ok);background:var(--ok-bg)}
.lg .src{margin-top:56px;font-size:15px;color:var(--ink-2)}
.lg table{font-size:15px}
.lg th{font-size:14px;font-weight:600;color:var(--ink-2);text-transform:none;letter-spacing:0}
.bad-t{color:var(--bad);font-weight:650}
.good-t{color:var(--ok);font-weight:650}
.lg .mono:not(td){background:none;padding:0}
.lg pre .mono{font-size:14px}
.lg td.mono{font-size:14px;padding:12px 16px;background:none;border-radius:0;white-space:nowrap;word-break:normal}
.tbl-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}

/* 浮動提示 */
#tip{position:fixed;z-index:90;pointer-events:none;opacity:0;transition:opacity .15s;background:var(--surface);
  border:1px solid var(--border-strong);border-radius:10px;padding:10px 12px;font-size:14px;box-shadow:var(--shadow);
  max-width:300px;line-height:1.55;color:var(--ink)}
#tip b{color:var(--ink)}
""".replace("__MONO__", MONO)


def render(*, title: str, description: str, generated: str, body: str, css: str = "", scripts: str = "") -> str:
    """body 是報告主體（封面＋各區塊）；css 是該報告自己的元件樣式。"""
    return page(title=title, description=description, active="archive", generated=generated,
                body=f'<div class="lg">\n{body}\n</div>', extra_css=LEGACY_CSS + css, scripts=scripts)
