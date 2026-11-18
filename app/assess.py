"""發音練習的判讀層。

同一段錄音跑三個判斷：
  1. Decisions API（gemini-decision-1）：校準機率 + 分級 + 逐字 choice
  2. Argon 盲聽：不給目標句，只做聽寫 → 由程式自行比對，避免「迎合答案」
  3. Argon 評分：給目標句，要求逐字診斷與建議

盲聽那一支是關鍵：實測發現生成式模型在知道答案時會把 near-miss 自動修正
（把 hooks 聽成 books），所以「有沒有唸對」不能只信評分那一支。
"""
from __future__ import annotations

import difflib
import json
import re
from concurrent.futures import ThreadPoolExecutor

import gemini

DECISION_MODEL = gemini.DECISION_MODEL
JUDGE_MODEL = gemini.JUDGE_MODEL

LEVELS = [
    "完全聽不出是目標句（或幾乎全錯）",
    "多數詞錯誤，只有零星正確",
    "可辨識，但有明顯錯誤、需要修正",
    "大致正確，只有小瑕疵",
    "正確且自然，接近母語者",
]

ZH_PUNCT = "，。、！？；：「」『』（）《》…—～·,.!?;:\"'()[]{}<>-– "
WORD_RE = re.compile(r"[A-Za-z']+|[0-9]+")

BLIND_SCHEMA = {
    "type": "object",
    "properties": {
        "transcript": {"type": "string"},
        "confidence": {"type": "number"},
        "noise": {"type": "string"},
    },
    "required": ["transcript", "confidence", "noise"],
}

ARGON_SCHEMA = {
    "type": "object",
    "properties": {
        "transcript": {"type": "string"},
        "overall": {"type": "integer"},
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "heard": {"type": "string"},
                    "status": {"type": "string",
                               "enum": ["correct", "mispronounced", "missing", "extra"]},
                    "note": {"type": "string"},
                },
                "required": ["word", "heard", "status", "note"],
            },
        },
        "tips": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["transcript", "overall", "words", "tips", "summary"],
}

BLIND_PROMPT = """你是聽寫員，不是老師。請只把你聽到的內容寫下來（{lang_name}，用{script}）。

重要規則：
- 不要自動修正成「合理的句子」。如果某個字聽起來像別的字，就寫你實際聽到的。
- 不要補充你沒聽到的字，也不要省略你聽到的字。
- 若聽到非語詞的聲音（音樂、雜訊、咳嗽），寫在 noise 欄位。
- 若完全沒有語音，transcript 留空字串。
- 輸出 JSON：transcript、confidence（0–1）、noise。"""

ARGON_PROMPT = """你是一位嚴格但鼓勵孩子的語言老師，正在評估一份朗讀錄音。

目標句子（{lang_name}）：{sentence}

請聽完音檔後回報：
1. transcript：你實際聽到的內容（{lang_name}）。**不要自動修正**：學生可能唸錯某個字，
   這時請寫出你實際聽到的音，而不是寫出題目上的字。
2. overall：0–100 的發音正確度。重點是「音是否正確」與「字是否正確」，不是口音或音色。
   80 以上代表清楚正確；60–79 代表聽得懂但有明顯錯誤；40–59 代表多處錯誤；40 以下代表幾乎不成句。
3. words：針對目標句子的每一個{unit}，比對你聽到的內容，給出 status：
   - correct：音正確
   - mispronounced：有唸但音不對{unit_extra}
   - missing：沒唸或唸不出來
   - extra：多唸的{unit}（word 填你多唸的內容）
   heard 請填你在該位置聽到的音；note 用繁體中文簡短說明（例如「聲調應為三聲」「th 咬舌音不見了」），正確時 note 留空字串。
4. tips：1–3 條具體可行的修正建議，用繁體中文，針對聽到的錯誤。
5. summary：一句話總結，繁體中文，語氣友善。

規則：
- 不要因為輕微口音扣分；只針對音與字的正確性。
- 特別注意「差一個音」的錯誤（例如 books 唸成 hooks、蘋果唸成蘋鍋），這種要抓出來。
- 若音檔沒有可辨識的語音，overall 給 0，transcript 給空字串，summary 說明「沒有聽到語音」。
- 只輸出 JSON。"""


