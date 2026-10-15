---
name: design-review
description: 依 DESIGN.md 檢查前端變更的設計一致性（token、元件分層、版面、light/dark、無障礙），列出違規與修正建議。Use when the user asks to review UI, check design consistency, or before finishing any frontend page or component work.
---

# Design Review

依序執行，結果用「通過 / 需修正」兩段輸出；需修正的每一項都要有 `檔案:行`、違反的規則、用 token 或元件名稱寫出的修法。

1. 找出變更的前端檔案：
   ```bash
   git diff --name-only HEAD -- frontend/src; git ls-files --others --exclude-standard frontend/src
   ```
2. 跑靜態檢查並列出所有錯誤與警告：
   ```bash
   python3 scripts/design_lint.py <變更的檔案或 frontend/src>
   ```
3. 讀 `DESIGN.md` §13 檢查清單，逐項對照每個變更檔案：
   - 只用語意 token；沒有 `dark:`、hex、預設色盤、inline 顏色
   - 元件分層正確：ui → layout → features → 頁面組合；沒有在頁面重造已存在的元件
   - 一個畫面一個橘色主按鈕；狀態用 `StatusBadge`；數字用 `font-mono tabular-nums`
   - 有 loading / error / empty 三種狀態；表單有 zod 驗證與錯誤訊息
   - 版面：page header 結構、`max-w-7xl`、間距用 4/8 倍數、圓角依規定
   - 無障礙：focus ring 可見、icon-only 按鈕有 `aria-label`、顏色不是唯一的狀態訊號
   - 動效只用於狀態變化與空間關係，有 `motion-reduce:` 處理
4. 若 dev server 可啟動（`cd frontend && npm run dev`）且有 Playwright：對每個變更頁面各截一張 light 與 dark 截圖（切換 `document.documentElement.classList.toggle("dark")`），檢查對比、對齊、溢出。沒有環境就說明略過。
5. 若使用者要求修正：直接改檔，重跑第 2 步直到無錯誤，再回報。
