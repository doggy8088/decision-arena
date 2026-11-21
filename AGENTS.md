# AGENTS.md

## Commit 規則

- Commit message 遵循 [Conventional Commits 1.0.0](https://www.conventionalcommits.org/zh-hant/v1.0.0/)：`<type>(<scope>): <subject>`，`type` 用 `feat`、`fix`、`docs`、`test`、`refactor`、`perf`、`chore`、`build`、`ci`、`style`、`revert`；破壞性變更在 `type` 後加 `!`，並在 footer 寫 `BREAKING CHANGE:`。
- Subject 與 body 一律用繁體中文（zh-tw）撰寫；body 要完整詳細：說明為什麼改、改了哪些檔案與行為、如何驗證（執行的指令與結果），以及已知限制或後續待辦。
- 每完成一個使用者指令，且驗證全部通過（測試、lint、型別檢查、`markdown-fixer --check` 等適用項目）後，就立即 commit，一個指令對應一個 commit。
- 驗證失敗或指令只完成一部分時先不 commit，向使用者回報失敗的輸出與目前狀態。
- 專案沒有可執行的驗證時，在 commit body 註明「無自動化驗證」，並寫出手動確認了什麼。

## Agent Skill 規則

- 新的 skill 預設建立在專案範圍的 `.agents/skills/<skill-name>/`；只有使用者明確要求時，才安裝到全域 skill 資料夾（`~/.agents/skills/`，並在 `~/.claude/skills/` 建立對應的 symbolic link）。
- 每建立一個專案 skill，都要在 `.claude/skills/` 建立指向它的相對路徑 symbolic link，讓 Claude Code 也能載入：

  ```sh
  ln -s ../../.agents/skills/<skill-name> .claude/skills/<skill-name>
  ```

- 建立後以 `ls -la .claude/skills/` 確認 link 存在，且 `cat .claude/skills/<skill-name>/SKILL.md` 讀得到內容。
