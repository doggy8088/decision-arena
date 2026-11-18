# Microsoft-Decision-1.1 支援音訊輸入嗎？

**結論：不支援。** `Microsoft-Decision-1.1` 的 `state` 只接受 **文字、JSON、以及（透過 `assets` 引用的）圖片** 三種模態，官方文件與第三方基準皆未列出音訊；我們對實際端點的四個探針也證實它對音訊欄位「不報錯、但只是當成純文字 tokenize」，等於沒有音訊解碼器。

查證日期：2026-11-17（來源頁面最後更新 2026-10-07）
查證方式：一手文件（Microsoft Learn、Microsoft Foundry 部落格）+ 第三方基準（Artificial Analysis）+ 對 `services.ai.azure.com` 端點的實測

---

## 1. 一手證據

| 來源 | 關鍵敘述 | 判定 |
|---|---|---|
| Microsoft Learn《Deploy and use Microsoft-Decision-1.1》 | 「The state can be **text or JSON** and can reference uploaded **images** supplied in `assets`.」 | 只列三種 |
| 同上（產品定位段） | 「It makes a focused judgment about **text, JSON, or images** and returns a typed, numerical decision.」 | 明確排除音訊 |
| Microsoft Foundry 部落格（GA 公告） | 多模態等同 **images**：影像走 `assets`，`{"type":"image","format":"png","data_base64":...}`，尺寸 280–1,568 px，單題最多 8 個影像引用 | 多模態 ≠ 音訊 |
| Artificial Analysis 模型頁 | 「The model supports **text input** and has a **33k tokens** context window.」 | 輸入模態僅文字 |

補充（同一批來源的效能／價格側寫，供對照用）：Decision Index 68（中位數 66）、每題 123 ms（中位數 206 ms）、輸入 US$0.042 / 1M tokens、每 100 萬題約 US$140。這些數字與本 repo 的 `out/ms-decision-report.md` 量到的延遲（成功呼叫中位數 961 ms）不同層級——對方量的是自家代管環境的推論時間，我們量的是含網路往返的端到端時間，兩者不可直接互比。

## 2. 我們自己對端點的實測（反證）

實測端點：`POST https://<resource>.services.ai.azure.com/providers/microsoft/v1/systemone`，body 為 `{"model":..., "state":..., "questions":...}`。

| 探針 | 送出的內容 | 結果 | 說明 |
|---|---|---|---|
| A | `{"type":"audio","mime_type":"audio/mpeg","data":"hello world"}` | 正常回應，`input_tokens: 51` | `data` 根本不是合法 base64 也不報錯 → 沒有解碼，只當字串算 token |
| B | `{"type":"zzz"}`（完全不存在的型別） | 被接受並回應 | `state` 是寬鬆 JSON，未知結構不會驗證 |
| C | 0.4 秒 / 4 KB 音檔 → 1.0 秒 / 19 KB 音檔 | token 由 3,363 成長到 13,880 | token 數隨 base64 字元數線性成長，符合「純文字」模型 |
| D | 10 秒 161 KB（base64）音檔 | HTTP 413 `question_context_limit`，`processed_input_tokens: 110,045` | 撞的是 33k 上下文上限，不是音訊格式錯誤 |

四個探針一致指向同一件事：**端點沒有音訊通道**，音訊位元組只會被當成一大段文字塞進 33k 的上下文窗口，然後撞牆。這也是為什麼「送進去有回應」很容易被誤讀成「支援音訊」——真正的音訊模型會回 `400 invalid mime type` 或 `unsupported modality`，這裡不會。

## 3. 對本專案的影響

原本的計畫是拿 MS 當第二個裁判，和 `gemini-decision-1` 對照三份音訊研究（單音節辨音、42 段音場分類、50 段發音評測）。由於音訊不可行，這三項**都沒有**跑 MS 分支，改為在純文字任務上對照（`scripts/ms_bench.py`，結果見 `out/ms-bench.json` 與 `out/ms-decision-report.md`）：

- Task A：朗讀轉錄稿分類，MS 14/37（37.8%）vs Gemini 17/42（40.5%），一致率 89.2%
- Task B：情緒判讀 AUC，兩者皆 1.0（MS 機率更銳利：0.957 / 0.327 / 0.001）
- Task C：垃圾訊息判定，MS 19/19（但 29 次呼叫失敗 5 次），Gemini 24/24
- 操作特性：首次成功率 27.6%（8/29），失敗型態全為 `SSL: UNEXPECTED_EOF_WHILE_READING`；成功呼叫延遲中位數 961 ms vs Gemini 442 ms

## 4. 尚未確認的部分

- 官方沒有寫「**不支援**音訊」這種否定句，只有正面列舉（text / JSON / images）。因此本結論是「正面列舉 + 端點行為 + 第三方基準」三方一致的推論，而非逐字引文。
- 微軟的 `microsoft-decision-1.1` 底層是 Gemma 4 26B A4（Foundry GA 部落格所述），而 Gemma 系列本身不具音訊前端；這支持結論，但我們沒有取得微軟對「是否計畫加入音訊」的路線說明。
- 若日後要複驗，最快的判別法就是探針 A：送一段**故意不是合法 base64** 的 `type:"audio"`，若照樣回 200 且 token 數等於字串長度，就代表仍無音訊通道。

## 來源

- Microsoft Learn — Deploy and use Microsoft-Decision-1.1 in Microsoft Foundry：<https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision>
- Microsoft Foundry Blog — Introducing Microsoft-Decision-1.1（GA 公告）：<https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/introducing-microsoft-decision-1-1-build-faster-more-efficient-ai-applications-w/4573877>
- Artificial Analysis — Microsoft-Decision-1.1：<https://artificialanalysis.ai/decision-models/microsoft-decision-1-1>
- OpenRouter 模型頁：<https://openrouter.ai/microsoft/microsoft-decision-1.1>
- Microsoft Foundry 模型目錄：<https://ai.azure.com/catalog/models/Microsoft-Decision-1.1>
