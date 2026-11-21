# AGENTS.md

## Commit 規則

- Commit message 遵循 [Conventional Commits 1.0.0](https://www.conventionalcommits.org/zh-hant/v1.0.0/)：`<type>(<scope>): <subject>`，`type` 用 `feat`、`fix`、`docs`、`test`、`refactor`、`perf`、`chore`、`build`、`ci`、`style`、`revert`；破壞性變更在 `type` 後加 `!`，並在 footer 寫 `BREAKING CHANGE:`。
- Subject 與 body 一律用繁體中文（zh-tw）撰寫；body 要完整詳細：說明為什麼改、改了哪些檔案與行為、如何驗證（執行的指令與結果），以及已知限制或後續待辦。
- 每完成一個使用者指令，且驗證全部通過（測試、lint、型別檢查、`markdown-fixer --check` 等適用項目）後，就立即 commit，一個指令對應一個 commit。
- 驗證失敗或指令只完成一部分時先不 commit，向使用者回報失敗的輸出與目前狀態。
- 專案沒有可執行的驗證時，在 commit body 註明「無自動化驗證」，並寫出手動確認了什麼。

## 文件格式：優先產出 HTML

- 給人閱讀的文件（報告、分析、說明、計畫、比較、調查結果）一律產出單一、自足的 `.html` 檔（CSS 內嵌），不產出 Markdown。
- 例外：給 agent 或工具讀的檔案維持 Markdown，包括 `AGENTS.md`、`CLAUDE.md`、`SKILL.md`、`README.md`；使用者明確要求 Markdown 時也照辦。
- HTML 要美觀、優雅、好讀，用下列數值當底線：
  - **字級**：內文至少 17px，`line-height` 1.7 以上；表格、程式碼、圖說等最小字級不低於 14px。
  - **字型**：`"PingFang TC", "Noto Sans TC", "Microsoft JhengHei", system-ui, sans-serif`；程式碼用等寬字型。
  - **版面**：內文欄寬上限約 72ch（或 960px）並置中；頁面左右留白桌面至少 32px、手機至少 16px；區段之間至少 48px；卡片與表格儲存格的 padding 至少 16px。
  - **配色**：顏色全部定義成 `:root` 的 CSS 變數，以一個主色搭配中性灰階；文字對比符合 WCAG AA（4.5:1）；用 `prefers-color-scheme: dark` 提供深色模式。
  - **結構**：標題層級清楚，重點用卡片、表格、標示色塊呈現，長表格可水平捲動而不撐破頁面。
- 完成條件：用瀏覽器開啟，在桌面寬度與 390px 手機寬度各看一次，確認沒有過小的字、沒有水平捲軸、深淺色模式都清楚可讀。

## Agent Skill 規則

- 新的 skill 預設建立在專案範圍的 `.agents/skills/<skill-name>/`；只有使用者明確要求時，才安裝到全域 skill 資料夾（`~/.agents/skills/`，並在 `~/.claude/skills/` 建立對應的 symbolic link）。
- 每建立一個專案 skill，都要在 `.claude/skills/` 建立指向它的相對路徑 symbolic link，讓 Claude Code 也能載入：

  ```sh
  ln -s ../../.agents/skills/<skill-name> .claude/skills/<skill-name>
  ```

- 建立後以 `ls -la .claude/skills/` 確認 link 存在，且 `cat .claude/skills/<skill-name>/SKILL.md` 讀得到內容。
