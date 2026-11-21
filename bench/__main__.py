"""Decision 模型評測 CLI。

    python3 -m bench models                    # 列出已登記的模型與金鑰狀態
    python3 -m bench tasks                     # 列出任務
    python3 -m bench build                     # 產生影像素材與音訊任務檔
    python3 -m bench probe --modalities image,audio
    python3 -m bench run --models gemini-decision-1 --tasks zh_text --limit 8 --budget 5
    python3 -m bench report                    # 由 results/ 產生 bench-report.html
    python3 -m bench dashboard                 # 由 results/ 產生互動式 bench-dashboard.html
"""
from __future__ import annotations

import argparse
import sys

from . import providers
from .schema import SCENARIOS, load_tasks


def _split(s: str | None) -> list[str] | None:
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def cmd_models(_args) -> None:
    for p in providers.get():
        info = p.info
        key = "✓" if p.available else "缺 " + ",".join(p.missing_env())
        print(f"{info.id:28s} {info.vendor:12s} {key:28s} 文件模態={','.join(info.documented_modalities)}")


def cmd_tasks(args) -> None:
    for t in load_tasks(_split(args.tasks)):
        mods = ",".join(sorted(t.modalities))
        print(f"{t.id:26s} {SCENARIOS[t.scenario]:14s} {t.question.type:6s} n={len(t.items):3d}  {mods:12s} {t.title}")


def cmd_build(_args) -> None:
    from .build_assets import build
    build()


def cmd_probe(args) -> None:
    from .probe import probe
    probe(providers.get(_split(args.models)), _split(args.modalities) or ["image", "audio"])


def cmd_run(args) -> None:
    from .runner import run
    tasks = load_tasks(_split(args.tasks))
    provs = providers.get(_split(args.models), include_mocks=True)
    out = run(provs, tasks, limit=args.limit, budget_usd=args.budget, workers=args.workers,
              model_workers=args.model_workers,
              force=args.force, use_cache=not args.no_cache, run_id=args.run_id or "")
    print(f"結果：{out}")


def cmd_report(args) -> None:
    from .report import build_report
    path = build_report(_split(args.runs))
    print(f"報告：{path}")


def cmd_dashboard(_args) -> None:
    from .dashboard import build_dashboard
    print(f"Dashboard：{build_dashboard()}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python3 -m bench", description="Decision 模型評測")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("models").set_defaults(fn=cmd_models)
    p = sub.add_parser("tasks")
    p.add_argument("--tasks")
    p.set_defaults(fn=cmd_tasks)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    p = sub.add_parser("probe")
    p.add_argument("--models")
    p.add_argument("--modalities", default="image,audio")
    p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("run")
    p.add_argument("--models", help="逗號分隔；預設全部已登記模型")
    p.add_argument("--tasks", help="逗號分隔的 glob（相對 tasks/），例如 zh_text,image/image-color")
    p.add_argument("--limit", type=int, default=0, help="每個任務最多跑幾題（0 = 全部）")
    p.add_argument("--budget", type=float, default=5.0, help="本次執行的美元上限")
    p.add_argument("--workers", type=int, default=4, help="每個模型同時送出的請求數")
    p.add_argument("--model-workers", type=int, default=6, help="同時跑幾個模型")
    p.add_argument("--force", action="store_true", help="忽略模態探針結果，硬跑")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--run-id")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("report")
    p.add_argument("--runs", help="逗號分隔的 run id；預設合併全部")
    p.set_defaults(fn=cmd_report)
    sub.add_parser("dashboard", help="由 results/ 產生 bench-dashboard.html").set_defaults(fn=cmd_dashboard)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