def tokens_for(sentence: str, lang: str) -> list[str]:
    if lang == "zh":
        return [c for c in sentence if c not in ZH_PUNCT]
    return WORD_RE.findall(sentence)


def decisions_questions(sentence: str, lang: str, tokens: list[str]) -> dict:
    lang_name = "台灣華語" if lang == "zh" else "英文"
    questions: dict = {
        "overall": {
            "type": "noul",
            "instructions": (
                f"The audio is a learner reading this {lang_name} sentence aloud: 「{sentence}」. "
                "Did the speaker read the target sentence correctly and understandably?"
            ),
        },
        "level": {
            "type": "score",
            "instructions": (
                f"Rate how correctly the learner pronounced this {lang_name} sentence: 「{sentence}」"
            ),
            "criteria": LEVELS,
        },
    }
    for i, tok in enumerate(tokens[:12]):
        questions[f"w{i}"] = {
            "type": "choice",
            "instructions": (
                f"Target sentence: 「{sentence}」. Focusing on the {lang_name} "
                f"{'character' if lang == 'zh' else 'word'} 「{tok}」, "
                "what happened in the recording?"
            ),
            "criteria": {
                "correct": "pronounced correctly",
                "wrong": "pronounced but the sound is wrong",
                "missing": "not pronounced / skipped",
            },
        }
    return questions


def argon_prompt(sentence: str, lang: str) -> str:
    if lang == "zh":
        return ARGON_PROMPT.format(
            lang_name="台灣華語", sentence=sentence, unit="字",
            unit_extra="（heard 請填你聽到的注音或拼音與聲調，例如 lü2）",
        )
    return ARGON_PROMPT.format(lang_name="英文", sentence=sentence, unit="單字", unit_extra="")


def blind_prompt(lang: str) -> str:
    if lang == "zh":
        return BLIND_PROMPT.format(lang_name="台灣華語", script="繁體中文漢字")
    return BLIND_PROMPT.format(lang_name="英文", script="英文原字")


