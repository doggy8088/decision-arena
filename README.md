# Decision 模型評測

評測市面上的 **decision models**：一次前向傳播就直接回傳校準機率、不生成文字的決策模型。評測涵蓋多模態能力（文字、影像、音訊），以及五類情境：

- 語音
- 影像判斷
- 中文文字決策
- Agent 守門與路由
- 台灣政經

> 📊 **互動版報告**：[`bench-report.html`](bench-report.html)。單一 HTML 檔，支援深色模式。
> 報告由 `python3 -m bench report` 從 `results/` 直接產生。
>
> 🎛️ **互動式 Dashboard**：[`bench-dashboard.html`](bench-dashboard.html)。
> 用圖表呈現模型與模態、情境之間的關係，並能依需要的模態、焦點指標、分數與價格篩選可用模型。
> 由 `python3 -m bench dashboard` 產生。

第一輪：2026-11-22，共 **34 個模型 × 20 個任務**，7,327 次請求，總花費約 **US$0.28**。

## 重點結論（2026-11-22）

| 發現 | 數據 |
| --- | --- |
| 實測能解碼音訊的只有 4 個模型 | `gemini-decision-1`、`clef-omni`、`heygen-decision-1`（含 turbo）。Liquid d1.2 經 OpenRouter 送音訊會被拒收；它的原生 API 有寫音訊欄位，這輪沒測 |
| 發音判斷，`clef-omni` 勝過 Gemini | 發音練習 50 段 AUC 0.92 vs 0.78；音場 7 類 88% vs 76%；ㄌㄨˊ 辨音 AUC 1.00 vs 0.54（14 段中只有 2 段正例） |
| 聲調錯誤，沒有模型抓得到 | 5 段刻意唸錯聲調的錄音，最多只抓到 1 段 |
| 中文文字與 Agent 種子題組出現天花板效應 | 232 格中有 200 格是 100%，下一輪需要更難的題目 |
| 有鑑別力的是繁中細節與台灣知識 | 形近字 26%–83%；注音字卡 0%–75%；台灣政經選擇題 32%–84%（不含會上網的 `decisions-fast`） |
| 台灣題組的錯誤集中在 2025 年後的新事實 | 例如最大出口市場已是美國、上市市值第二為聯發科；多數模型答錯 |
| 新框架重現了原始研究 | 用原始題目描述，`gemini-decision-1` 音場分類 32/42，與 11-17 完全一致 |

## 架構

```text
bench/                     # 評測框架（純 Python 標準函式庫）
├── schema.py              # 任務格式：標準化題型 binary／choice、輸入 text／image／audio
├── providers/             # 每個模型一個 adapter，標準化題目 → 各家 API
│   ├── gemini.py          #   Google Decisions API 直連（音訊已驗證）
│   ├── openrouter.py      #   OpenRouter /api/alpha/decisions，33 個模型的名冊
│   └── mock.py            #   離線測試用
├── probe.py               # 模態探針：用正負例對照確認模型真的看得到／聽得到
├── runner.py              # 執行：快取、美元上限、模態守門、多模型平行
├── metrics.py             # 正確率、AUC、Brier、ECE、log loss、立場對稱 |Δ|
├── report.py              # 產生 bench-report.html
├── dashboard.py           # 產生 bench-dashboard.html（資料內嵌，樣板在 dashboard_template.html）
├── build_assets.py        # 用 ffmpeg 合成影像題，並把既有音訊研究轉成任務
└── build_taiwan.py        # data/taiwan/items.json（附一手來源）→ 任務檔
tasks/<情境>/<任務>.json   # 20 個任務，所有模型共用
assets/images/             # 合成影像題（標註由程式決定）
data/taiwan/items.json     # 台灣政經題目，每題附來源網址、引文與查證日期
results/
├── capabilities.json      # 各模型 × 模態的探針結果
├── notes.json             # 報告裡手寫的結論與註記
└── runs/<run-id>/         # 每次執行的原始紀錄（records.jsonl、meta.json）
tests/test_bench.py        # 離線單元測試
```

## 怎麼跑

```bash
export OPENROUTER_API_KEY=...   # 33 個模型都經由 OpenRouter
export GEMINI_API_KEY=...       # Gemini 直連

python3 -m bench models                       # 列出模型名冊與金鑰狀態
python3 -m bench tasks                        # 列出任務
python3 -m bench build                        # 重新產生影像素材與音訊任務
python3 -m bench probe                        # 對所有模型探測影像／音訊能力
python3 -m bench run --tasks zh_text,agent --budget 1
python3 -m bench run --models clef-omni,gemini-decision-1 --tasks audio --limit 10
python3 -m bench report                       # 合併 results/runs/* → bench-report.html
python3 -m bench dashboard                    # 合併 results/runs/* → bench-dashboard.html
python3 -m unittest discover -s tests         # 離線測試
```

各項行為說明：

- **音訊任務**需要先下載素材：`scripts/fetch_scenes.py` 下載音場片段，`scripts/build_pron_corpus.py` 產生發音語料。這些音檔不進版控。
- **跳過的任務**：模態探針沒有判定為 `supported` 的任務，會整格跳過、不計分。要硬跑請加 `--force`。
- **快取**：原始回應快取在 `out/bench/cache/`，重跑或重出報告不會重複計費。

## 擴充

