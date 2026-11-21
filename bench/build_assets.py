"""產生評測素材與任務檔（可重複執行，結果固定）。

    python3 -m bench build

會做三件事：
1. ``bench/fixtures/``：模態探針用的純色圖與「假媒體」檔。
2. ``assets/images/``：用 ffmpeg 的 drawbox／drawtext 合成影像題（標註由程式決定，不需人工）。
3. ``tasks/audio/*.json``、``tasks/image/*.json``：把既有三項音訊研究與影像題轉成標準任務格式。

文字類任務（中文、Agent、台灣政經）是手寫的 JSON，不由本檔產生。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .schema import ROOT

FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
FIX = ROOT / "bench" / "fixtures"
IMG = ROOT / "assets" / "images"
TASKS = ROOT / "tasks"
W, H = 768, 512

COLORS = {"red": "#d62828", "green": "#2a9d3f", "blue": "#1d4ed8", "yellow": "#f2c200"}


# ------------------------------------------------------------------ ffmpeg
def _ffmpeg(filters: list[str], out: Path, bg: str = "white", size: tuple[int, int] = (W, H)) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = ",".join(filters) if filters else "null"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={bg}:s={size[0]}x{size[1]}",
           "-frames:v", "1", "-vf", vf, str(out)]
    subprocess.run(cmd, check=True)


class Canvas:
    """累積 drawbox／drawtext 濾鏡；文字走 textfile，避免 ffmpeg 跳脫字元的麻煩。"""

    def __init__(self, tmp: Path):
        self.filters: list[str] = []
        self.tmp = tmp
        self.n = 0

    def box(self, x, y, w, h, color, fill=True):
        self.filters.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t={'fill' if fill else 3}")
        return self

    def text(self, s, x, y, size=48, color="black"):
        self.n += 1
        f = self.tmp / f"t{self.n}.txt"
        f.write_text(s, encoding="utf-8")
        self.filters.append(f"drawtext=fontfile='{FONT}':textfile='{f}':fontsize={size}:"
                            f"fontcolor={color}:x={x}:y={y}")
        return self

    def save(self, out: Path, bg="white"):
        _ffmpeg(self.filters, out, bg)


# ------------------------------------------------------------------ fixtures
def build_fixtures(tmp: Path) -> None:
    for name, color in [("red", "#d62828"), ("red_dark", "#8b1111"), ("blue", "#1d4ed8"), ("green", "#2a9d3f")]:
        _ffmpeg([], FIX / f"{name}.png", bg=color, size=(512, 512))
    (FIX / "invalid.png").write_bytes(b"hello world, this is not a PNG file")
    (FIX / "invalid.mp3").write_bytes(b"hello world, this is not an MP3 file")


# ------------------------------------------------------------------ 影像任務
SQUARE_LAYOUTS = [(80, 90), (330, 90), (580, 90), (200, 300), (450, 300)]


def task_image_color(tmp: Path) -> dict:
    items = []
    layouts = [(234, 106, 300, 300), (60, 60, 648, 392)]
    for color, hexv in COLORS.items():
        for i, (x, y, w, h) in enumerate(layouts):
            path = IMG / "color" / f"{color}_{i}.png"
            Canvas(tmp).box(x, y, w, h, hexv).save(path, bg="#f4f4f4")
            items.append({"id": f"{color}_{i}", "inputs": [{"type": "image", "path": _rel(path)}], "gold": color})
    return {
        "id": "image-color", "scenario": "image", "title": "主色辨識（健全性檢查）",
        "description": "灰底上一個大色塊，問主色是什麼。看不到圖的模型只能猜（25%），用來確認影像通道真的有在運作。",
        "question": {"type": "choice", "instructions": "What is the color of the large shape in this image?",
                     "options": {c: f"the shape is {c}" for c in COLORS}},
        "items": items,
    }


def task_image_count(tmp: Path) -> dict:
    items = []
    for n in range(1, 6):
        for variant, color in enumerate(["#1d4ed8", "#d62828"]):
            c = Canvas(tmp)
            order = SQUARE_LAYOUTS if variant == 0 else list(reversed(SQUARE_LAYOUTS))
            for x, y in order[:n]:
                c.box(x, y, 110, 110, color)
            path = IMG / "count" / f"n{n}_{variant}.png"
            c.save(path)
            items.append({"id": f"n{n}_{variant}", "inputs": [{"type": "image", "path": _rel(path)}],
                          "gold": str(n)})
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
    return {
        "id": "image-count", "scenario": "image", "title": "數方塊（1–5 個）",
        "description": "白底上 1 到 5 個同色方塊。數量是決策模型常見的弱點（研究二的「幾個人在講」就失敗）。",
        "question": {"type": "choice", "instructions": "How many filled squares are in this image?",
                     "options": {str(n): f"exactly {w} square{'s' if n > 1 else ''}" for n, w in words.items()}},
        "items": items,
    }


ZH_CHAR_GROUPS = [
    ["未", "末", "本", "朱"], ["己", "已", "巳"], ["天", "夭", "夫", "失"],
    ["土", "士", "干", "千"], ["日", "曰", "目", "旦"], ["戊", "戌", "戍", "戎"],
]


def task_image_zh_char(tmp: Path) -> dict:
    items = []
    for gi, group in enumerate(ZH_CHAR_GROUPS):
        opts = list(dict.fromkeys(group))
        for ci, ch in enumerate(opts):  # 每個字都當一次正解，正解位置平均分布、避免位置偏誤
            path = IMG / "zh_char" / f"g{gi}_{ci}.png"
            Canvas(tmp).text(ch, "(w-text_w)/2", "(h-text_h)/2", size=260).save(path)
            items.append({
                "id": f"g{gi}_{ci}", "inputs": [{"type": "image", "path": _rel(path)}], "gold": ch,
                "question": {"type": "choice",
                             "instructions": "Which Traditional Chinese character is shown in this image?",
                             "options": {o: f"the character 「{o}」" for o in opts}},
            })
    return {
        "id": "image-zh-char", "scenario": "image", "title": "形近繁中字辨識",
        "description": "單一大字，選項是形近字（未／末、己／已／巳、戊／戌／戍……）。每個字都輪流當正解（正解平均分布在各選項位置），測細部筆畫的視覺辨識。",
        "question": items[0]["question"],
        "items": items,
    }


ZHUYIN_SETS = [
    ["ㄌㄨˊ", "ㄌㄩˊ", "ㄌㄩˇ", "ㄌㄨˋ"],
    ["ㄇㄚ", "ㄇㄚˊ", "ㄇㄚˇ", "ㄇㄚˋ"],
]


def task_image_zhuyin(tmp: Path) -> dict:
    items = []
    for si, opts in enumerate(ZHUYIN_SETS):
        for oi, zy in enumerate(opts):
            path = IMG / "zhuyin" / f"s{si}_{oi}.png"
            Canvas(tmp).text(zy, "(w-text_w)/2", "(h-text_h)/2", size=180).save(path)
            items.append({
                "id": f"s{si}_{oi}", "inputs": [{"type": "image", "path": _rel(path)}], "gold": zy,
                "question": {"type": "choice",
                             "instructions": "Which Zhuyin (Bopomofo) syllable, including its tone mark, is shown in this image?",
                             "options": {o: f"「{o}」" for o in opts}},
            })
    return {
        "id": "image-zhuyin", "scenario": "image", "title": "注音字卡（含聲調符號）",
        "description": "延續研究一的 ㄌㄨˊ／ㄌㄩ 主題，改成「看」注音字卡；四個選項只差韻母或聲調符號。",
        "question": items[0]["question"],
        "items": items,
    }


UI_SCREENS = [
    # (id, 橫幅底色, 橫幅文字, 內文, 是否為錯誤狀態)
    ("pay_fail", "#c62828", "付款失敗", "信用卡授權被拒，請改用其他付款方式。", "yes"),
    ("timeout", "#ef6c00", "連線逾時", "無法連線到伺服器，請檢查網路後重試。", "yes"),
    ("login_fail", "#c62828", "登入失敗", "帳號或密碼錯誤，還可以再試 2 次。", "yes"),
    ("err_grey", "#616161", "Error 500", "Internal Server Error. Request ID: 7f3a", "yes"),
    ("upload_fail", "#1565c0", "上傳未完成", "檔案超過 20 MB 上限，上傳已中止。", "yes"),
    ("pay_ok", "#2e7d32", "付款成功", "訂單 #48213 已成立，預計週二出貨。", "no"),
    ("loading", "#1565c0", "載入中…", "正在同步你的資料，請稍候。", "no"),
    ("saved", "#2e7d32", "已儲存", "所有變更都已儲存到雲端。", "no"),
    ("sale_red", "#c62828", "限時特價", "全館 8 折，今晚 12 點截止！", "no"),
    ("empty", "#455a64", "目前沒有通知", "有新訊息時會顯示在這裡。", "no"),
]


def task_image_ui(tmp: Path) -> dict:
    items = []
    for sid, color, title, body, gold in UI_SCREENS:
        c = Canvas(tmp)
        c.box(0, 0, W, 64, "#eceff1").text("我的帳戶", 28, 16, size=30, color="#263238")
        c.box(40, 110, W - 80, 110, color).text(title, 70, 140, size=46, color="white")
        c.text(body, 50, 260, size=28, color="#37474f")
        c.box(50, 400, 220, 70, "#cfd8dc").text("確定", 125, 418, size=32, color="#263238")
        path = IMG / "ui" / f"{sid}.png"
        c.save(path)
        items.append({"id": sid, "inputs": [{"type": "image", "path": _rel(path)}], "gold": gold})
    return {
        "id": "image-ui-error", "scenario": "image", "title": "App 畫面是否為錯誤狀態",
        "description": "合成的 App 截圖。刻意放了「紅底但不是錯誤」（限時特價）與「藍／灰底但是錯誤」，"
                       "測模型是看語意還是只看顏色。",
        "question": {"type": "binary",
                     "instructions": "Does this app screen show an error or failure state that the user needs to deal with?"},
        "items": items,
    }


def task_image_caption(tmp: Path) -> dict:
    """圖＋文字說明是否一致：重用 count 任務的圖。"""
    zh = {1: "一", 2: "兩", 3: "三", 4: "四", 5: "五"}
    cname = {0: "藍色", 1: "紅色"}
    items = []
    for n in range(1, 6):
        for variant in (0, 1):
            img = {"type": "image", "path": f"assets/images/count/n{n}_{variant}.png"}
            true_cap = f"圖中有{zh[n]}個{cname[variant]}方塊。"
            wrong_n = n + 1 if n < 5 else n - 1
            false_cap = (f"圖中有{zh[wrong_n]}個{cname[variant]}方塊。" if variant == 0
                         else f"圖中有{zh[n]}個{cname[1 - variant]}方塊。")
            items.append({"id": f"n{n}_{variant}_t", "inputs": [img, {"type": "text", "text": f"說明：{true_cap}"}],
                          "gold": "yes"})
            items.append({"id": f"n{n}_{variant}_f", "inputs": [img, {"type": "text", "text": f"說明：{false_cap}"}],
                          "gold": "no"})
    return {
        "id": "image-caption-match", "scenario": "image", "title": "圖文是否一致",
        "description": "同一張圖配上正確或錯誤（數量錯或顏色錯）的中文說明，問說明是否正確。測影像＋文字的跨模態比對。",
        "question": {"type": "binary", "instructions": "Does the caption accurately describe the image?"},
        "items": items,
    }


# ------------------------------------------------------------------ 音訊任務（既有研究）
SCENE_DESC = {  # 與研究二 scripts/scene_bench.py 的 CAT_DESC 逐字相同
    "speech": "one person talking, no background music (talk, lecture, audiobook)",
    "singing": "singing voice, with or without instrumental backing (a song)",
    "music": "instrumental music only, no human voice",
    "noise": "environmental noise only: rain, traffic, construction, white noise; no voice, no music",
    "concert": "live concert recording: amplified performance, audience/crowd, applause, echoes",
    "multi_speech": "several people talking (podcast, panel, interview, conversation)",
    "speech_music": "a person talking over background music (ad, vlog, explainer)",
}


def task_audio_scene() -> dict:
    man = json.loads((ROOT / "data/scenes/manifest.json").read_text(encoding="utf-8"))
    items = [{"id": c["id"], "inputs": [{"type": "audio", "path": c["file"]}], "gold": c["cat"], "group": c["cat"]}
             for c in man["clips"]]
    return {
        "id": "audio-scene-7class", "scenario": "audio", "title": "音場分類（7 類 × 6 段）",
        "description": "研究二的 42 段 YouTube 10 秒片段，標註經 Groq Whisper 獨立驗證。"
                       "原始結果：gemini-decision-1 32/42、concert 0/6。",
        "source": "data/scenes/manifest.json（音檔需先執行 scripts/fetch_scenes.py 下載）",
        "question": {"type": "choice", "instructions": "Which sound scene does this audio clip contain?",
                     "options": SCENE_DESC},
        "items": items,
    }


def task_audio_voice() -> dict:
    man = json.loads((ROOT / "data/scenes/manifest.json").read_text(encoding="utf-8"))
    voiced = {"speech", "singing", "concert", "multi_speech", "speech_music"}
    items = [{"id": c["id"], "inputs": [{"type": "audio", "path": c["file"]}],
              "gold": "yes" if c["cat"] in voiced else "no", "group": c["cat"]} for c in man["clips"]]
    return {
        "id": "audio-has-voice", "scenario": "audio", "title": "有沒有人聲（守門）",
        "description": "同一批 42 段，只問有沒有人聲（說話或唱歌）。原始結果：Decisions 42/42。",
        "source": "data/scenes/manifest.json",
        "question": {"type": "binary", "instructions": "Does this audio clip contain a human voice (speaking or singing)?"},
        "items": items,
    }


def task_audio_lu2() -> dict:
    labels = json.loads((ROOT / "data/labels.json").read_text(encoding="utf-8"))["clips"]
    items = [{"id": c["id"], "inputs": [{"type": "audio", "path": c["file"]}],
              "gold": "yes" if c["expect_lu2"] else "no", "group": c["category"]} for c in labels]
    return {
        "id": "audio-syllable-lu2", "scenario": "audio", "title": "單音節辨音：是不是 ㄌㄨˊ",
        "description": "研究一的 14 段注音音檔（含已知唸錯成 lü 的舊檔）。原始結果：gemini-decision-1 無鑑別力。",
        "source": "data/labels.json",
        "question": {"type": "binary", "instructions": "Is the spoken Mandarin syllable ㄌㄨˊ (lu, second tone)?"},
        "items": items,
    }


def _pad(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", "apad=pad_dur=0.6,asetnsamples=n=1152:p=0", "-ac", "1",
                    "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "96k", str(dst)], check=True)


def task_audio_pron() -> dict:
    man = json.loads((ROOT / "data/pron/manifest.json").read_text(encoding="utf-8"))
    items = []
    for c in man["clips"]:
        src = ROOT / c["file"]
        dst = ROOT / "data/pron/padded" / src.name
        if src.is_file():
            _pad(src, dst)
        lang = "Mandarin Chinese" if c["lang"] == "zh" else "English"
        items.append({"id": c["id"], "group": c["variant"], "gold": "yes" if c["gold"] == "ok" else "no",
                      "vars": {"target": c["target"], "lang": lang},
                      "inputs": [{"type": "audio", "path": _rel(dst)}]})
    return {
        "id": "audio-pron-ok", "scenario": "audio", "title": "發音練習：有沒有唸對目標句",
        "description": "研究三的 50 段 TTS 語料（正確／正確＋噪音／聲調錯／換字／漏字／離題），已補 0.6 秒尾靜音。",
        "source": "data/pron/manifest.json（音檔需先執行 scripts/build_pron_corpus.py 產生）",
        "question": {"type": "binary",
                     "instructions": "The audio is a learner reading this {lang} sentence aloud: 「{target}」. "
                                     "Did the speaker read the target sentence correctly, word for word?"},
        "items": items,
    }


# ------------------------------------------------------------------
def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def _write(task: dict) -> Path:
    path = TASKS / task["scenario"] / f"{task['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def build(log=print) -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit("需要 ffmpeg")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        build_fixtures(tmp)
        for fn in (task_image_color, task_image_count, task_image_zh_char, task_image_zhuyin,
                   task_image_ui, task_image_caption):
            log(f"  {_rel(_write(fn(tmp)))}")
    for fn in (task_audio_scene, task_audio_voice, task_audio_lu2, task_audio_pron):
        log(f"  {_rel(_write(fn()))}")