# ------------------------------------------------------------------ 盲聽比對
def diff_blind(target: str, heard: str, lang: str) -> dict:
    """把盲聽結果和目標句做序列比對，得到逐字狀態（純程式判斷，不經過模型）。"""
    tt = tokens_for(target, lang)
    if lang == "zh":
        hh = [c for c in (heard or "") if c not in ZH_PUNCT]
    else:
        hh = WORD_RE.findall((heard or "").lower())
    tl = [t.lower() for t in tt]
    hl = [h.lower() for h in hh]

    rows: list[dict] = []
    sm = difflib.SequenceMatcher(a=tl, b=hl, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({"token": tt[i1 + k], "heard": hh[j1 + k], "status": "correct"})
        elif tag == "replace":
            pairs = min(i2 - i1, j2 - j1)
            for k in range(pairs):
                rows.append({"token": tt[i1 + k], "heard": hh[j1 + k], "status": "substituted"})
            for k in range(i1 + pairs, i2):
                rows.append({"token": tt[k], "heard": "", "status": "missing"})
            for k in range(j1 + pairs, j2):
                rows.append({"token": "", "heard": hh[k], "status": "extra"})
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append({"token": tt[k], "heard": "", "status": "missing"})
        elif tag == "insert":
            for k in range(j1, j2):
                rows.append({"token": "", "heard": hh[k], "status": "extra"})

    expected = [r for r in rows if r["status"] != "extra"]
    hit = sum(1 for r in expected if r["status"] == "correct")
    return {
        "words": rows,
        "correct": hit,
        "total": len(tt),
        "rate": round(hit / len(tt), 3) if tt else 0.0,
        "extra": [r["heard"] for r in rows if r["status"] == "extra"],
    }


def _normalise_argon(raw: dict, tokens: list[str]) -> dict:
    heard_map = {}
    for w in raw.get("words", []) or []:
        key = (w.get("word") or "").strip().lower()
        if key:
            heard_map[key] = w
    words = []
    for tok in tokens:
        item = heard_map.get(tok.strip().lower())
        if item:
            words.append({
                "token": tok,
                "heard": item.get("heard", ""),
                "status": item.get("status", "unknown"),
                "note": item.get("note", ""),
            })
        else:
            words.append({"token": tok, "heard": "", "status": "unscored", "note": ""})
    extras = [w for k, w in heard_map.items() if k not in {t.lower() for t in tokens}]
    return {
        "transcript": raw.get("transcript", ""),
        "overall": int(raw.get("overall") or 0),
        "words": words,
        "extras": [{"token": w.get("word", ""), "heard": w.get("heard", "")} for w in extras],
        "tips": raw.get("tips", []) or [],
        "summary": raw.get("summary", ""),
    }


# ------------------------------------------------------------------ 三支呼叫
def _run_decisions(audio, mime, sentence, lang, tokens):
    questions = decisions_questions(sentence, lang, tokens)
    with gemini.Timer() as timer:
        try:
            result = gemini.decide(audio, mime, questions)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "model": DECISION_MODEL, "error": str(exc)[:300],
                    "latency_ms": getattr(timer, "ms", None)}

    answers = result.get("answers", {})
    level = answers.get("level", {}) or {}
    probs = level.get("probabilities", {}) or {}
    raw_score = float(level.get("score", 0)) if probs else 0.0
    level_idx = int(round(raw_score))
    words = []
    for i, tok in enumerate(tokens[:12]):
        ans = answers.get(f"w{i}", {}) or {}
        p = ans.get("probabilities", {}) or {}
        top = max(p, key=p.get) if p else "unknown"
        words.append({"token": tok, "verdict": top, "probs": {k: round(v, 3) for k, v in p.items()}})

    usage = result.get("usage", {})
    return {
        "ok": True,
        "model": DECISION_MODEL,
        "p_correct": round(float(answers.get("overall", {}).get("noul", 0.0)), 3),
        "level": level_idx,
        "level_raw": round(raw_score, 2),
        "level_label": (level.get("legend", {}) or {}).get(str(level_idx), ""),
        "level_probs": {k: round(v, 3) for k, v in probs.items()},
        "words": words,
        "usage": usage,
        "cost_usd": round(gemini.estimate_cost(DECISION_MODEL, usage), 6),
        "latency_ms": timer.ms,
    }


def _run_argon(audio, mime, sentence, lang, tokens, thinking="low"):
    with gemini.Timer() as timer:
        try:
            result = gemini.generate(argon_prompt(sentence, lang), audio, mime, model=JUDGE_MODEL,
                                     thinking=thinking, response_schema=ARGON_SCHEMA)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "model": JUDGE_MODEL, "error": str(exc)[:300],
                    "latency_ms": getattr(timer, "ms", None)}

    usage = result.get("usage", {})
    try:
        raw = json.loads(result["text"])
    except json.JSONDecodeError:
        return {"ok": False, "model": JUDGE_MODEL, "error": "JSON 解析失敗：" + result["text"][:200],
                "usage": usage, "latency_ms": timer.ms,
                "cost_usd": round(gemini.estimate_cost(JUDGE_MODEL, usage), 6)}

    return {
        "ok": True,
        "model": JUDGE_MODEL,
        **_normalise_argon(raw, tokens),
        "usage": usage,
        "cost_usd": round(gemini.estimate_cost(JUDGE_MODEL, usage), 6),
        "latency_ms": timer.ms,
    }


