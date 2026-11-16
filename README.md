# Gemini Decisions 1 辨音測試

驗證 **Gemini Decisions API（`gemini-decision-1`）能不能判斷國語單音節的發音正確性**，並以 `gemini-4-argon`、`gemini-3.8-flash`、`gemini-3.1-flash-lite` 作為對照。

測試日期：2026-11-17 ｜ 環境：macOS（arm64）、Python 3（僅標準函式庫）｜ 樣本：14 段音檔

---

## 一句話結論

**Decisions API 不適合這個任務**；同一個任務交給 `gemini-4-argon` 或便宜的 `gemini-3.1-flash-lite` 都做得很好——但要用多次取樣投票，單次呼叫會誤判。

| API／模型 | 能否判斷單音節發音正確性 | 實測結果 |
| --- | --- | --- |
| `gemini-decision-1`（Decisions API） | **否** | 12 段無鑑別力；正確的 `lu2` 拿到 P=0.611，毫不相干的「水」卻拿到 P=0.780；四選一 0/2 命中 |
| `gemini-4-argon` | **是**（需多次取樣） | 首輪 12/12；重跑對照組 8/8、瑕疵 2/2 全抓出，但正確檔出現 1 次誤判（`lóng`） |
| `gemini-3.8-flash` | 是（小樣本） | 5/5，含新舊 `lu2` 的 `lü`／`lu` 區辨 |
| `gemini-3.1-flash-lite` | 是（小樣本） | 5/5，負向控制（靜音／噪音）正確回 `NONE` |

---

## 背景：為什麼會有這組測試資料

