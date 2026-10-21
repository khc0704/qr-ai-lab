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
- Job 相關畫面（專案的 Job 詳情、管理員佇列的 Job 抽屜）共用 `LogViewer`、`JobStatusBar`、`StatusBadge`；不要為管理員另做一套。
- 任何接觸使用者資料的 UI（一次性上傳 `Dropzone`、資料來源表單）必須顯示「本服務不保存資料」的 `info` 提示，憑證欄位不回填。
- 完成 UI 後自檢：light 與 dark 都看過；`python3 scripts/design_lint.py frontend/src` 無錯誤；鍵盤 focus ring 可見；icon-only 按鈕有 `aria-label`。

## Next.js 16 慣例

- App Router、Server Components 預設；只有需要互動 / hooks 的檔案加 `"use client"`，並盡量下推到葉子元件。
- `params`、`searchParams`、`cookies()`、`headers()` 都是 Promise，必須 `await`。
- 請求攔截用 `src/proxy.ts`（Next.js 16 改名，不再用 `middleware.ts`），只做未登入導向與輕量 header 處理。
- 資料取得：Server Component 直接呼叫 `@/lib/api`（`server-only` 的 fetch wrapper，自動帶 Keycloak access token 到 FastAPI）。寫入用 Server Actions（`"use server"`，zod 驗證輸入，回傳可序列化結果，之後 `revalidatePath` / `revalidateTag`）。
- 即時資料（job 進度、log）：client component 用 `EventSource` 訂閱 backend `/api/v1/jobs/{id}/events`（SSE）。
- 路由分組：`(auth)` 未登入頁；`(app)` 登入後的 AppShell；admin 頁在 `(app)/admin/**`，其 layout 用 `isAdmin(user)`（admin 或 superadmin）否則 `notFound()`；頁面內更細的按鈕用 `can(user, "<perm>")`（`src/lib/roles.ts`，權限清單來自 `/me`），不要再寫 `role === "admin"`。
- 認證：`AUTH_MODE=local` 走 `loginAction` + cookie `qr_token`；`AUTH_MODE=keycloak` 走 `src/auth.ts`（Auth.js Keycloak provider）+ 瀏覽器端 `signIn("keycloak")`（`next-auth/react`）/ `logoutAction`（server：signOut + Keycloak end-session）；`getToken()`（`src/lib/backend.ts`）依模式取 token，Route Handler 與 `apiFetch` 都只用它。登入頁上和 `AUTH_MODE` 有關的內容要放在讀 `searchParams` 的動態子樹，不能進 prerender 的殼。
- 狀態管理：伺服器狀態靠 RSC，client 端互動列表用 TanStack Query；表單 react-hook-form + zod；不引入全域 store。
- 型別：TypeScript strict；API 的前端型別手寫在 `src/types/domain.ts`（camelCase），snake_case → camelCase 的轉換集中在 `src/lib/api/mappers.ts`（枚舉值要原樣傳遞，不要用預設值吞掉未知值；`npm test` 的 mapper 測試會檢查）。
- 檔名：所有元件與檔案 kebab-case（`status-badge.tsx` 匯出 `StatusBadge`）；hooks `use-xxx.ts`；路由資料夾 kebab-case。
- 文案繁體中文，集中在元件常數或 `src/i18n/zh-TW.ts`（預留），不要散落硬編碼。
- Lint 用 ESLint 直接執行（Next.js 16 已移除 `next lint`）；格式用 Prettier + `prettier-plugin-tailwindcss`（class 排序）。`npm run typecheck` 會先 `next typegen` 再 `tsc`。
- **頁面的資料一律放在頁面自己的 `<Suspense>` 裡**（Next 16.4 instant navigation）：`page.tsx` 的 default export 必須是同步函式，只回傳 `<Suspense fallback={<PageSkeleton />}><Content params={params} /></Suspense>`，`await`（`@/lib/api`、`getCurrentUser()`、`params`、`searchParams`）全部寫在內層的 async 元件。父 layout 的 Suspense **不算**：client 端導覽只重新渲染目標 page segment，dev overlay 會報「Instant: encountered uncached data during prerendering or a navigation」。`src/app/pages-stream.test.ts`（`npm test`）會擋 `export default async function` 的頁面。
- Cache Components 已開啟（`cacheComponents: true`），build 會驗證：讀 `params` / `searchParams` / `cookies()` / `headers()` 的 Server Component 與呼叫 `usePathname()` / `useSearchParams()` 的 Client Component 必須包在 `<Suspense>`（fallback 給 Skeleton 或無作用中狀態的同一元件）；伺服器渲染不可用 `new Date()` / `Math.random()`（放 client 元件 + `useSyncExternalStore`）；`(app)/layout.tsx` 不讀 cookie。範例見 `components/layout/breadcrumbs.tsx`、`components/features/greeting.tsx`。
- `components/ui/**` 是從 shadcn registry 複製的，可為了 React Compiler 的 ESLint 規則做最小修改（已改：`sidebar.tsx` skeleton 寬度改用 `useId`、`hooks/use-mobile.ts` 改用 `useSyncExternalStore`）；重新用 `npx shadcn add --overwrite` 更新時要重套這兩處。
- react-hook-form 取值用 `useWatch`，不要 `form.watch()`（React Compiler 無法記憶化）。
- **Server Component 只能從 `"use client"` 模組 import 元件**（PascalCase）：常數、helper、Set 之類的值經過 client boundary 會變成 client reference（`X.has is not a function`、`Attempted to call X() from the server`）。共用的值放 `src/lib/*`（純模組），`src/app/client-boundary.test.ts`（`npm test`）會擋。
- 精靈的手動參數依目錄型別呈現（`ParamField`：有選項清單的 → `Select`（清單 = `i18n.paramChoices[name]` ∪ `search_space` 的 categorical，選項旁的中文說明來自 `i18n.paramChoiceLabel[name][value]`，欄位下的提示來自 `i18n.paramHint[name]`；新參數先補這三張表）、布林 → true / false、`augment` → 依家族 `augment_choices` 的多選、其餘文字框；`paramVisible()` 依其他設定隱藏欄位：`k` 只在 `head=knn`、`vision.dino` 的微調欄位只在 `finetune` 不是 none、`backbone_lr` 只在 full、PatchCore 欄位只在 `patchcore` 不是 off；`backbone` 與 `finetune` 本身在精靈獨立的「骨幹」步驟（`stepKeys` 依任務決定步驟，IMAGE × classification 才有，排在「模式」之前；自動模式把兩者放進 `config.backbone` / `config.finetune` 固定不搜尋），上傳的 zip 有類別資料夾時顯示偵測到的正常資料夾；目錄標 `deprecated` 的家族不列出）；申請表單的任務下拉用 `lib/catalog.ts` 的 `supportedTasks(catalog)` 過濾。資料分析的影像報告（`analysis-report.tsx`）在 `result.label_check` / `result.layers` 存在時多顯示「標籤一致性檢查」與「各層特徵代表什麼」兩張卡。
- 表格長內容：`TableCell` 偵測到截斷時在右側顯示「展開完整內容」切換（只展開那一格），`Table` 右上角的「展開內容」是整表換行；key / value 清單用 `components/features/expandable-value.tsx`。
- 讀取只經過 `@/lib/api`（`server-only` fetch，snake_case → camelCase 在 `src/lib/api/mappers.ts`），寫入只經過 `@/lib/actions.ts`（Server Actions，回傳 `ActionResult`，成功後 `revalidatePath`）；瀏覽器不直接打 backend，上傳 / SSE / 下載走 `src/app/api/*` 的 Route Handler。新 API 欄位先改 `src/types/domain.ts` 與 mapper，再改頁面。
- 相對時間 / 耗時用 `components/features/time.tsx` 的 `RelativeTime` / `Duration`（server 不可讀時鐘）；任務即時狀態用 `JobLive`。
- 文件：本地啟動流程在 `docs/GETTING_STARTED.md`；端到端截圖用 `npm run screenshots`（需要整套服務在跑，輸出到 `docs/screenshots/e2e/`），報告用 `npm run screenshots:report`。
- 看樣本只從瀏覽器本地讀：`lib/local-data.ts` 保存上傳時的 `File`（Dropzone `onUploaded` 的第三個參數），建任務時 `aliasLocalFile(uploadKey(...), jobKey(id))`；結果頁用 `SampleViewer` / `PreviewTable` 顯示，不新增任何把資料存回伺服器的端點。zip 用 `lib/zip-reader.ts` 隨機讀取、CSV / JSONL 用 `lib/line-index.ts`，都不把整個檔案載進記憶體。