def _run_blind(audio, mime, sentence, lang, tokens, thinking="low"):
    with gemini.Timer() as timer:
        try:
            result = gemini.generate(blind_prompt(lang), audio, mime, model=JUDGE_MODEL,
                                     thinking=thinking, response_schema=BLIND_SCHEMA)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "model": JUDGE_MODEL, "error": str(exc)[:300],
                    "latency_ms": getattr(timer, "ms", None)}

    usage = result.get("usage", {})
    try:
        raw = json.loads(result["text"])
    except json.JSONDecodeError:
        return {"ok": False, "model": JUDGE_MODEL, "error": "JSON 解析失敗：" + result["text"][:200],
                "usage": usage, "latency_ms": timer.ms,
                "cost_usd": round(gemini.estimate_cost(JUDGE_MODEL, usage), 6)}

    transcript = (raw.get("transcript") or "").strip()
    return {
        "ok": True,
        "model": JUDGE_MODEL,
        "transcript": transcript,
        "confidence": raw.get("confidence"),
        "noise": raw.get("noise", ""),
        "diff": diff_blind(sentence, transcript, lang),
        "usage": usage,
        "cost_usd": round(gemini.estimate_cost(JUDGE_MODEL, usage), 6),
        "latency_ms": timer.ms,
    }


def agreement(decisions: dict, argon: dict, blind: dict | None = None) -> dict:
    """逐字判斷的一致性。"""
    out: dict = {}
    if decisions.get("ok") and blind and blind.get("ok"):
        dmap = {w["token"]: w["verdict"] for w in decisions.get("words", [])}
        pairs = []
        for w in blind["diff"]["words"]:
            if not w["token"]:
                continue
            dv = dmap.get(w["token"])
            bv = {"correct": "correct", "substituted": "wrong", "missing": "missing"}.get(w["status"])
            if dv is None or bv is None:
                continue
            pairs.append({"token": w["token"], "decisions": dv, "blind": bv, "same": dv == bv})
        if pairs:
            out["decisions_vs_blind"] = {
                "n": len(pairs),
                "same": sum(1 for p in pairs if p["same"]),
                "rate": round(sum(1 for p in pairs if p["same"]) / len(pairs), 3),
            }
    if argon.get("ok") and blind and blind.get("ok"):
        amap = {w["token"]: w["status"] for w in argon.get("words", [])}
        pairs = []
        for w in blind["diff"]["words"]:
            if not w["token"]:
                continue
            av = amap.get(w["token"])
            bv = {"correct": "correct", "substituted": "mispronounced",
                  "missing": "missing"}.get(w["status"])
            if av is None or bv is None or av == "unscored":
                continue
            pairs.append({"token": w["token"], "argon": av, "blind": bv, "same": av == bv})
        if pairs:
            out["argon_vs_blind"] = {
                "n": len(pairs),
                "same": sum(1 for p in pairs if p["same"]),
                "rate": round(sum(1 for p in pairs if p["same"]) / len(pairs), 3),
            }
    return out


def assess(audio: bytes, mime: str, sentence: str, lang: str, thinking: str = "low") -> dict:
    tokens = tokens_for(sentence, lang)
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_dec = pool.submit(_run_decisions, audio, mime, sentence, lang, tokens)
        f_arg = pool.submit(_run_argon, audio, mime, sentence, lang, tokens, thinking)
        f_bli = pool.submit(_run_blind, audio, mime, sentence, lang, tokens, thinking)
        decisions, argon, blind = f_dec.result(), f_arg.result(), f_bli.result()

    return {
        "model_input": {"mime": mime, "bytes": len(audio), "tokens": tokens},
        "decisions": decisions,
        "argon": argon,
        "blind": blind,
        "agreement": agreement(decisions, argon, blind),
        "cost_usd": round(sum(x.get("cost_usd") or 0 for x in (decisions, argon, blind)), 6),
    }