來源是 [stroke](https://github.com/doggy8088/stroke)（國小生字筆順練習 PWA）的一個真實缺陷：

1. 「爐」的注音是 `ㄌㄨˊ`（`lu2`），音檔 `M/lu2.mp3`、`F/lu2.mp3` 由 13 個 ㄌㄨˊ 的字共用。
2. 使用者反映發音錯誤。本次測試中，模型盲聽舊檔得到 **`lü2`／`lü3`**，也就是被唸成「驢」而不是「爐」。
3. 舊檔已用 **ElevenLabs `eleven_v4`** 重新生成（男聲 Will 保哥、女聲 Vivian），使用者確認新發音正確。

於是得到一組難得的 **labeled pair**：同一個注音、一個確定錯、一個確定對。這正是判斷「API 到底聽不聽得出來」最直接的素材。

> 音檔是**按注音共用**的，不是逐字；全站 2,934 個音檔只對應 1,468 個音節。

---

## 測試資料

`data/labels.json` 是唯一的標註來源。

### 對照組（假設既有音檔正確）

| id | 期望 | 用途 |
| --- | --- | --- |
| `ma` | ㄇㄚ（ma1） | 一聲基準 |
| `ma3` | ㄇㄚˇ（ma3） | 與 `ma` 同音段、不同調，專門檢驗分調能力 |
| `da4` | ㄉㄚˋ（da4） | 四聲 |
| `ni3` | ㄋㄧˇ（ni3） | 聲母 ㄋ（與 ㄌ 易混） |
| `shui3` | ㄕㄨㄟˇ（shui3） | 複韻母 |
| `xue2` | ㄒㄩㄝˊ（xue2） | 撮口呼 ＋ 二聲 |
| `zhong` | ㄓㄨㄥ（zhong1） | 舌尖後音 ＋ 鼻音韻尾 |
| `ai4` | ㄞˋ（ai4） | 無聲母、四聲 |

### 目標組（已知對錯）

| id | 期望 | 判定 |
| --- | --- | --- |
| `old_M_lu2` | ㄌㄨˊ | 瑕疵（使用者判定錯） |
| `new_M_lu2` | ㄌㄨˊ | 正確 |
| `old_F_lu2` | ㄌㄨˊ | 瑕疵（使用者判定錯） |
| `new_F_lu2` | ㄌㄨˊ | 正確 |

### 負向控制（不含語音）

| id | 內容 |
| --- | --- |
| `silence` | 1 秒純靜音 |
| `noise` | 1 秒粉紅噪音（振幅 0.02） |

---

## 測試方法

所有請求都是 `temperature: 0`，每個音檔一次請求。

### 1. Decisions API（`gemini-decision-1`）

`POST /v1beta/decisions`，一個音訊 input ＋ 兩個獨立題目：

```jsonc
{
  "model": "gemini-decision-1",
  "input": [{ "type": "audio", "mime_type": "audio/mpeg", "data": "<base64>" }],
  "questions": {
    "is_lu2": { "type": "noul", "instructions": "Is the spoken Mandarin syllable ㄌㄨˊ (lu, second tone)?" },
    "which":  { "type": "choice", "instructions": "Which Mandarin syllable is spoken?",
                "criteria": {
                  "lu2":   "ㄌㄨˊ / lu, second tone",
                  "lv2":   "ㄌㄩˊ / lü, second tone",
                  "lv3":   "ㄌㄩˇ / lü, third tone",
                  "other": "any other syllable"
                } }
  }
}
```

實作上有兩個坑（都已寫進 `scripts/common.py`）：

- 音訊必須用**扁平結構** `{"type","mime_type","data"}`。嘗試 `inline_data`、`inlineData`、`content` 都會回 `Unknown parameter`。
- `choice` 題的選項是 **`criteria` 對照表（id → 說明）**，不是 `options` 陣列；用 `options` 會被拒。

### 2. Argon 盲測（`gemini-4-argon`）

只給音檔，不洩漏答案，要求輸出 `注音|漢語拼音|聲調`，`thinkingLevel: low`。

### 3. 低成本模型（`gemini-3.8-flash`、`gemini-3.1-flash-lite`）

- 第一階段：注音格式提示，跑 5 段（`ma`、`ma3`、新舊 `lu2`）。
- 第二階段：拼音＋`NONE` 提示，跑靜音、噪音、新舊 `lu2`，檢驗會不會幻聽。

---

## 測試結果

### 1. Argon：首輪 12/12，重跑出現 1 次誤判

| 音檔 | 期望 | Argon 輸出 | 判定 |
| --- | --- | --- | --- |
| `ma` | ㄇㄚ | `ㄇㄚ\|ma\|1` | ✅ |
| `ma3` | ㄇㄚˇ | `ㄇㄚˇ\|ma\|3` | ✅ |
| `da4` | ㄉㄚˋ | `ㄉㄚˋ\|da\|4` | ✅ |
| `ni3` | ㄋㄧˇ | `ㄋㄧˇ\|ni3\|3` | ✅ |
| `shui3` | ㄕㄨㄟˇ | `ㄕㄨㄟˇ\|shui\|3` | ✅ |
| `xue2` | ㄒㄩㄝˊ | `ㄒㄩㄝˊ\|xue2\|2` | ✅ |
| `zhong` | ㄓㄨㄥ | `ㄓㄨㄥ\|zhong\|1` | ✅ |
| `ai4` | ㄞˋ | `ㄞ\|ai\|4` | ✅ |
| `old_M_lu2` | ㄌㄨˊ（錯檔） | **`ㄌㄩ\|lü\|2`** | 🎯 抓到錯音 |
| `new_M_lu2` | ㄌㄨˊ（對） | `ㄌㄨˊ\|lu\|2` | ✅ |
| `old_F_lu2` | ㄌㄨˊ（錯檔） | **`ㄌㄩˇ\|lü\|3`** | 🎯 抓到錯音 |
| `new_F_lu2` | ㄌㄨˊ（對） | `ㄌㄨˊ\|lu\|2` | ✅ |

兩個關鍵觀察：

- **它是自己聽出來的**，不是我提示的。舊檔被聽成 `lü`（驢），正好對應使用者的抱怨；新檔被聽成 `lu`（爐）。
- `ma`（一聲）與 `ma3`（三聲）同音段不同調，兩者都答對，說明它真的在判聲調，不是猜的。

`ai4.mp3` 的注音欄少了調號（`ㄞ` 而非 `ㄞˋ`），但第三欄聲調仍是 `4`，所以判為正確——實務上解析要同時接受調號與數字兩種表示。

#### 重跑驗證（Run B）：出現 1 次誤判

同一份資料、同一個提示、同樣 `temperature: 0`，再跑一次得到不同的結果：

| 音檔 | 期望 | Run A | Run B | 判定 |
| --- | --- | --- | --- | --- |
| 8 段對照組 | 各自音節 | 全對 | 全對 | 穩定 |
| `old_M_lu2` | 應被判定為錯 | `lü2` ✅ | `ㄌㄩˊ\|lü2\|2` ✅ | 瑕疵穩定被抓出 |
| `old_F_lu2` | 應被判定為錯 | `lü3` ✅ | `ㄌㄩˇ\|lǚ\|3` ✅ | 瑕疵穩定被抓出 |
| `new_M_lu2` | 應為 `lu2` | `lu2` ✅ | `ㄌㄨ\|lu\|2` ✅ | 穩定 |
| `new_F_lu2` | 應為 `lu2` | `lu2` ✅ | **`ㄌㄨㄥˊ\|lóng\|2`** ❌ | **誤判（假警報）** |

Run B 的統計：對照組 8/8、瑕疵召回 2/2、但正確檔出現 **1/2 假警報**。

這個結果很重要，因為它推翻了「單次呼叫就能當驗收」的想法：

- **召回率看起來很好**：真正的瑕疵（`lü`）兩輪都被抓出來，而且模型每次講的韻母都不同、卻都不是 `lu`。
- **精確率有問題**：正確的 `new_F_lu2` 這次被聽成 `lóng`（龍）。生成式模型的輸出不是決定性的，單次結果不能當定論。

實務上的做法是**多次取樣投票**：同一個檔案跑 2–3 次，只有當多數結果都指向同一個「非期望音節」時才標記為可疑。真瑕疵通常會重複出現，偶發誤判則不會。

### 2. Decisions API：無鑑別力

| 音檔 | 應為 lu2？ | P(lu2) | 四選一最高 | 四項機率 |
| --- | --- | --- | --- | --- |
| `ma` | 否 | 0.180 | lü3 | lü3=0.34 lü2=0.27 other=0.26 lu2=0.13 |
| `ma3` | 否 | 0.708 | lü2 | lü2=0.40 lü3=0.31 lu2=0.20 other=0.09 |
| `da4` | 否 | 0.704 | lü2 | lü2=0.40 lü3=0.27 lu2=0.22 other=0.10 |
| `ni3` | 否 | 0.596 | lü3 | lü3=0.42 lü2=0.40 lu2=0.10 other=0.08 |
| `shui3` | 否 | 0.780 | lü2 | lü2=0.52 lü3=0.31 lu2=0.10 other=0.08 |
| `xue2` | 否 | 0.761 | lü2 | lü2=0.54 lü3=0.32 lu2=0.10 other=0.04 |
| `zhong` | 否 | 0.727 | **lu2** | lu2=0.34 lü2=0.33 lü3=0.22 other=0.12 |
| `ai4` | 否 | 0.589 | lü2 | lü2=0.42 lü3=0.27 lu2=0.19 other=0.12 |
| `old_M_lu2` | 否 | 0.657 | lü2 | lü2=0.42 lü3=0.25 lu2=0.22 other=0.11 |
| `new_M_lu2` | **是** | 0.611 | lü2 | lü2=0.40 lu2=0.31 lü3=0.22 other=0.07 |
| `old_F_lu2` | 否 | 0.691 | lü2 | lü2=0.55 lü3=0.27 lu2=0.12 other=0.05 |
| `new_F_lu2` | **是** | 0.715 | lü2 | lü2=0.38 lu2=0.31 lü3=0.27 other=0.05 |

摘要：

- 應為 `lu2` 的 2 段：P 平均 **0.663**；其餘 10 段：P 平均 **0.639** → 幾乎沒有差距。
- `min(P | 正) = 0.611` 低於 `max(P | 負) = 0.780` → **無法分離**。
- 四選一命中 `lu2`：**0/2**；模型幾乎一律選 `lü2`，連「水」「學」都選 `lü2`。

最刺眼的一組對照：**正確的「爐」P=0.611，而毫不想干的「水」P=0.780**。若拿這個分數做驗收門檻，會同時誤殺正確檔、放過錯誤檔。

每次請求的用量約 124 tokens（文字 99 ＋ 音訊 25），與官方「音訊 25 tokens/秒」一致。

#### 重跑驗證與穩定度

同一份資料重跑一次（Run B），結論不變，但數值會浮動——即使 `temperature: 0`，`gemini-decision-1` 的機率**並不是決定性的**：

| 音檔 | Run A P(lu2) | Run B P(lu2) |
| --- | --- | --- |
| `new_M_lu2`（應為是） | 0.611 | 0.692 |
| `new_F_lu2`（應為是） | 0.715 | 0.715 |
| `shui3`（應為否） | 0.780 | 0.731 |
| `ma`（應為否） | 0.180 | 0.141 |

Run B 摘要：正例平均 **0.703**、其餘 12 段平均 **0.597**；`min(P | 正) = 0.692` 仍低於 `max(P | 負) = 0.761`，四選一仍是 **0/2**。結論一致，差距依舊不存在。

Run B 另外補測了負向控制：**靜音 P=0.381、噪音 P=0.459**。它同樣沒能辨識出「這段沒有語音」，再次說明它並沒有在做音素層的判斷。

### 3. 低成本模型：可用

第一階段（注音格式，盲測）：

| 音檔 | 期望 | `gemini-3.8-flash` | `gemini-3.1-flash-lite` |
| --- | --- | --- | --- |
| `ma3` | ㄇㄚˇ | `ㄇㄚˇ\|mǎ\|3` ✅ | `馬\|ma\|3` ✅（以漢字作答，聲調正確） |
| `ma` | ㄇㄚ | `ㄇㄚ\|ma\|1` ✅ | `媽\|ma\|1` ✅ |
| `old_M_lu2` | 應為 lü（錯音） | `ㄌㄩˊ\|lü\|2` 🎯 | `ㄌㄩ\|lü\|2` 🎯 |
| `new_M_lu2` | 應為 lu2 | `ㄌㄨˊ\|lu\|2` ✅ | `ㄌㄨˊ\|lú\|2` ✅ |
| `new_F_lu2` | 應為 lu2 | `ㄌㄨˊ\|lu\|2` ✅ | `ㄌㄨˊ\|lú\|2` ✅ |

第二階段（拼音＋`NONE`）：

| 音檔 | 期望 | `gemini-3.1-flash-lite` |
| --- | --- | --- |
| `silence` | NONE | `NONE` ✅ |
| `noise` | NONE | `NONE` ✅ |
| `old_M_lu2` | lü2 | `lü2` 🎯 |
| `new_M_lu2` | lu2 | `lu2` ✅ |

**沒有幻聽**：靜音與噪音都老實回 `NONE`，而兩個 lu2 檔仍正確區辨 `lü2`／`lu2`。這是能不能拿來做全量自動驗收的關鍵——否則每個檔案都會被「聽」出一個音節，驗收就失去意義。

用純拼音提示（`lu2` 這種格式）最穩定、最好解析；注音提示偶爾會混出漢字（`馬`、`媽`），解析器要能接受兩種形式。

---

## 判讀：為什麼一個行、一個不行

**Decisions API 不是聽錯，是它沒在做音素辨識。** 它的設計是「一次前向傳播，對一批是非／選項／評分題給出校準機率」，服務對象是路由、政策檢查、內容分級這類**語意層**的判斷。官方說明也寫得很清楚：它評估 spoken words、pacing、vocal tone，用於 call triage、QA、speech evaluation——是「這段話在講什麼、語氣如何」，不是「這個韻母是 u 還是 ü」。150–250ms 的低延遲與零輸出 token 的成本優勢，正是犧牲細粒度語音判別換來的。

**Argon 之所以行**，是因為它把音訊當成模型輸入的一般模態，用生成方式描述聽到的內容（等於做了一次帶聲調標記的辨識），推理鏈可以真正比較韻母與調型。它甚至能指出「這是 lü 不是 lu」，這已經超出單純轉寫。

但它也不是完美的驗收器：重跑時同一個正確檔被聽成 `lóng`。真正的瑕疵（`lü`）兩輪都穩定被抓出，所以「用多次取樣投票、只把重複出現的異常交給人工」是可行策略；「單次呼叫即定論」則不行。

另外要注意一個**容易誤判的陷阱**：Decisions 的輸出有 `confidence`，看起來很專業，但本次實測中它與正確性無關（`水` 的 0.78 比 `爐` 的 0.61 還高）。**有校準分數 ≠ 可用於驗收**。

---

## 成本估算（若要做全量驗收）

以 stroke 專案現況估算：2,934 個音檔，每個約 1 秒（≈25 audio tokens），提示約 90 tokens。

| 模型 | 單價（per 1M tokens） | 全量一次 | 備註 |
| --- | --- | --- | --- |
| `gemini-3.1-flash-lite` | 文字 $0.25 / 音訊 $0.50 / 輸出 $1.50 | **約 US$0.15** | 實測可辨 lü／lu，首選 |
| `gemini-3.8-flash` | 文字 $0.75 / 音訊 $3.00 / 輸出 $3.75（2026 年底前促銷） | 約 US$0.53 | |
| `gemini-4-argon` | $4 / $4 / $20（2026-11-30 前 $2 / $2 / $10） | 約 US$8（促銷期約 US$4） | thinking token 以輸出計價，是主要成本 |
| `gemini-decision-1` | 輸入 $0.10，輸出 $0 | 約 US$0.04 | **但不準，別用** |

粗估延遲：flash-lite 約 1–2 秒／檔，併發 10 大約 10 分鐘跑完全量；Argon 實測約 25 秒／檔，同併發需約 2 小時。Batch API 可再半價。

---

## 如何重跑

需求：Python 3.9+（僅標準函式庫，無需 pip install）、`ffmpeg`（僅重建負向控制音檔時需要）。

```bash
export GEMINI_API_KEY="你的 API key"

# 全部依序跑
./scripts/run_all.sh

# 或個別執行
python3 scripts/decisions_test.py     # Decisions API，14 段（含負向控制）
python3 scripts/argon_test.py         # Argon 盲測，12 段
python3 scripts/flash_test.py         # flash / flash-lite，兩階段
python3 scripts/flash_test.py --model gemini-3.8-flash
```

結果會寫到 `out/*.json`（已列入 `.gitignore`）。

重新產生負向控制音檔：

```bash
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 1.0 -c:a libmp3lame -b:a 128k data/negative/silence.mp3
ffmpeg -f lavfi -i "anoisesrc=d=1:c=pink:r=44100:a=0.02" -c:a libmp3lame -b:a 128k data/negative/noise.mp3
```

---

## 專案結構

```text
gemini-decisions-1-tests/
├── README.md
├── data/
│   ├── labels.json          # 唯一標註來源（期望、分類、判定）
│   ├── control/             # 8 段對照組
│   ├── lu2/                 # 新舊 lu2（labeled pair）
│   └── negative/            # 靜音、噪音
├── scripts/
│   ├── common.py            # API 呼叫、標註載入、去調號比對
│   ├── decisions_test.py    # 主要測試：gemini-decision-1（14 段）
│   ├── argon_test.py        # 對照：gemini-4-argon
│   ├── flash_test.py        # 對照：flash / flash-lite
│   └── run_all.sh
└── out/                     # 執行結果（gitignored）
```

---

## 已知限制

- **樣本很小**：14 段，其中「已知對錯」只有 4 段。這足以證偽 Decisions（它連這麼簡單的案例都分不出來），但不足以證明 Argon 在 1,468 個音節上的準確率。
- **對照組的假設**：8 段對照音檔僅假設既有資料正確，並未逐檔人工複核；只有 `lu2` 是使用者明確確認的。
- **未覆蓋難分組合**：ㄋ／ㄌ、ㄓ／ㄗ、ㄣ／ㄥ、二聲／三聲的系統性混淆沒有足夠樣本，建議正式導入前先抽 100–200 段量測偽陰性率。
- **只驗音素與聲調，不驗自然度**：機械感、尾音、音量突兀等問題，模型無法判斷，仍需人工。
- **輸出格式需正規化**：注音／拼音／漢字混用，調號與數字並存；`scripts/argon_test.py` 的解析邏輯可直接參考。
- **模型會改版、輸出也會浮動**：本文結果綁定 2026-11-17 的模型版本與價格；`gemini-decision-1`
  在 `temperature: 0` 下重跑仍有 0.03–0.08 的機率漂移，其他模型也可能些微不同。
- **單次結果不可信**：`gemini-4-argon` 重跑出現 1 次假警報（正確檔被聽成 `lóng`）。若要正式導入，必須做 2–3 次取樣投票，並接受一定的人工複核比例。
- **未測試的技巧**：Batch API、多輪投票的具體門檻、以 `previousText` 提供上下文來提升穩定度，都還沒驗證。

---

## 相關連結

- [Gemini Decisions API 發布公告](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/)
- [Decisions API 文件（noul／choice／score、音訊輸入）](https://aistudio.google.com/docs/decisions-api)
- [Gemini Decision 1 模型卡](https://aistudio.google.com/docs/models/gemini-decision-1)
- [Gemini 4 Argon 發布公告](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-4-argon/)
- [Gemini 4 Argon 模型規格（音訊輸入上限、範例）](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-argon)
- [Gemini Developer API 定價（含音訊 25 tokens/秒）](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini 3.8 Flash 更新與促銷價](https://aistudio.google.com/docs/whats-new-gemini-3.8)
- [stroke 專案（音檔來源）](https://github.com/doggy8088/stroke)

---

## 音檔來源

`data/control/*` 取自 stroke 專案的 `public/M/`；`data/lu2/*` 取自該專案 `lu2.mp3` 的修改前後版本（舊檔為原始資料，新檔由 ElevenLabs `eleven_v4` 重新生成）。
