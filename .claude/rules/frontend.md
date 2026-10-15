---
paths:
  - "frontend/**/*.{ts,tsx,js,jsx,css,mdx}"
  - "frontend/package.json"
---

# Frontend 規則（Next.js 16 + Tailwind v4 + shadcn/ui）

## 設計系統（最高優先）

- 動任何 UI 之前先讀 `DESIGN.md`：新元件 / 新頁面 / 改版面 → 讀全篇；小修改 → 下方速查表足夠。
- 顏色只能用語意 token class：
  - 底色 `bg-background | bg-card | bg-popover | bg-muted | bg-accent | bg-secondary | bg-primary | bg-destructive | bg-success | bg-warning | bg-info | bg-signal | bg-sidebar`
  - 文字 `text-foreground | text-muted-foreground | text-subtle-foreground | text-primary-foreground | text-brand-ink | text-destructive | text-success | text-warning | text-info | text-signal`
  - 框線 `border-border | border-border-strong | border-input | border-primary/50`；focus `ring-ring`
  - 狀態淡底寫法：`bg-success/10 text-success border-success/30`
- 禁止：十六進位 / `rgb()` 色碼、Tailwind 預設色盤 class（`bg-orange-500`、`text-gray-400`、`border-slate-800`、`text-white`、`bg-black/50`…）、inline style 顏色、頁面與 feature 元件裡的 `dark:`（token 已處理 dark mode）。`brand-*` 原始色階只允許在 `src/app/globals.css` 與 `src/components/ui/**`。
- 元件分層：`@/components/ui`（shadcn 基底，可改樣式但不改 API）→ `@/components/layout`（AppShell、Sidebar、Topbar、PageHeader）→ `@/components/features/*`（StatusBadge、ResourceMeter、StatCard、LogViewer、EmptyState…）→ 頁面只做組合與資料取得，不自行重造樣式。
- 一個畫面只有一個橘色主按鈕；數字 / ID / log 一律 `font-mono tabular-nums`；狀態一律 `<StatusBadge>`，不自行拼色。
- 每頁都要有 `loading.tsx`（Skeleton）、`error.tsx`（含重試）與空狀態 `<EmptyState>`。
- 完成 UI 後自檢：light 與 dark 都看過；`python3 scripts/design_lint.py frontend/src` 無錯誤；鍵盤 focus ring 可見；icon-only 按鈕有 `aria-label`。

## Next.js 16 慣例

- App Router、Server Components 預設；只有需要互動 / hooks 的檔案加 `"use client"`，並盡量下推到葉子元件。
- `params`、`searchParams`、`cookies()`、`headers()` 都是 Promise，必須 `await`。
- 請求攔截用 `src/proxy.ts`（Next.js 16 改名，不再用 `middleware.ts`），只做未登入導向與輕量 header 處理。
- 資料取得：Server Component 直接呼叫 `@/lib/api`（`server-only` 的 fetch wrapper，自動帶 Keycloak access token 到 FastAPI）。寫入用 Server Actions（`"use server"`，zod 驗證輸入，回傳可序列化結果，之後 `revalidatePath` / `revalidateTag`）。
- 即時資料（job 進度、log）：client component 用 `EventSource` 訂閱 backend `/api/v1/jobs/{id}/events`（SSE）。
- 路由分組：`(auth)` 未登入頁；`(app)` 登入後的 AppShell；admin 頁在 `(app)/admin/**`，其 layout 檢查 `role === "admin"`，否則 `notFound()`。
- 狀態管理：伺服器狀態靠 RSC，client 端互動列表用 TanStack Query；表單 react-hook-form + zod；不引入全域 store。
- 型別：TypeScript strict；API 型別從 `src/types/api.ts` 取得（`pnpm gen:api` 由 backend OpenAPI 產生），不手寫重複型別。
- 檔名：所有元件與檔案 kebab-case（`status-badge.tsx` 匯出 `StatusBadge`）；hooks `use-xxx.ts`；路由資料夾 kebab-case。
- 文案繁體中文，集中在元件常數或 `src/i18n/zh-TW.ts`（預留），不要散落硬編碼。
- Lint 用 ESLint 直接執行（Next.js 16 已移除 `next lint`）；格式用 Prettier + `prettier-plugin-tailwindcss`（class 排序）。