- **新增模型**：
  - OpenRouter 上有的模型，在 `bench/providers/openrouter.py` 的 `CATALOG` 加一行即可。
  - 其他廠商請繼承 `Provider`，實作 `build_request` 與 `parse_response`，再登記到 `providers/__init__.py`。
  - 加完後先執行 `probe`。
- **新增任務**：在 `tasks/<情境>/` 放一個 JSON。格式見 `bench/schema.py` 的說明。標註不可取自任何受測模型的輸出。
- **尚未接上的模型**：
  - OpenRouter 上刻意不跑的：抽取型的 `cloudflare/clairic`，以及已退役或改道的舊版（d1、d1.1、d1-ultra、Jev 1.13、Drex v1.5）。
  - 以下四個不在 OpenRouter 上，需要各家的金鑰：
    - GLiDE v1.2（Fastino）
    - SubQ Snap 1.2
    - Celeris-1.1 Decision
    - Mercury Decide（2026-12-28 停止服務）

## 已知限制

- **題組規模小**：每個任務 5–50 題，是種子題組，分數差距在小樣本下不一定顯著。
- **中文文字與 Agent 題組太簡單**：需要換成貼近實際資料的難題。
- **台灣政經的近期數據有時效性**：最低工資、經濟成長率、市值排名等題目，以 `as_of` 日期為準。
- **立場對稱題只有 8 組**：只能當描述性觀察，不能當作偏見的定論。
- **對措辭敏感**：決策模型對選項描述的措辭很敏感。同樣的音場題，類別描述寫短一點，Gemini 就從 32/42 掉到 29/42。
- **模型會更新**：雲端模型的行為可能改變，數字只代表測試當天的狀態。

---

以下是本專案原本針對 `gemini-decision-1` 的深入研究（2026-11-17～19），內容保留不動。

# Gemini Decisions 多模態實測

三個研究，回答同一個問題：**`gemini-decision-1`（Decisions API）在「非文字」的判斷上到底能做什麼、不能做什麼**，並以 `gemini-4-argon` 當對照組。

測試日期：2026-11-17 ｜ 環境：macOS arm64、Python 3（僅標準函式庫）、ffmpeg ｜ 總花費：約 **US$1.0**

> 📊 **互動版報告**：[`report.html`](report.html)（單檔、可離線開、深淺色切換）。
> 由 `python3 scripts/build_report.py` 從 `out/*.json` 直接產生，報告裡的數字與本文同源。

> 🔍 **注音音檔稽核**：[`audit-report.html`](audit-report.html)（flash-lite 全量 2,934 檔的檢查結果）。
> 由 `python3 scripts/build_audit_report.py` 產生。

> 🏢 **Microsoft Decision 1.1 實測**：[`ms-decision-report.html`](ms-decision-report.html)。
> 結論：該端點只吃文字、不支援音訊；文字任務上與 Gemini 同級但請求不穩。
> 「支援音訊嗎」的完整查證（一手文件 + 端點探針）：[`docs/ms-decision-audio-support.md`](docs/ms-decision-audio-support.md)。

---

## 一句話結論

| 任務 | `gemini-decision-1` | `gemini-4-argon` | 該用哪個 |
| --- | --- | --- | --- |
| **單音節辨音**（研究一） | ❌ 無鑑別力 | ✅ 12/12（需多次取樣） | Argon |
| **音場分類 7 類**（研究二） | 🟡 76%（32/42） | ✅ 90%（38/42） | 粗分類可用 Decisions，細分類用 Argon |
| **「有沒有人聲」守門**（研究二） | ✅ 42/42 | ✅ 42/42 | **兩者都可以**，Decisions 快 13 倍、便宜 26 倍 |
| **發音練習判斷**（研究三） | ❌ 逐字抓錯 0/34、誤放 19/30 | 🟡 句子層級準，聲調不行 | 見研究三 |

**最反直覺的一點**：Decisions 在「說話 / 唱歌 / 純音樂 / 噪音」這四類上是 **24/24 全對**，而且只要 500 ms、幾乎零成本。它壞掉的地方非常特定——**「同一個內容、不同場合」的判斷**（演唱會 vs 錄音室）、**人數**（一個人 vs 多個人）、以及**語氣層的音對不對**。這正好對應它「一次前向傳播、給你校準機率」的設計：它能回答「這段音訊屬於哪個語意類型」，但答不出「有幾個人在講」「這個音節的聲調對嗎」。

---

## 目錄

