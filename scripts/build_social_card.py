#!/usr/bin/env python3
"""產生社群分享卡 assets/site/og-card.png（1200×630，OpenGraph／Twitter 共用）。

卡片用 HTML 排版、headless Chrome 截圖，文字是真的字型渲染，不靠圖像模型畫字；
模型數與任務數從 results/ 讀出（與網站同源），背景沿用首頁主視覺 hero-dark.webp。

用法：
  python3 scripts/build_social_card.py
需要：本機安裝 Google Chrome（或以 CHROME 環境變數指定路徑）、ImageMagick（magick）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.dashboard import build_data  # noqa: E402

OUT = ROOT / "assets" / "site" / "og-card.png"
W, H = 1200, 630
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def card_html(models: int, tasks: int) -> str:
    hero = (ROOT / "assets" / "site" / "hero-dark.webp").as_uri()
    return f"""<!doctype html><html lang="zh-Hant-TW"><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:#0f1115}}
body{{position:relative;font-family:"PingFang TC","Noto Sans TC",sans-serif;color:#e8ebf0}}
.art{{position:absolute;right:-150px;top:0;height:100%;width:820px;background:url('{hero}') right center/cover no-repeat;
  -webkit-mask-image:linear-gradient(90deg,transparent 0,transparent 8%,#000 45%)}}
.copy{{position:absolute;left:72px;top:0;bottom:0;width:640px;display:flex;flex-direction:column;justify-content:center}}
.brand{{display:flex;align-items:center;gap:16px;font-size:34px;font-weight:700;letter-spacing:-.01em}}
h1{{font-size:62px;line-height:1.2;font-weight:750;margin:34px 0 22px;letter-spacing:-.01em}}
p{{font-size:28px;line-height:1.5;color:#b2b9c4}}
.foot{{position:absolute;left:72px;bottom:46px;font-size:24px;color:#8f97a3}}
</style></head><body><div class="art"></div><div class="copy">
<div class="brand"><svg width="46" height="46" viewBox="0 0 26 26"><rect x="2" y="13" width="4" height="11" rx="2" fill="#3987e5"/>
<rect x="8" y="7" width="4" height="17" rx="2" fill="#e7a3c8"/><rect x="14" y="2" width="4" height="22" rx="2" fill="#e8ebf0"/>
<rect x="20" y="10" width="4" height="14" rx="2" fill="#1baf7a"/></svg>Decision Arena</div>
<h1>{models} 個決策模型，<br>同一套考題。</h1>
<p>語音、影像、繁中文字、Agent 守門與台灣政經，{tasks} 個任務的多模態實測。</p>
</div><div class="foot">decision-arena.gh.miniasp.com</div></body></html>"""


def main() -> None:
    if not Path(CHROME).exists():
        sys.exit(f"找不到 Chrome：{CHROME}（可用 CHROME 環境變數指定）")
    data = build_data()
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "card.html"
        shot = Path(td) / "card.png"
        src.write_text(card_html(len(data["models"]), len(data["tasks"])), encoding="utf-8")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--window-size={W},{H}", "--virtual-time-budget=3000", f"--screenshot={shot}", src.as_uri()],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # 截圖可能帶 alpha；轉成不透明 8-bit PNG 並裁成精確尺寸
        magick = shutil.which("magick") or sys.exit("找不到 ImageMagick（magick）")
        subprocess.run([magick, str(shot), "-crop", f"{W}x{H}+0+0", "+repage", "-background", "#0f1115", "-alpha", "remove",
                        "-depth", "8", "-strip", "-define", "png:compression-level=9", str(OUT)], check=True)
    print(f"✅ {OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
