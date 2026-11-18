#!/usr/bin/env python3
"""把 ms-bench.json 整理成 Markdown 報告。

用法：
  python3 scripts/ms_report.py
輸出：
  out/ms-decision-report.md
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
CAT_NAME = {
    "speech": "單人說話", "singing": "唱歌", "music": "純音樂", "noise": "環境噪音",
    "concert": "演唱會", "multi_speech": "多人說話", "speech_music": "說話＋音樂",
}


def main() -> None:
    d = json.loads((OUT / "ms-bench.json").read_text(encoding="utf-8"))
    s = d["summary"]
    a, tc = s.get("taskA", {}), s.get("taskC", {})
    tb = s.get("taskB", {})

    L: list[str] = []
    add = L.append

    add("# Microsoft Decision 1.1 實測")
    add("")
    add("測試日期：2026-11-19　｜　端點：`mvpai-eastus.services.ai.azure.com/providers/microsoft/v1/systemone`　｜　"
        "Deployment：`Decision-1.1`")
    add("")
    add("---")
    add("")
    add("## 一句話結論")
    add("")
    add("**這個端點只吃文字。** 送進去的音訊會被當成 base64 字串、以純文字 token 計價，模型看不到聲音——"
        "所以先前三項音訊測試（單音節、音場、發音）無法在它身上執行。"
        "在**文字**任務上它與 `gemini-decision-1` 表現接近，但每次呼叫慢兩倍多，"
        "而且實測只有約三成請求第一次就成功——其餘會直接斷線。")
    add("")

    add("## 快速對照")
    add("")
    add("| | Microsoft Decision 1.1 | Gemini Decision 1 |")
    add("| --- | --- | --- |")
    add("| 音訊輸入 | ❌ 不支援（base64 當文字） | ✅ 25 tokens／秒 |")
    add("| 題型 | `noul` / `choice` / `score` | 同 |")
    if a.get("ms") and a.get("gemini"):
        add(f"| 轉錄稿分類（7 類） | {a['ms']['ok']}/{a['ms']['n']}（{a['ms']['acc']}%） | "
            f"{a['gemini']['ok']}/{a['gemini']['n']}（{a['gemini']['acc']}%） |")
        ops0 = s.get("ops") or {}
        add(f"| 成功呼叫延遲（中位數） | {ops0.get('latency_median_ms', '—')} ms | {a['gemini']['ms']:,} ms |")
    if tb.get("ms") and tb.get("gemini"):
        add(f"| 情緒校準 AUC | {tb['ms']['auc']} | {tb['gemini']['auc']} |")
    if tc.get("ms") and tc.get("gemini"):
        add(f"| 垃圾訊息判對 | {tc['ms']['correct']}/{tc['ms']['n']} | {tc['gemini']['correct']}/{tc['gemini']['n']} |")
    ops0 = s.get("ops") or {}
    if ops0.get("first_try_rate") is not None:
        add(f"| 第一次就成功的比例 | **{ops0['first_try_rate']}%** | 100% |")
    add("")

    # ---------------- 一
    add("## 一、核心發現：它沒有在聽")
    add("")
    add("四個獨立證據，任何一個都足以證明音訊沒有被解碼：")
    add("")
    add("| # | 實驗 | 結果 | 意義 |")
    add("| --- | --- | --- | --- |")
    add("| 1 | `data` 塞入 `\"hello world\"`（不是合法 base64） | 正常回傳、51 tokens | 若真的解碼，會直接報錯 |")
    add("| 2 | `{\"type\":\"zzz\"}` 這種不存在的型別 | 也被接受、28 tokens | `state` 只是被序列化成文字 |")
    add("| 3 | 0.4 秒音檔（4 KB）→ 3,363 tokens；1.0 秒（19 KB）→ 13,880 tokens | 隨**檔案大小**成長，不隨長度 | 這是 base64 的文字 token |")
    add("| 4 | 10 秒音檔（161 KB base64） | `413 question_context_limit`，`processed_input_tokens: 110,045` | 單段 10 秒音訊就吃掉 11 萬 tokens |")
    add("")
    add("對照之下，同樣 1 秒的音訊：")
    add("")
    add("| | 音訊 1 秒的 token | 換算 42 段 10 秒片段的成本 |")
    add("| --- | --- | --- |")
    add("| Gemini Decision 1 | 25 | 約 10,500 tokens |")
    add("| Microsoft Decision 1.1 | 約 13,880（且不保證聽得到） | 約 580,000 tokens，且多數會超過上限 |")
    add("")
    add("> 這一點與官方文件是否宣稱支援音訊無關——**這是這個 deployment 的實際行為**，我沒有找到任何能讓它接收到聲音的欄位。")
    add("")

    # ---------------- 二
    add("## 二、API 形狀")
    add("")
    add("```jsonc")
    add("POST /providers/microsoft/v1/systemone")
    add("api-key: <key>")
    add("{")
    add('  "model": "Decision-1.1",')
    add('  "state": { "type": "text", "text": "I love this product" },')
    add('  "questions": {')
    add('    "q": { "type": "noul",  "instructions": "Is this positive?" },')
    add('    "c": { "type": "choice", "instructions": "Which?", "criteria": { "a": "A", "b": "B" } },')
    add('    "s": { "type": "score",  "instructions": "Rate", "criteria": ["bad", "good"] }')
    add("  }")
    add("}")
    add("```")
    add("")
    add("回傳：")
    add("")
    add("```jsonc")
    add('{ "model": "microsoft-decision-1.1",')
    add('  "answers": { "q": { "type": "noul", "noul": 0.9359 } },')
    add('  "usage": { "input_tokens": 21, "output_tokens": 1 } }')
    add("```")
    add("")
    add("三個題型的回傳與 Gemini 幾乎一致（`noul` 機率、`choice` 的 `choice`＋`probabilities`、"
        "`score` 的 `score`＋`legend`＋`probabilities`），差異在：")
    add("")
    add("- `state` 只接受**單一物件**，傳陣列會直接斷線；")
    add("- 沒有 `confidence` 欄位（`choice` / `score` 有，`noul` 沒有）；")
    add("- `usage` 只有 `input_tokens` / `output_tokens`，沒有文字／音訊分項。")
    add("")

    # ---------------- 三
    add("## 三、文字任務結果")
    add("")
    add("既然音訊走不通，就比較兩邊都能吃的文字任務。")
    add("")
    add("### Task A：42 段轉錄稿 → 7 類音場")
    add("")
    add("拿研究二的 Whisper 轉錄稿當輸入（音樂與噪音的轉錄稿本來就是空的，所以這題對兩邊都很難）。")
    add("")
    if a:
        add("| 模型 | 正確 | 正確率 | 平均延遲 | 失敗 |")
        add("| --- | --- | --- | --- | --- |")
        for k, name in (("ms", "MS Decision 1.1"), ("gemini", "Gemini Decision 1")):
            v = a.get(k)
            if v:
                add(f"| {name} | {v['ok']}/{v['n']} | {v['acc']}% | {v['ms']:,} ms | {v['fail']} |")
        add("")
        add(f"兩邊答案一致：**{s['taskA_agree']['agree']}/{s['taskA_agree']['n']}"
            f"（{s['taskA_agree']['rate']}%）**——它們對同一段文字的判斷幾乎相同。")
        add("")
        rows = []
        for c in CAT_NAME:
            m1 = a.get("ms", {}).get("per_class", {}).get(c)
            m2 = a.get("gemini", {}).get("per_class", {}).get(c)
            if m1 and m2:
                rows.append(f"| {CAT_NAME[c]} | {m1['hit']}/{m1['n']} | {m2['hit']}/{m2['n']} |")
        if rows:
            add("| 類別 | MS | Gemini |")
            add("| --- | --- | --- |")
            L.extend(rows)
            add("")

    add("### Task B：18 句商品評論的正負向（機率校準）")
    add("")
    if tb:
        add("| 模型 | 正面平均 P | 中性平均 P | 負面平均 P | AUC | ≥0.5 判對 |")
        add("| --- | --- | --- | --- | --- | --- |")
        for k, name in (("ms", "MS Decision 1.1"), ("gemini", "Gemini Decision 1")):
            v = tb.get(k)
            if v:
                add(f"| {name} | {v['mean_pos']} | {v['mean_neutral']} | {v['mean_neg']} | "
                    f"{v['auc']} | {v['correct_at_0_5']}/{v['n']} |")
        add("")
        add("兩邊都全對，差別在**機率的銳利度**：MS 把負面壓到 0.001、正面拉到 0.948；"
            "Gemini 則是 0.045 與 0.901。以「拿門檻做決策」來說，MS 的分布比較好用；"
            "但要小心這種銳利度在邊界案例上容易過度自信。")
        add("")

    add("### Task C：24 封訊息判斷垃圾／釣魚")
    add("")
    if tc:
        add("| 模型 | 垃圾平均 P | 正常平均 P | AUC | 判對 | 平均延遲 | 失敗 |")
        add("| --- | --- | --- | --- | --- | --- | --- |")
        for k, name in (("ms", "MS Decision 1.1"), ("gemini", "Gemini Decision 1")):
            v = tc.get(k)
            if v:
                add(f"| {name} | {v['mean_spam']} | {v['mean_ham']} | {v['auc']} | "
                    f"{v['correct']}/{v['n']} | {v['ms']:,} ms | {v['fail']} |")
        add("")

    # ---------------- 四
    add("## 四、操作特性：快，但不穩")
    add("")
    ops = s.get("ops") or {}
    if ops.get("latency_median_ms") and a.get("gemini"):
        ratio = ops["latency_median_ms"] / max(1, a["gemini"]["ms"])
        add(f"- **延遲**：成功的呼叫中位數 **{ops['latency_median_ms']} ms**（範圍 "
            f"{ops['latency_min_ms']}–{ops['latency_max_ms']} ms），Gemini 約 {a['gemini']['ms']} ms，"
            f"**約 {ratio:.1f} 倍**。")
        add(f"  （上面表格裡的「平均延遲」把重試退避也算進去了，所以看起來接近 10 倍；"
            f"單次成功呼叫其實只差兩倍多。）")
    if ops.get("first_try_rate") is not None:
        add(f"- **穩定度**：實測連續 {ops['probe_calls']} 次請求，只有 **{ops['probe_ok']} 次第一次就成功"
            f"（{ops['first_try_rate']}%）**。其餘全部是同一種錯誤：`SSL: UNEXPECTED_EOF_WHILE_READING`"
            f"——伺服器直接斷線，不是 4xx/5xx。")
    add(f"- **最終失敗**：Task A 有 {a.get('ms', {}).get('fail', '—')}/42、"
        f"Task C 有 {tc.get('ms', {}).get('fail', '—')}/24 在重試 6 次後仍然失敗。"
        f"Gemini 這一輪 {a.get('gemini', {}).get('n', 42)} 次全部一次成功。")
    add("- **退避策略**：實務上至少要 4 次指數退避重試，並且要把「斷線」當成可重試錯誤，"
        "否則會有大約四成的請求直接消失。")
    add("- **計價**：MS 只回 `input_tokens` / `output_tokens`，沒有分項；"
        "這個 deployment 的價格我查不到公開資訊，所以本報告只列 token 數，不換算金額。")
    add("")

    # ---------------- 五
    add("## 五、對你的專案意味著什麼")
    add("")
    add("| 你想做的事 | MS Decision 1.1 | 建議 |")
    add("| --- | --- | --- |")
    add("| 單音節聲調驗收 | ❌ 收不到音訊 | 維持 Argon |")
    add("| 音場分類（有沒有人聲、演唱會、多人） | ❌ 收不到音訊 | Decisions 當守門員、Argon 做細分類 |")
    add("| 發音練習判斷 | ❌ 收不到音訊 | Argon＋盲聽＋尾靜音補償 |")
    add("| 文字內容決策（分類、路由、審核） | ✅ 可以，表現與 Gemini 接近 | 若已在 Azure 上，MS 是合理選項；否則 Gemini 快 10 倍 |")
    add("")
    add("**如果你要的是「微軟版的 Decisions API」來做音訊**：這個 deployment 做不到。"
        "要嘛等支援音訊的版本／端點，要嘛在前面接一層 ASR，把聲音變成文字再送進來——"
        "但那樣就測不到發音，只能測「內容」。")
    add("")

    # ---------------- 六
    add("## 六、方法與限制")
    add("")
    add("- 環境：macOS arm64、Python 3（僅標準函式庫）、`temperature` 未提供（API 無此參數）。")
    add("- Task A 的輸入是 Whisper 轉錄稿，音樂與噪音片段多為空字串，因此兩個模型都只有四成——"
        "**這不代表模型差，是這個題目在文字上本來就沒有足夠資訊**。")
    add("- Task B / C 的語料是我手寫的 18 + 24 句，標籤明確但樣本小，只能看方向。")
    add("- MS 端點沒有提供種子或溫度，重跑可能不同；Gemini 端 `temperature: 0` 但仍有漂移（見研究一）。")
    add("- 音訊不支援的結論是**針對這個 deployment**，不代表 Microsoft 其他服務也不能處理音訊。")
    add("")

    add("## 七、如何重跑")
    add("")
    add("```bash")
    add('export MS_KEY="<你的 key>"')
    add("python3 scripts/ms_bench.py            # 三個文字任務")
    add("python3 scripts/ms_report.py           # 產生這份報告")
    add("```")
    add("")
    add("原始數據：`out/ms-bench.json`（含每一次呼叫的延遲、嘗試次數、token 與完整回覆）。")
    add("")

    (OUT / "ms-decision-report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"→ {OUT / 'ms-decision-report.md'}")


if __name__ == "__main__":
    main()