1. [研究一：單音節辨音](#研究一單音節辨音)
2. [研究二：音場分類（YouTube 片段）](#研究二音場分類youtube-片段)
3. [研究三：發音練習能不能靠它](#研究三發音練習能不能靠它)
4. [發音練習 Web App](#發音練習-web-app)
5. [成本總表](#成本總表)
6. [限制](#限制)
7. [如何重跑](#如何重跑)
8. [專案結構](#專案結構)

---

# 研究一：單音節辨音

> 完整版仍在本文後段，這裡只留結論與關鍵數據。

**素材**：14 段音檔，含一組難得的 labeled pair——同一個注音 `ㄌㄨˊ` 的「確定錯」（舊 ElevenLabs 音檔被唸成 `lü`）與「確定對」（重新生成）。

| API／模型 | 判斷單音節發音正確性 | 實測 |
| --- | --- | --- |
| `gemini-decision-1` | **否** | 12 段無鑑別力；正確的「爐」P=0.611，毫不相干的「水」P=0.780；四選一 0/2 |
| `gemini-4-argon` | 是（需多次取樣） | 首輪 12/12；重跑 8/8 對照組、瑕疵 2/2 抓出，但出現 1 次假警報（把 `lu2` 聽成 `lóng`） |
| `gemini-3.8-flash` | 是（小樣本） | 5/5 |
| `gemini-3.1-flash-lite` | 是（小樣本） | 5/5，靜音／噪音正確回 `NONE`（沒有幻聽） |

**判讀**：Decisions 不是「聽錯」，是**它沒在做音素辨識**。它的 `confidence` 看起來很專業，但與正確性無關——這是本專案最重要的一個陷阱：**有校準分數 ≠ 可用於驗收**。

<details>
<summary>研究一原始數據（點開）</summary>

## Decisions：無鑑別力

| 音檔 | 應為 lu2？ | P(lu2) | 四選一最高 |
| --- | --- | --- | --- |
| `ma` | 否 | 0.180 | lü3 |
| `ma3` | 否 | 0.708 | lü2 |
| `da4` | 否 | 0.704 | lü2 |
| `ni3` | 否 | 0.596 | lü3 |
| `shui3` | 否 | 0.780 | lü2 |
| `xue2` | 否 | 0.761 | lü2 |
| `zhong` | 否 | 0.727 | **lu2** |
| `ai4` | 否 | 0.589 | lü2 |
| `old_M_lu2` | 否 | 0.657 | lü2 |
| `new_M_lu2` | **是** | 0.611 | lü2 |
| `old_F_lu2` | 否 | 0.691 | lü2 |
| `new_F_lu2` | **是** | 0.715 | lü2 |

正例平均 0.663、其餘 0.639；`min(P|正)=0.611 < max(P|負)=0.780` → 無法分離。重跑一次結論相同（正例 0.703、其餘 0.597，四選一仍 0/2）。

## Argon 盲測

| 音檔 | 期望 | Argon | 判定 |
| --- | --- | --- | --- |
| `ma` / `ma3` / `da4` / `ni3` / `shui3` / `xue2` / `zhong` / `ai4` | 各自音節 | 全部正確 | ✅ 8/8 |
| `old_M_lu2` | 應被判定為錯 | `ㄌㄩ｜lü｜2` | 🎯 |
| `old_F_lu2` | 應被判定為錯 | `ㄌㄩˇ｜lü｜3` | 🎯 |
| `new_M_lu2` / `new_F_lu2` | `lu2` | `lu2` / 一次誤判 `lóng` | 🟡 1 次假警報 |

音檔來源：[stroke](https://github.com/doggy8088/stroke) 專案的注音音檔（`data/control/`、`data/lu2/`）。

</details>

---

# 研究二：音場分類（YouTube 片段）

## 問題

> 能不能分辨「人聲說話／人聲唱歌／純音樂／環境噪音／演唱會／多人說話」？

這題對語音產品很實際：如果使用者對著麥克風說話，但背景是電視或音樂，系統要先知道「這段到底有沒有人聲、有幾個人在講」，才知道要不要進入發音判斷。

## 素材：7 類 × 6 段 = 42 段

全部從 YouTube 擷取 10 秒片段，`yt-dlp` 只下載需要的時間窗，`ffmpeg` 轉成 24 kHz 單聲道 96 kbps mp3。

| 類別 | 定義 | 來源範例 |
| --- | --- | --- |
| `speech` | 單人說話、無背景音樂 | Steve Jobs 史丹佛演講、TED、有聲書 |
| `singing` | 人聲唱歌（含伴奏或純人聲） | Bohemian Rhapsody、Pentatonix 阿卡貝拉 |
| `music` | 純器樂、無人聲 | Canon in D、lofi、拉赫曼尼諾夫交響曲 |
| `noise` | 環境噪音 | 大雨、高速公路車流、白噪音、工地 |
| `concert` | 演唱會現場（擴音、觀眾、合唱） | Queen Live Aid、Coldplay 現場、BTS fancam |
| `multi_speech` | 多人說話 | 雙主持人 podcast、座談會、雙人訪談 |
| `speech_music` | 人聲說話＋明顯背景音樂 | 電影預告、電視廣告、廣播廣告 |

完整清單與每個片段的影片標題、起點秒數在 [`data/scenes/manifest.json`](data/scenes/manifest.json)。

## 標註怎麼來的（以及我怎麼發現標錯了）

**標註不採用任何 Gemini 模型的輸出**，否則就是循環論證。做法是三層：

1. **來源宣告**：標題／頻道／影片類型決定預期類別（例如「Live Aid 1985 Full Concert」→ `concert`）。
2. **獨立 ASR 驗證**：用 **Groq Whisper large-v3**（不同廠商）逐段轉錄。`music` / `noise` 應該轉不出字；`speech` / `multi_speech` / `speech_music` 應該有清楚的句子。
3. **自動挑窗**：長影片只抓需要的區段，再用「能量穩定度」挑 10 秒窗，避免挑到前奏或空白。

這一步抓出 **6 段標錯**，全部換掉重抓：

| 片段 | 問題 | 處理 |
| --- | --- | --- |
| `sm_sprite` / `sm_nursery` | 原素材其實是「水滴聲」與「兒歌」，不是說話 | 換成真正的人聲＋音樂 |
| `sm_siva`（英語教學 vlog） | Whisper 有字、但**完全沒有背景音樂** → 應該算 `speech` | 換素材 |
| `sm_abelcole`（廣播廣告） | 兩個人對話、**沒有音樂** → 應該算 `multi_speech` | 換素材 |
| `sm_vlog`（生活 vlog） | 該時間窗只有環境音＋一個中文字 | 換素材 |
| `sg_despacito` | 起點 60 秒是間奏，只有 1 個字 | 改到有唱歌的窗 |

換完之後，42 段的 Whisper 結果全部與標註一致（`music`/`noise` 共 12 段轉不出任何句子；`speech`/`multi_speech`/`speech_music` 共 18 段全部有完整句子）。

> ⚠️ `speech_music` 這類有一個本質上的模糊地帶：TED-Ed 那种「旁白＋很輕的配樂」到底算 `speech` 還是 `speech_music`？我的判準是 **背景音樂要明顯到能影響判斷**。三個 TED-Ed 片段因為配樂太輕，兩個模型都判 `speech`——我因此把它們換成配樂明顯的電影片預告與廣告，而不是把模型的答案當成標註。

## 方法

同一段音訊，兩種問法：

**Decisions（`gemini-decision-1`）**：一個請求同時問 8 題——

```jsonc
{
  "model": "gemini-decision-1",
  "input": [{ "type": "audio", "mime_type": "audio/mpeg", "data": "<base64>" }],
  "questions": {
    "scene": { "type": "choice", "instructions": "Which sound scene does this audio clip contain?",
               "criteria": { "speech": "one person talking, no background music", "...": "..." } },
    "is_speech":  { "type": "noul", "instructions": "Does this audio clip contain one person talking...?" },
    "is_singing": { "type": "noul", "instructions": "..." }
    // 共 7 個 noul，每類一個獨立是非題
  }
}
```

跑 2 次確認穩定性。

**Argon（`gemini-4-argon`）**：盲聽，只給音檔與類別定義，要求輸出 JSON（類別、信心、有無人聲、有無音樂、人數）。`thinkingLevel: low`、`temperature: 0`，跑 3 次取多數決。

## 結果

### 總表

| 方法 | 七類正確率 | 有無人聲 | 有無說話 |
| --- | --- | --- | --- |
| Decisions（choice 題） | **32/42（76%）** | **42/42** | 41/42 |
| Decisions（7 個 noul 題取最高） | 28/42（67%） | 42/42 | 39/42 |
| Argon（單次） | **38/42（90%）** | **42/42** | **42/42** |
| Argon（3 次多數決） | 38/42（90%） | 42/42 | 42/42 |

### 分類別召回

| 類別 | Decisions | Argon |
| --- | --- | --- |
| `speech` 單人說話 | **6/6** | **6/6** |
| `singing` 唱歌 | **6/6** | **6/6** |
| `music` 純音樂 | **6/6** | **6/6** |
| `noise` 環境噪音 | **6/6** | **6/6** |
| `concert` 演唱會 | **0/6** ❌ | 5/6 |
| `multi_speech` 多人說話 | 4/6 | 3/6 |
| `speech_music` 說話＋音樂 | 4/6 | **6/6** |

### 混淆矩陣（Decisions）

```text
true\pred      speech  singin   music   noise  concer  multi_  speech   n  recall
---------------------------------------------------------------------------------
speech              6       0       0       0       0       0       0   6  6/6
singing             0       6       0       0       0       0       0   6  6/6
music               0       0       6       0       0       0       0   6  6/6
noise               0       0       0       6       0       0       0   6  6/6
concert             0       6       0       0       0       0       0   6  0/6   ← 全部判成「唱歌」
multi_speech        2       0       0       0       0       4       0   6  4/6
speech_music        0       0       0       0       1       1       4   6  4/6
```

### 混淆矩陣（Argon 多數決）

```text
true\pred      speech  singin   music   noise  concer  multi_  speech   n  recall
---------------------------------------------------------------------------------
speech              6       0       0       0       0       0       0   6  6/6
singing             0       6       0       0       0       0       0   6  6/6
music               0       0       6       0       0       0       0   6  6/6
noise               0       0       0       6       0       0       0   6  6/6
concert             0       1       0       0       5       0       0   6  5/6
multi_speech        3       0       0       0       0       3       0   6  3/6
speech_music        0       0       0       0       0       0       6   6  6/6
```

### 逐段結果

| 類別 | 片段 | Decisions | Argon | 素材 |
| --- | --- | --- | --- | --- |
| concert | co_bohemian_l | singing | **concert** | Bohemian Rhapsody @ Live Aid |
| concert | co_bts | singing | **concert** | BTS Butter @ AMA（含 fanchant） |
| concert | co_coldplay | singing | **concert** | Coldplay 聖保羅現場 |
| concert | co_coldplay2 | singing | **concert** | Coldplay 印度現場 |
| concert | co_dimash | singing | **concert** | Dimash 現場 fancam |
| concert | co_liveaid | singing | singing | Queen Live Aid 全場 |
| multi_speech | ms_causal | multi_speech | multi_speech | 座談會（因果推論） |
| multi_speech | ms_ivehadit | multi_speech | multi_speech | 雙主持人 podcast |
| multi_speech | ms_panel | multi_speech | speech | 座談會 |
| multi_speech | ms_panel2 | speech | speech | 座談會（另一場） |
| multi_speech | ms_twohot | multi_speech | multi_speech | Two Hot Takes podcast |
| multi_speech | ms_twoperson | speech | speech | 雙人訪談 |
| speech_music | sm_abelcole | concert | **speech_music** | 電影預告 Back to Black |
| speech_music | sm_nursery | **speech_music** | **speech_music** | Coca-Cola 30 秒廣告 |
| speech_music | sm_siva | multi_speech | **speech_music** | 電影預告 Heart of the Beast |
| speech_music | sm_spotify | **speech_music** | **speech_music** | Spotify 廣播廣告 |
| speech_music | sm_sprite | **speech_music** | **speech_music** | TED-Ed 起司史（旁白＋配樂） |
| speech_music | sm_vlog | **speech_music** | **speech_music** | Quaker 30 秒廣告 |
| speech | sp_jobs / sp_zoo / sp_ted_* / sp_audiobook | 全對 | 全對 | 演講、有聲書 |
| singing | sg_* （6 段） | 全對 | 全對 | 流行歌、阿卡貝拉 |
| music | mu_* （6 段） | 全對 | 全對 | 古典、lofi、爵士、吉他 |
| noise | no_* （6 段） | 全對 | 全對 | 雨、車流、白噪音、工地、警笛 |

### 穩定性與延遲

| 指標 | Decisions | Argon |
| --- | --- | --- |
| 重跑結果一致 | **42/42** | **42/42** |
| 真實類別平均機率 / 信心 | 0.648 | 0.962 |
| 平均延遲 | **500 ms** | 6 704 ms |
| 每段成本（10 秒音訊＋8 個題目） | 約 US\$0.00009 | 約 US\$0.0025 |

## 判讀

**1. Decisions 的強項比預期好，弱點也很明確。**

四個「內容單純」的類別 24/24 全對，而且只要 500 ms。它失敗的地方有一個共同的結構：

- **演唱會 0/6，全部判成「唱歌」**。模型聽得到「有人在唱歌」，但**沒有用到「現場／觀眾／擴音」的線索**。這不是聽錯，是它的判斷維度裡沒有「場合」。
- **多人說話 4/6**。錯的兩段（`ms_panel2`、`ms_twoperson`）被判成「單人說話」。10 秒窗內常常真的只有一個人在講——**這不完全是模型的錯，是 10 秒窗的設計限制**。
- **說話＋音樂 4/6**。兩段電影片預告被判成 `concert` 與 `multi_speech`：預告片的配樂又大又戲劇化，聽起來真的像現場。

**2. Argon 在「場合」與「說話＋音樂」上明顯較好，但人數同樣不穩。**

Argon 抓到 5/6 演唱會、6/6 說話＋音樂（連很輕的 TED-Ed 配樂都抓得到），但多人說話只有 3/6——和 Decisions 一樣卡在「10 秒內只有一個人在講」。

**3. 最有實務價值的發現：當「守門員」時兩者一樣好。**

如果你的目的只是「**這段音訊裡到底有沒有人聲？要不要進入下一步？**」，兩個模型都是 **42/42**。這時候選 Decisions：快 13 倍、便宜約 26 倍、而且輸出是可直接當門檻用的機率。

**4. 獨立問 7 個是非題，反而比一次 7 選 1 更差**（28 vs 32）。把機率最高的那一類當答案，會被「多個題目同時高分」搞混。要機率就用 `choice`，不要自己用 `noul` 拼。

---

# 研究三：發音練習能不能靠它

## 問題

> 拿一段「小朋友唸句子」的錄音，Decisions API 能不能判斷唸對了沒、正確率多少？

這是 Decisions 官方文件裡明列的用途之一（speech evaluation、spoken words、pacing、vocal tone），所以值得實測，而不是從研究一直接推論。

## 三個先踩到的坑（不是模型的錯，是整合的錯）

在寫 App 的過程中，我做了幾個對照實驗，發現三個會**直接讓判斷失準**的工程問題：

### 坑 1：音檔尾巴被吃掉 → 最後 1–3 個字被判「沒唸」

TTS 唸 `The cat sat on the mat.`（1.24 秒、結尾乾淨、沒有尾靜音）：

| 送出的音訊 | Argon 聽到 | 判定 |
| --- | --- | --- |
| 原檔 | `The cat sat on` | 「the mat」三個字 **missing**，給 65 分 |
| 補 600 ms 尾靜音 | `The cat sat on the mat` | 6/6 全對 |

同一個檔案，Whisper 聽得到完整句子，所以**音檔沒問題，是 Gemini 端對「沒有尾巴靜音」的短音檔會漏掉結尾**。小朋友唸完通常立刻按停止，這個補償在實務上是必要的。App 已經在送出前自動補 0.6 秒（`server.py: prepare_audio`）。

### 坑 2：給了答案，它就會把錯的字「聽成」對的字

同一段「故意唸錯」的音檔（`I like to read hooks.`，把 books 唸成 hooks）：

| 提示方式 | Argon 轉錄 |
| --- | --- |
| 盲聽（不給題目） | `I like to read books` ❌ 自動修正了 |
| 盲聽＋「可能有唸錯，照實寫」 | `I like to read hooks` ✅ |
| 給了目標句＋「可能有唸錯」 | `I like to read hooks` ✅ |
| 給了目標句（原始寫法） | `books`，逐字全部 correct，100 分 ❌ |

也就是說：**模型有很強的「語言先驗」，會把 hooks 補成 books**。這對發音教學是致命的——越像真字的錯誤越容易被吃掉。緩解方式有兩個，App 兩個都做了：

1. 提示裡明確寫「不要自動修正成合理的句子」。
2. **另外跑一支完全不給答案的盲聽**，逐字比對由程式做（`difflib`），不經過模型。

即便如此，盲聽偶爾還是會修正（同一個檔案跑兩次，一次 `hooks`、一次 `books`）。所以 App 把「盲聽結果」單獨顯示，並在兩支不一致時降階成「不確定」的語氣。

### 坑 3：分數會浮動，而且偏寬鬆

- 同一段正確音檔，Argon 給過 65、82、100 三種分數。
- 一個字的聲調錯（`我喜歡吃蘋果` → `蘋鍋`），Decisions 給 **P=0.79、等級 4「正確且自然」**；Argon 給 82 分（有在文字裡指出錯誤，但分數仍然偏高）。

結論：**不要拿單一分數當及格線**。App 的判定順序因此改成「盲聽逐字比對（程式算）優先，模型分數為輔」。

## 基準測試：50 段 TTS 語料

用 macOS `say` 合成 10 個句子 × 4 種變體，外加「正確句＋粉紅噪音（SNR 12 dB）」10 段，共 50 段：

| 變體 | 內容 | 用意 |
| --- | --- | --- |
| `correct` | 正確朗讀 | 應該被接受 |
| `correct_noisy` | 正確朗讀＋背景噪音 | 教室／家裡的真實情況 |
| `tone_error`（中文）／`wrong_word`（英文） | 差一個音或換一個詞 | 應該被抓出 |
| `missing_word` | 漏字 | 應該被抓出 |
| `off_topic` | 唸成完全不同的句子 | 應該被拒絕 |

### 總表

| 指標 | Decisions | Argon |
| --- | --- | --- |
| AUC（正確句 vs 錯誤句） | 0.697 | **0.938** |
| 正確句平均分 | P = 0.687 | 99.1 / 100 |
| 錯誤句平均分 | P = 0.563 | 55.4 / 100 |
| 門檻放行正確句（D: P≥0.5／A: ≥70） | 18/20 | **20/20** |
| 誤放錯誤句 | 19/30 | 18/30 |
| **逐字抓錯**（34 個刻意錯誤的字） | **0/34** | **24/34** |
| 平均延遲 | 552 ms | 9 204 ms |

花費 US$0.3692（150 次呼叫）。

### 各變體平均分

| 變體 | n | Decisions P | Argon 0–100 |
| --- | --- | --- | --- |
| `correct` 正確朗讀 | 10 | 0.690 | **99.1** |
| `correct_noisy` 正確＋背景噪音（SNR 12 dB） | 10 | 0.684 | **99.6** |
| `off_topic` 唸成別句 | 10 | 0.452 | **1.5** |
| `missing_word` 漏字 | 5 | 0.676 | 79.6 |
| `wrong_word` 差一個音／換詞 | 10 | 0.605 | 78.2 |
| `tone_error` 聲調錯（中文） | 5 | 0.591 | 93.4 |

### 判讀

**1. Decisions 幾乎沒有鑑別力，而且錯的方式很一致。**

- 漏字句的平均 P（0.676）和完全正確句（0.690）只差 **0.014**。
- 34 個刻意做錯的字，逐字 choice 題**一個都沒抓到（0/34）**——它的逐字機率是裝飾品。
- 唯一有效的是 `off_topic`（0.452）：它分辨得出「這是完全不同的句子」，但到此為止。
- 它還誤殺了 2 段**完全正確**的句子（`四是四，十是十，十四是十四` P=0.39、加噪音版 0.38），因為那兩句音節密集。所以連「當及格線」都不行：會同時放過錯的、擋掉對的。

**2. Argon 對「是不是同一句話」非常準，對「差一個音」只能算堪用。**

- 正確句 99.1、唸成別句 1.5——**句子層級的鑑別力接近完美**。
- 背景噪音（12 dB SNR 粉紅噪音）**完全沒有影響**：99.6 分，一分都沒掉。
- 差一個音（`hooks`／`hat`／`waiter`）只掉到 78 分，仍在 70 分門檻之上；漏字 79.6。**它抓到了，但分數沒有掉到「不及格」**——這是為什麼不能只看總分。

**3. 最大盲點：中文聲調錯。**

5 段聲調錯（`蘋鍋`／`真豪吃`／`小兔紫`／`死是四`／`媽媽馬馬`）平均 **93.4 分**，5 段裡有 **3 段直接給 100 分**，而且轉錄出來的是**完全正確的句子**——它把聲調錯自動修正掉了。只有 `蘋鍋`（82）與 `媽媽麻馬`（85）被抓到。

> 這與研究一（單音節）的結果一致：**Argon 在「單獨聽一個音節」時聲調判斷是準的（`ma` vs `ma3` 都對），但把它放進句子裡，語言先驗就會蓋過聽覺證據。**

**4. 所以實務上該怎麼用。**

| 想做的事 | 用什麼 |
| --- | --- |
| 判斷「有沒有唸到這句」 | Argon 的盲聽＋逐字比對（或 Argon 總分 ≥ 80） |
| 指出「哪個字不對」 | Argon 的逐字標記（24/34），不要看總分 |
| 判斷「這個字的聲調對不對」 | ❌ 兩個模型都不行，需要另外設計（例如請模型只回報聲調、或逐字單獨送審） |
| 「有沒有人在說話」的守門 | Decisions（42/42，500 ms，幾乎免費） |

### 尾靜音 A/B（同一批正確句）

| 條件 | 平均分 | 結尾異常 |
| --- | --- | --- |
| 補 0.6 秒尾靜音 | **99.1** | 0 / 10 |
| 不補 | 94.0 | 2 / 10（`The cat sat on the mat` 直接少了「the mat」，67 分；`seashore` 被聽成 `shore`，82 分） |

這就是前面「坑 1」的量化版本：**同一個模型、同一批音檔，只差一段尾靜音，就會把「唸對」判成「漏字」**。做發音練習時務必補。

---

# 發音練習 Web App

一個本機執行的小網站：顯示句子 → 網頁直接錄音 → 同時送 Decisions 與 Argon → 顯示回饋 → 記錄下來做研究。

## 啟動

```bash
export GEMINI_API_KEY="你的 key"
python3 app/server.py --port 8899
# 開 http://127.0.0.1:8899
```

需求：Python 3.9+（無需 pip install）、`ffmpeg`（補尾靜音用；沒有也能跑，但會少一層保護）。
麥克風權限：`localhost` 屬於安全來源，不需要 HTTPS。若要給其他裝置用，請自己加 TLS 或走反向代理。

## 畫面

- **句子卡**：英文／中文切換、難度篩選、`🔊 聽示範`（系統 TTS）、中文句子附逐字拼音。
- **錄音**：即時音量表、最長 15 秒、可重錄、可用 `或上傳音檔` 取代麥克風（沒有麥克風也能測）。
- **盲聽卡**：不給答案的聽寫結果＋程式算的逐字比對（正確／音不對／沒聽到／多唸）。
- **Decisions 卡**：P(唸對)、5 級分佈、逐字機率、延遲與成本。
- **Argon 卡**：0–100 分、它聽到的句子、逐字診斷與修正建議。
- **一致性**：Decisions↔盲聽、Argon↔盲聽 的逐字一致率。
- **回饋**：三個模型各給「準／部分／不準」、小朋友反應（😀／😐／😣）、自由備註。
- **研究紀錄**：最近的紀錄表、`匯出 CSV`、`?record=last` 可重看任一筆結果。

## 每次判斷會發生什麼

```text
錄音 (webm/opus)
   ↓ ffmpeg 轉 mp3 + 補 0.6 秒尾靜音
   ├─→ Decisions API     一個請求：1 個 noul + 1 個 5 級 score + 每字 1 個 choice（≤12 字）
   ├─→ Argon 盲聽        不給答案，只聽寫 → 程式用 difflib 逐字比對
   └─→ Argon 評分        給答案，要求逐字診斷 + 修正建議（明確禁止自動修正）
   ↓
三份結果一起回傳，前端並排顯示
```

三個呼叫平行送出，實際等待約 **8–12 秒**（Decisions 0.6 秒就好了，等的是 Argon），每次約 **US$0.0065**。

## 資料怎麼存（研究用）

```text
app/data/
├── recordings/<record_id>.webm   # 原始錄音，完全不改動
├── records.jsonl                 # 每筆判斷的完整原始回應（含 usage、延遲、逐字機率）
├── feedback.jsonl                # 人工回饋（哪個模型準、小朋友反應、備註）
└── cost.json                     # 累計花費
```

- 一筆 record 與一筆 feedback 用 `record_id` 對應，**append-only**，不會覆蓋。
- `/api/export` 匯出 CSV：句子、兩個模型的分數、抓錯的字、回饋，可直接丟進 Excel／pandas。
- 只有**音訊**會送到 Gemini API；紀錄與回饋都留在本機。

## 給小朋友用之前要知道的事

1. **它會出錯，而且錯得很有自信**。把它當「第二位聽眾」，不是裁判。
2. **看「哪個字被標記」，不要只看總分**。總分會浮動，被標記的字通常是真的。
3. **孩子唸完不要馬上按停止**（或依賴 App 的自動補靜音），結尾的字最容易被吃掉。
4. **背景有電視或音樂時，先確認它有沒有把環境音當成人聲**——用盲聽卡看它聽到什麼最直接。

---

# 成本總表

| 項目 | 呼叫次數 | 花費 |
| --- | --- | --- |
| 研究一（單音節，既有） | 約 50 | 約 US$0.15（估） |
| 研究二（音場，最終資料集） | 210 | **US$0.32** |
| 研究二（換素材與重跑的成本） | 約 60 | 約 US$0.10 |
| 研究三（TTS 基準 50 段 × 3 支） | 約 180 | 約 US$0.40 |
| App 手動測試 | 約 15 | 約 US$0.10 |
| **合計** | 約 500 | **約 US$1.0** |

預算 US$5 **沒有用完**（約 24%）。成本結構很清楚：**Argon 佔 97.5%**（研究二實測：Argon US$0.3103／126 次、Decisions US$0.0078／84 次），Decisions 幾乎免費。

單價參考（2026-11 官方牌價，Argon 為 2026-11-30 前促銷價）：

| 模型 | 文字輸入 | 音訊輸入 | 輸出 | 10 秒音訊一次呼叫 |
| --- | --- | --- | --- | --- |
| `gemini-decision-1` | \$0.10／1M | \$0.10／1M | \$0（無輸出 token） | 約 US\$0.00009 |
| `gemini-4-argon` | \$2／1M | \$2／1M | \$10／1M | 約 US\$0.0025 |

---

# 限制

- **樣本小**：音場每類只有 6 段、共 42 段；發音基準是 TTS 合成，不是真人小孩。足以看出方向（Decisions 在演唱會 0/6 不是抽樣誤差），但不足以給出可信的準確率區間。
- **10 秒窗的限制**：`multi_speech` 的低分有一部分是「10 秒內真的只有一個人在講」，不是模型不會分。要測人數偵測，需要更長的窗或 diarization 標註。
- **`speech_music` 的邊界是主觀的**：背景音樂「多大聲才算」沒有客觀標準。本文用「明顯到會影響判斷」當判準，並換掉三個配樂太輕的片段。
- **TTS 太乾淨**：合成語音沒有真實的吞音、氣音、教室回音。真人小孩的表現一定更差，實務門檻要自己校準。
- **沒有真人小孩的資料**：App 已備好錄音、盲聽、回饋、匯出的完整流程，但本次沒有實際收集兒童錄音。這是下一步。
- **模型會改版**：本文結果綁定 2026-11-17 的模型版本與價格。
- **音場素材來自 YouTube**：僅供研究評估，未取得任何授權；重跑時片段可能已被下架（`manifest.json` 有完整出處）。

---

# 如何重跑

```bash
export GEMINI_API_KEY="..."
export GROQ_API_KEY="..."        # 選用：片段標註的獨立驗證

./scripts/run_all.sh             # 全部（研究一 + 二 + 三）
./scripts/run_all.sh --fast      # 減少重複次數，快速看趨勢
```

個別執行：

```bash
# 研究二
python3 scripts/fetch_scenes.py --jobs 5              # 下載 42 段（已存在會跳過）
python3 scripts/validate_clips.py                     # Whisper 獨立驗證標註
python3 scripts/scene_bench.py --decisions-runs 2 --argon-runs 3 --budget 5
python3 scripts/probe_windows.py sm_vlog --patch      # 某段挑不到人聲時，重新找時間窗

# 研究三
python3 scripts/build_pron_corpus.py                  # 用 say 合成 50 段語料
python3 scripts/pron_baseline.py --ab-pad             # 跑基準＋尾靜音 A/B

# App
python3 app/server.py --port 8899
```

結果都在 `out/`（已列入 `.gitignore`）：`scene-results.json`、`scene-summary.md`、`pron-baseline.json`、`pron-summary.md`、`clip-validation.json`。

---

# 專案結構

```text
gemini-decisions-1-tests/
├── README.md
├── data/
│   ├── labels.json              # 研究一：14 段單音節標註
│   ├── control/ lu2/ negative/  # 研究一：音檔
│   ├── scenes.json              # 研究二：素材清單（影片 id、類別、起點）
│   ├── scenes/
│   │   ├── manifest.json        # 下載結果：標題、起點、能量特徵
│   │   └── <類別>/<id>.mp3      # 42 段 10 秒片段（gitignored）
│   └── pron/
│       ├── variants.json        # 研究三：句子與刻意錯誤
│       ├── manifest.json        # 合成結果與 gold label
│       └── *.mp3                # 50 段 TTS 語料（gitignored）
├── scripts/
│   ├── common.py                # 研究一：API 呼叫、標註
│   ├── decisions_test.py        # 研究一：Decisions
│   ├── argon_test.py            # 研究一：Argon
│   ├── flash_test.py            # 研究一：flash / flash-lite
│   ├── fetch_scenes.py          # 研究二：下載 + 挑窗 + 切段
│   ├── validate_clips.py        # 研究二：Whisper 獨立驗證
│   ├── probe_windows.py         # 研究二：重新找有語音的時間窗
│   ├── scene_bench.py           # 研究二：基準測試與指標
│   ├── build_pron_corpus.py     # 研究三：TTS 語料
│   ├── pron_baseline.py         # 研究三：基準測試與指標
│   └── run_all.sh
├── app/
│   ├── server.py                # Web App 後端（標準函式庫）
│   ├── assess.py                # 三支判斷與盲聽比對
│   ├── gemini.py                # API 用戶端與成本估算
│   ├── sentences.json           # 題庫（中英各 10 句）
│   ├── static/                  # 前端（無框架）
│   └── data/                    # 錄音、紀錄、回饋（gitignored）
└── out/                         # 執行結果（gitignored）
```

---

# 相關連結

- [Gemini Decisions API 發布公告](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/)
- [Decisions API 文件（noul／choice／score、音訊輸入）](https://aistudio.google.com/docs/decisions-api)
- [Gemini Decision 1 模型卡](https://aistudio.google.com/docs/models/gemini-decision-1)
- [Gemini 4 Argon 發布公告](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-4-argon/)
- [Gemini Developer API 定價](https://ai.google.dev/gemini-api/docs/pricing)
- [Groq Whisper large-v3（獨立驗證用）](https://console.groq.com/docs/speech-to-text)
- [stroke 專案（研究一音檔來源）](https://github.com/doggy8088/stroke)
