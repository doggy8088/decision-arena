"""任務定義（task）的資料結構與載入。

一個任務 = 一題「標準化題目」＋ 一批題項（item）。所有 provider 都吃同一份任務檔，
各自的 adapter 再把標準化題型翻成自家 API 的欄位名稱。

標準化題型
----------
- ``binary``：是非題，答案標籤固定為 ``yes`` / ``no``。
- ``choice``：單選題，``options`` 是 ``{label: 說明}``。

輸入片段（item.inputs 的每個元素）
----------------------------------
- ``{"type": "text", "text": "..."}``
- ``{"type": "image", "path": "assets/images/x.png"}``
- ``{"type": "audio", "path": "data/scenes/speech/sp_jobs.mp3"}``

題目文字可以用 ``{var}`` 引用 item.vars，例如發音題把目標句塞進題目。
"""
from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = ROOT / "tasks"

QUESTION_TYPES = ("binary", "choice")
INPUT_TYPES = ("text", "image", "audio")
SCENARIOS = {
    "audio": "語音與音訊",
    "image": "影像判斷",
    "zh_text": "中文文字決策",
    "agent": "Agent 守門／路由",
    "taiwan": "台灣政經",
}
METRICS = ("classification", "swap_symmetry")

MIME = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".png": "image/png",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class TaskError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    type: str
    instructions: str
    options: dict[str, str] = field(default_factory=dict)

    @property
    def labels(self) -> list[str]:
        return ["yes", "no"] if self.type == "binary" else list(self.options)

    def render(self, vars: dict[str, Any]) -> "Question":
        if not vars:
            return self
        return Question(self.type, self.instructions.format(**vars),
                        {k: v.format(**vars) for k, v in self.options.items()})

    def to_dict(self) -> dict:
        d: dict = {"type": self.type, "instructions": self.instructions}
        if self.type == "choice":
            d["options"] = dict(self.options)
        return d


@dataclass(frozen=True)
class Part:
    type: str
    text: str = ""
    path: str = ""

    @property
    def mime(self) -> str:
        suffix = Path(self.path).suffix.lower()
        return MIME.get(suffix) or mimetypes.guess_type(self.path)[0] or "application/octet-stream"

    def read_bytes(self) -> bytes:
        return (ROOT / self.path).read_bytes()


@dataclass(frozen=True)
class Item:
    id: str
    inputs: tuple[Part, ...]
    gold: str | None = None
    group: str = ""
    pair: str = ""
    vars: dict[str, Any] = field(default_factory=dict)
    question: Question | None = None   # 單題覆寫

    @property
    def modalities(self) -> set[str]:
        return {p.type for p in self.inputs}


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    scenario: str
    description: str
    question: Question
    items: tuple[Item, ...]
    metric: str = "classification"
    positive: str = "yes"          # binary 任務算 AUC 時的正類
    source: str = ""
    path: str = ""

    @property
    def modalities(self) -> set[str]:
        out: set[str] = set()
        for it in self.items:
            out |= it.modalities
        return out

    @property
    def scored(self) -> bool:
        return self.metric == "classification"

    def question_for(self, item: Item) -> Question:
        return (item.question or self.question).render(item.vars)


def _question(raw: dict, where: str) -> Question:
    qtype = raw.get("type")
    if qtype not in QUESTION_TYPES:
        raise TaskError(f"{where}: 題型必須是 {QUESTION_TYPES}，收到 {qtype!r}")
    if not raw.get("instructions"):
        raise TaskError(f"{where}: 缺少 instructions")
    options = raw.get("options") or {}
    if qtype == "choice" and len(options) < 2:
        raise TaskError(f"{where}: choice 至少要兩個選項")
    return Question(qtype, raw["instructions"], dict(options))


def parse_task(raw: dict, path: str = "") -> Task:
    tid = raw.get("id") or Path(path).stem
    where = f"任務 {tid}"
    if raw.get("scenario") not in SCENARIOS:
        raise TaskError(f"{where}: scenario 必須是 {list(SCENARIOS)}")
    metric = raw.get("metric", "classification")
    if metric not in METRICS:
        raise TaskError(f"{where}: metric 必須是 {METRICS}")
    question = _question(raw.get("question") or {}, where)
    items = []
    seen = set()
    for i, it in enumerate(raw.get("items") or []):
        iid = it.get("id") or f"{tid}-{i}"
        if iid in seen:
            raise TaskError(f"{where}: 重複的 item id {iid}")
        seen.add(iid)
        parts = []
        for p in it.get("inputs") or []:
            if p.get("type") not in INPUT_TYPES:
                raise TaskError(f"{where}/{iid}: 輸入型別必須是 {INPUT_TYPES}")
            if p["type"] == "text":
                parts.append(Part("text", text=p.get("text", "")))
            else:
                if not p.get("path"):
                    raise TaskError(f"{where}/{iid}: {p['type']} 需要 path")
                parts.append(Part(p["type"], path=p["path"]))
        if not parts:
            raise TaskError(f"{where}/{iid}: 至少要一個輸入")
        q = _question(it["question"], f"{where}/{iid}") if it.get("question") else None
        item = Item(iid, tuple(parts), it.get("gold"), it.get("group", ""), it.get("pair", ""),
                    dict(it.get("vars") or {}), q)
        labels = (q or question).labels
        if metric == "classification":
            if item.gold not in labels:
                raise TaskError(f"{where}/{iid}: gold {item.gold!r} 不在選項 {labels} 內")
        elif not item.pair:
            raise TaskError(f"{where}/{iid}: swap_symmetry 任務的每題都要有 pair")
        items.append(item)
    if not items:
        raise TaskError(f"{where}: 沒有任何題項")
    return Task(tid, raw.get("title", tid), raw["scenario"], raw.get("description", ""),
                question, tuple(items), metric, raw.get("positive", "yes"),
                raw.get("source", ""), path)


def load_task(path: Path) -> Task:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rel = str(Path(path).resolve().relative_to(ROOT)) if Path(path).resolve().is_relative_to(ROOT) else str(path)
    return parse_task(raw, rel)


def load_tasks(patterns: list[str] | None = None) -> list[Task]:
    """依 glob（相對 tasks/）載入任務；不給就載入全部。"""
    files: list[Path] = []
    for pat in patterns or ["**/*.json"]:
        if not pat.endswith(".json"):
            pat = pat.rstrip("/") + ("/**/*.json" if (TASKS_DIR / pat).is_dir() else ".json")
        files.extend(sorted(TASKS_DIR.glob(pat)))
    seen: dict[str, Task] = {}
    for f in files:
        t = load_task(f)
        seen.setdefault(t.id, t)
    return list(seen.values())
