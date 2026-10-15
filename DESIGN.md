# QR AI Lab Design System

前端唯一的視覺真相來源。所有 UI 程式碼都必須能回溯到這份文件的 token、元件或版面規則。

- 實作檔案：`frontend/src/app/globals.css`（token，見附錄 A）、`frontend/src/components/ui/**`（shadcn/ui 基底）、`frontend/src/components/layout/**`（App Shell）、`frontend/src/components/features/**`（領域元件）。
- 強制機制：`.claude/rules/frontend.md`（Claude 動到 `frontend/` 時自動載入）、`scripts/design_lint.py`（PostToolUse hook 與 CI）、`/design-review` skill（§13 檢查清單）。
- 改這份文件的同時必須改 `globals.css`；新增 token 還要更新 `scripts/design_lint.py` 的規則與 §2.2 表格。

## 0. 怎麼讀

| 你要做的事 | 讀哪裡 |
|---|---|
| 小修改（文案、間距、多一個按鈕） | §2.2 token 表、§8 對應元件 |
| 新元件 | §1–§6、§8、§13 |
| 新頁面 / 改版面 | 全篇，特別是 §7、§9 |
| 第一次建立前端 | §10、附錄 A、附錄 B、附錄 C |

## 1. 設計個性：Precision Lab

關鍵詞：**精密、冷靜、暗色優先、一點點熱度**。像一台高階量測儀器的操作面板：深石墨底、細線框、等寬數字、單一橘色訊號。

- 「未來科技」靠層次、線條、光暈、等寬字表達；不靠霓虹堆疊、大面積漸層、玻璃特效、掃描線。
- 橘色是訊號不是裝飾：主要動作、進行中狀態、選取 / 焦點、品牌標誌。一個畫面只有一個橘色主按鈕。
- Dark mode 是預設；Light mode 是完整支援的第一公民，所有元件兩種模式都要驗收。
- 密度：資料型應用，偏緊湊（body 14px、表格列高 40px），留白用 4 / 8 的倍數維持節奏。
- 動效只有兩種用途：狀態變化、空間關係。沒有裝飾性動畫。

## 2. 色彩

### 2.1 品牌橘（原始色階 `brand-*`）

只允許在 `globals.css` 與 `components/ui/**` 直接引用；頁面與 feature 元件一律用 §2.2 的語意 token。

| step | hex | 用途 |
|---|---|---|
| 50 | `#FFF5EC` | light：橘色淡底 |
| 100 | `#FFE8D2` | |
| 200 | `#FFCDA3` | |
| 300 | `#FFAB6A` | |
| 400 | `#FF8A3D` | dark：橘色文字（brand-ink）、primary hover |
| 500 | `#FF6B1A` | 主色：primary 按鈕底、品牌標誌、focus ring |
| 600 | `#E8570D` | light：primary hover |
| 700 | `#C2450A` | light：橘色文字（brand-ink） |
| 800 | `#9A370C` | |
| 900 | `#7C2F0E` | |
| 950 | `#431505` | dark：極深橘底（一般改用 `bg-primary/10`） |

### 2.2 語意 token（Tailwind class 字尾 ↔ CSS 變數）

命名沿用 shadcn/ui（元件可直接使用），再加本專案擴充：`success`、`warning`、`info`、`signal`、`brand-ink`、`subtle-foreground`、`border-strong`、`primary-hover`。

| token | Light | Dark | 用途 |
|---|---|---|---|
| `background` | `#F6F7F9` | `#0A0D13` | 頁面底 |
| `foreground` | `#0F1420` | `#E6EAF2` | 主要文字 |
| `card` / `card-foreground` | `#FFFFFF` / `#0F1420` | `#10141C` / `#E6EAF2` | 卡片、面板 |
| `popover` / `popover-foreground` | `#FFFFFF` / `#0F1420` | `#161B25` / `#E6EAF2` | 浮層：menu、tooltip、dialog |
| `muted` / `muted-foreground` | `#F1F3F6` / `#525C6E` | `#161B25` / `#9AA4B8` | 次要底 / 次要文字 |
| `subtle-foreground` | `#7C8699` | `#6B7589` | 第三層文字：時間戳、placeholder、≥14px 的輔助標籤 |
| `accent` / `accent-foreground` | `#F1F3F6` / `#0F1420` | `#1C2230` / `#E6EAF2` | hover / selected 底（shadcn 語意，不是品牌色） |
| `primary` / `primary-foreground` | brand-500 / `#1A0B02` | brand-500 / `#1A0B02` | 主要動作：橘底深字 |
| `primary-hover` | brand-600 | brand-400 | 主要動作 hover |
| `brand-ink` | brand-700 | brand-400 | 橘色文字、連結、作用中圖示 |
| `secondary` / `secondary-foreground` | `#E9ECF1` / `#0F1420` | `#1C2230` / `#E6EAF2` | 次要按鈕 |
| `destructive` / `destructive-foreground` | `#E11D48` / `#FFFFFF` | `#FB7185` / `#0A0D13` | 危險動作、失敗、退回 |
| `success` / `success-foreground` | `#15803D` / `#FFFFFF` | `#34D399` / `#0A0D13` | 成功、已核准 |
| `warning` / `warning-foreground` | `#B45309` / `#FFFFFF` | `#FBBF24` / `#0A0D13` | 待審、資源偏高 |
| `info` / `info-foreground` | `#0369A1` / `#FFFFFF` | `#38BDF8` / `#0A0D13` | 已排程、提示 |
| `signal` / `signal-foreground` | `#0E7490` / `#FFFFFF` | `#22D3EE` / `#0A0D13` | 「AI / 自動化」強調：AutoML 標記、sparkline；一個畫面最多一處 |
| `border` | `#E3E7EE` | `#232A38` | 預設框線 |
| `border-strong` | `#CBD2DD` | `#2F3849` | 更明顯的分隔、拖曳區、浮層邊 |
| `input` | `#E3E7EE` | `#2F3849` | 輸入框框線 |
| `ring` | brand-500 | brand-400 | focus ring |
| `sidebar` / `sidebar-foreground` | `#FFFFFF` / `#0F1420` | `#0D1118` / `#C9D1E0` | 側欄底 / 文字 |
| `sidebar-accent` / `sidebar-border` | `#F1F3F6` / `#E3E7EE` | `#161B25` / `#1C2230` | 側欄 hover 底 / 分隔線 |
| `chart-1…5` | 橘 / 青 / 紫 / 綠 / 琥珀 | 同序亮版 | 圖表序列，順序固定 |

### 2.3 用法規則

1. 背景三層：`bg-background`（頁）→ `bg-card`（卡片）→ `bg-popover`（浮層）。Dark mode 靠三層明度差表達高度，不靠陰影。
2. 文字三層：`text-foreground` → `text-muted-foreground` → `text-subtle-foreground`（只用於 ≥14px 或非必要資訊）。
3. 橘色只出現在：主按鈕、`text-brand-ink`、作用中導覽項、running 狀態、focus ring、品牌標誌、進度條填色。
4. 狀態色一律淡底寫法 `bg-{state}/10 text-{state} border-{state}/30`；因為 token 本身依模式變化，兩種模式都成立。
5. 禁止：hex、`rgb()`、Tailwind 預設色盤 class、`text-white`、`bg-black/50`、inline style 顏色、頁面裡的 `dark:`。需要新顏色先改本文件與 `globals.css`，再更新 `scripts/design_lint.py`。
6. 透明度只用 `/10 /15 /20 /30 /50 /80` 幾檔。
7. 漸層只用於品牌標誌與首頁 / 空狀態背後的徑向光暈（`bg-primary/10` 經 `blur-3xl`），內容區不用漸層。

### 2.4 對比驗證（WCAG 2.x，數值由腳本計算）

| 組合 | 比值 | 結論 |
|---|---|---|
| foreground / background（dark、light） | 16.1 / 17.2 | AAA |
| muted-foreground / card（dark、light） | 7.4 / 6.7 | AAA / AA |
| subtle-foreground / card（dark、light） | 4.0 / 3.7 | 只准大字或非必要資訊 |
| primary-foreground `#1A0B02` / primary brand-500 | 6.7 | AA，主按鈕用深字 |
| 白字 / brand-500 | 2.9 | 不及格，禁止白字壓橘底 |
| brand-ink：brand-400 / card（dark）、brand-700 / white（light） | 7.9 / 5.1 | AAA / AA |
| brand-500 文字 / white（light） | 2.9 | 不及格，light 的橘字必須用 brand-ink |
| success、warning、info、destructive 文字 / card（dark） | 9.6 / 11.1 / 8.6 / 6.9 | AAA–AA |
| success、warning、info、destructive 文字 / white（light） | 5.0 / 5.0 / 5.9 / 6.3 | AA |
| signal / background（dark）、signal / white（light） | 10.8 / 5.4 | AAA / AA |

### 2.5 狀態 → token 對照（StatusBadge 的唯一來源）

| 狀態 | token | 點 |
|---|---|---|
| `queued`、`cancelled`、`closed`、`archived` | muted | 靜止 |
| `scheduled`、`open` | info | 靜止 |
| `running` | primary | `animate-pulse-dot` |
| `succeeded`、`approved`、`active` | success | 靜止 |
| `failed`、`rejected` | destructive | 靜止 |
| `in_review` | warning | 靜止 |

## 3. 字體

- Sans：Geist（`geist` npm 套件，離線建置可用）→ `font-sans`；Mono：Geist Mono → `font-mono`。
- 中文回退放在 font stack 後段：`"Noto Sans TC", "PingFang TC", "Microsoft JhengHei"`（附錄 A）。
- 不另外引入 display 字體；科技感靠 tracking、等寬數字、大小對比。

| 角色 | class | 用在 |
|---|---|---|
| Page title | `text-2xl font-semibold tracking-tight` | 每頁一個 h1 |
| Section title | `text-lg font-semibold tracking-tight` | 區塊標題 |
| Card title | `text-base font-medium` | `CardTitle` |
| Body | `text-sm`（body 預設） | 內文、表格 |
| Caption | `text-xs text-muted-foreground` | 說明、輔助 |
| Micro label | `text-label`（11px、uppercase、tracking 0.08em、muted） | 表頭、stat 標題、側欄群組名 |
| Metric | `font-mono text-3xl font-semibold tracking-tight tabular-nums` | 儀表板數字 |
| Code / ID / log | `font-mono text-xs` | job id、路徑、log、指標值 |

- 所有數字（表格數值、百分比、配額、時間）都用 `font-mono tabular-nums`，表格內靠右。
- 行高：標題 `leading-tight`，內文預設；段落寬度上限 `max-w-prose`。

## 4. 間距、圓角、線框、層次

- 間距：4px 基準。頁面內距 `p-6`（手機 `p-4`）、卡片內距 `p-5`、元件群 `gap-2` / `gap-3`、區塊間 `space-y-6`、頁面大區段 `space-y-8`。
- 圓角（`--radius: 10px`）：按鈕、輸入框、badge `rounded-md`（8px）；卡片、對話框 `rounded-xl`（14px）；浮層 `rounded-lg`（10px）；頭像、狀態點 `rounded-full`；小 chip `rounded-sm`（6px）。不用 pill 形按鈕。
- 線框：預設 `border border-border`（1px）；強調 `border-border-strong`；作用中 / 選取 `border-primary/50`；分隔 `divide-y divide-border`。
- 層次：
  - Light：卡片無陰影（白卡 + 線框）；浮層 `shadow-elevated`。
  - Dark：不用大陰影；靠 background → card → popover 三階明度 + 線框；浮層加 `border-border-strong`。
  - 光暈 `shadow-glow-sm`：只給主按鈕（hover 升級為 `shadow-glow`）、running 狀態卡、品牌標誌。
- 背景紋理：`bg-grid`（32px 格線）或 `bg-dots`，只用於首頁 hero、空狀態、登入頁，並加 `[mask-image:radial-gradient(ellipse_at_center,black,transparent_70%)]` 淡出；內容區不鋪紋理。
- `glass`（半透明底 + blur）只用於 sticky topbar 與浮動工具列。

## 5. 動效

| 用途 | 時間 | 緩動 | 例子 |
|---|---|---|---|
| 顏色 / 透明度變化（hover、focus） | 150ms | `ease-out` | 按鈕、列 hover |
| 浮層出現 / 消失 | 200ms | `ease-out` / `ease-in` | menu、tooltip、dialog（tw-animate-css `animate-in fade-in-0 zoom-in-95`） |
| 空間變化（側欄收合、sheet、tab 指示條） | 300ms | `ease-out-expo` | sidebar `transition-[width]` |
| 狀態脈動 | 1.6s 循環 | `ease-in-out` | running 狀態點 `animate-pulse-dot` |
| 載入骨架 | 1.8s 循環 | linear | `skeleton` utility |

- 進度條 `transition-[width] duration-500 ease-out`。
- 沒有 hover 放大、沒有彈跳、沒有視差、沒有自動播放的裝飾動畫。
- 所有動效加 `motion-reduce:transition-none` 或 `motion-reduce:animate-none`。

## 6. 圖示

- 只用 `lucide-react`。尺寸：`size-4`（按鈕、導覽、表格）、`size-5`（page header、stat、空狀態輔助）、`size-8`（空狀態主圖）。stroke 用預設。
- 顏色跟隨文字 token（`text-muted-foreground`）；作用中 / 強調才用 `text-brand-ink`；狀態圖示用狀態 token。
- 固定對應：
  - 資料類型：TABULAR `Table2`、IMAGE `Image`、SEQUENCE `Activity`、TEXT `FileText`、SPECTRUM `Waves`
  - 任務：classification `Tags`、regression `TrendingUp`、detection `ScanSearch`、segmentation `Layers`、anomaly_detection `AlertTriangle`
  - 導覽：首頁 `House`、討論區 `MessagesSquare`、專案 `FolderKanban`、管理 `ShieldCheck`
- Icon-only 按鈕必有 `aria-label` 與 `Tooltip`。

## 7. 版面：App Shell

```
┌──────────────┬────────────────────────────────────────────────┐
│ ◆ QR AI Lab  │ ≡  專案 / demo-defect / 訓練       ⌘K  ◔  ☾    │ ← Topbar h-14 sticky glass
├──────────────┼────────────────────────────────────────────────┤
│ 主選單        │  h1 頁面標題                        [主按鈕]    │ ← Page header
│ ▸ 首頁        │  說明文字 text-sm muted                        │
│ ▸ 討論區   3  │                                                │
│ ▸ 專案        │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐  │ ← stat 列 grid 4
│ 管理          │  │ GPU    │ │ CPU    │ │ Memory │ │ Storage│  │
│ ▸ Dashboard   │  └────────┘ └────────┘ └────────┘ └────────┘  │
│               │  ┌────────────────────────────────────────┐    │
│               │  │ 工具列（搜尋 / 篩選）                   │    │
│               │  │ Table …                                │    │   max-w-7xl
│               │  └────────────────────────────────────────┘    │
├──────────────┤                                                │
│ ● 王小明 admin│                                                │ ← Sidebar footer 使用者卡
└──────────────┴────────────────────────────────────────────────┘
   w-64 ⇄ w-14（收合只剩 icon + tooltip）
```

### 7.1 Sidebar（shadcn `Sidebar`，`collapsible="icon"`）

- 寬度：展開 `16rem`、收合 `3.5rem`。狀態存 cookie（名稱取安裝後 `sidebar.tsx` 的 `SIDEBAR_COOKIE_NAME`），`(app)/layout.tsx` 讀 cookie 設 `defaultOpen`，避免 SSR 閃爍；快捷鍵 `⌘B` / `Ctrl+B`。
- 底色 `bg-sidebar`，右側 `border-sidebar-border`。
- Header：品牌標誌（`size-8 rounded-md bg-primary text-primary-foreground shadow-glow-sm` 內放簡寫符號）+ 「QR AI Lab」（`font-semibold tracking-tight`，收合時隱藏）。
- 群組：`主選單`（首頁、討論區、專案）、`管理`（Dashboard、使用者、資源與佇列；僅 admin 可見）。群組名用 `text-label`。
- 項目：`h-9 rounded-md`、icon `size-4` + `text-sm`；hover `bg-sidebar-accent`。作用中：`bg-sidebar-accent font-medium` + 左側 2px 橘色指示條（`before:absolute before:left-0 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-full before:bg-primary`）+ icon `text-brand-ink`。
- 計數：討論區待審數用 `SidebarMenuBadge`（`font-mono text-xs`）。
- Footer：使用者卡（`Avatar size-8`、display name `text-sm`、角色 `text-xs text-muted-foreground`）；點擊開 `DropdownMenu`：個人資料、主題（light / dark / system）、登出。收合時只顯示頭像。
- 手機（< md）：自動變 off-canvas Sheet；Topbar 左側 `SidebarTrigger`。

### 7.2 Topbar

- `sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border px-4 glass`。
- 左：`SidebarTrigger` + `Breadcrumb`（最後一節 `text-foreground`，其餘 `text-muted-foreground`）。
- 右：全域搜尋按鈕（outline，含 `<Kbd>⌘K</Kbd>`，開 `Command` 面板）、通知鈴（未讀 → 右上角 `size-2 rounded-full bg-primary`）、主題切換。
- 不放使用者頭像（在 sidebar footer），避免重複。

### 7.3 內容區

- `<main className="flex-1 p-4 md:p-6"><div className="mx-auto w-full max-w-7xl space-y-6">…</div></main>`。
- Page header（`<PageHeader>`）：`flex flex-col gap-4 md:flex-row md:items-start md:justify-between`；左：h1 + `text-sm text-muted-foreground`；右：動作區，最多一個主按鈕 + 一個 outline 按鈕 + 「更多」`DropdownMenu`。
- 分頁（專案詳情）：`Tabs` 置於 page header 下方，`border-b border-border`，作用中 tab 底線 `bg-primary` 2px。
- 網格：stat 列 `grid gap-4 sm:grid-cols-2 xl:grid-cols-4`；主內容 + 側欄 `grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]`。
- 列表頁：工具列（搜尋 `Input` + 篩選 `Select` + 排序）→ `Table` 或卡片網格 → 分頁器；永遠有空狀態。
- 表單頁：`max-w-2xl`，區段用 `Card` 分組，底部 sticky 動作列（取消 outline + 儲存 primary）。

## 8. 元件規格

所有基底元件來自 shadcn/ui（`components/ui`），以下是本專案的變體與使用規則；feature 元件（`components/features`）照這裡的配方實作。

### 8.1 Button
| variant | 配方 | 用途 |
|---|---|---|
| `default`（primary） | `bg-primary text-primary-foreground hover:bg-primary-hover shadow-glow-sm hover:shadow-glow` | 每個畫面唯一主要動作 |
| `secondary` | `bg-secondary text-secondary-foreground hover:bg-secondary/80` | 次要動作 |
| `outline` | `border border-input bg-background hover:bg-accent` | 工具列、取消 |
| `ghost` | `hover:bg-accent` | 表格列動作、icon 按鈕 |
| `destructive` | `bg-destructive text-destructive-foreground hover:bg-destructive/90` | 刪除、取消 job（一律先 `AlertDialog` 確認） |
| `link` | `text-brand-ink underline-offset-4 hover:underline` | 行內連結 |
- 尺寸：`sm h-8`、`default h-9`、`lg h-10`、`icon size-9`。字 `text-sm font-medium`；icon 在左 `gap-2`。
- Loading：`disabled` + 左側 `Spinner`；不改變寬度。
- Focus：`focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background`。

### 8.2 Card
- `rounded-xl border border-border bg-card text-card-foreground`；`CardHeader p-5 pb-3`、`CardContent p-5 pt-0`。
- 變體：`interactive`（可點：`hover:border-border-strong hover:bg-accent/40 transition-colors`）、`active`（選取：`border-primary/50 shadow-glow-sm`）。
- 卡片標題旁可放 `text-label` 的類別標籤與右上角 `DropdownMenu`。

### 8.3 Badge、StatusBadge、DataTypeChip
- Badge 基底：`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium`。
- `StatusBadge status="running"`：依 §2.5 取 token → `border-{t}/30 bg-{t}/10 text-{t}`，前置 `size-1.5 rounded-full bg-{t}` 的點；running 加 `animate-pulse-dot`。文字顯示中文（`執行中`），`title` 顯示原始值。
- `DataTypeChip`：`rounded-sm bg-muted text-muted-foreground font-mono text-[11px] uppercase tracking-wide` + §6 圖示；任務也用同樣 chip。
- 計數 badge：`font-mono tabular-nums`。

### 8.4 表單
- 一律 `Form`（react-hook-form + zod）+ `Field` 組合：`Label text-sm font-medium` → 控制項 → `FormDescription text-xs text-muted-foreground` → `FormMessage text-xs text-destructive`。
- `Input` / `Textarea` / `Select`：`h-9 rounded-md border-input bg-background text-sm`；focus `border-ring ring-2 ring-ring/30`；錯誤 `border-destructive ring-destructive/20`；數字輸入 `font-mono text-right`。
- 憑證輸入（MinIO access / secret、URL header）用 `type="password"` + 顯示切換；不自動填充。
- 分段表單（新增資料集的三種來源）用 `Tabs` 切換，不用 radio 展開。
- 精靈（新建訓練）用 `Stepper`（features）：上方步驟列（完成 `bg-primary`、目前 `border-primary`、未到 `border-border`），每步一個 `Card`，底部「上一步 / 下一步 / 建立」。

### 8.5 Table
- shadcn `Table`；表頭 `text-label`；列高 `h-10`；hover `bg-accent/50`；選取列 `bg-primary/5`。
- 數值欄 `font-mono tabular-nums text-right`；狀態欄用 `StatusBadge`；時間欄 `text-muted-foreground` 顯示相對時間，`title` 為完整時間。
- 列動作：最右欄 `ghost icon` 按鈕開 `DropdownMenu`。
- 長列表：sticky header、分頁器置底右；空資料時整表換成 `EmptyState`。

### 8.6 Tabs、Dialog、Sheet、AlertDialog
- `Tabs`（line 樣式）：`TabsList border-b bg-transparent`，`TabsTrigger` 作用中 `text-foreground border-b-2 border-primary`，其餘 `text-muted-foreground`。
- `Dialog`：`max-w-lg rounded-xl`，標題 `text-lg font-semibold`，動作列右對齊（取消 outline、確認 primary）。
- `Sheet`：右側 `w-[420px]`，用於詳情快速檢視、job 設定。
- `AlertDialog`：所有破壞性操作（刪除、取消執行中 job、封存專案）必經；確認鈕 `destructive`。

### 8.7 DropdownMenu、Tooltip、Popover、Command
- 浮層：`rounded-lg border border-border-strong bg-popover shadow-elevated`（dark 自動靠 border）。
- `Tooltip`：`text-xs`，延遲 300ms；所有 icon-only 與收合側欄項目都有。
- `Command`（⌘K）：搜尋專案、討論單、job；群組名 `text-label`。

### 8.8 Toast（sonner）
- 位置右下；`richColors` 關閉，改用 token：成功 `border-success/30`、失敗 `border-destructive/30`。
- 文案：動詞開頭（「已建立訓練任務 #128」）；失敗要帶 `code` 與「重試」動作。

### 8.9 StatCard（features）
- `Card p-5`：`text-label` 標題 → `font-mono text-3xl font-semibold tabular-nums` 數值（含單位 `text-base text-muted-foreground`）→ 底部說明 `text-xs text-muted-foreground`（可含 `text-success` / `text-destructive` 的變化量）。
- 可選右上角 §6 圖示 `text-muted-foreground`，或 sparkline（`text-signal`，一個畫面最多一個）。

### 8.10 ResourceMeter（features）
- 標題列：`text-label` 名稱 + 右側 `font-mono text-xs` 值（`2 / 4 GPU`、`12.5 / 32 GB`）。
- 軌道 `h-1.5 rounded-full bg-muted`；填色依比例：< 70% `bg-primary`、70–90% `bg-warning`、≥ 90% `bg-destructive`。
- 配額為 0 顯示「未配置」`text-subtle-foreground`。

### 8.11 LogViewer（features）
- 外框 `rounded-xl border border-border bg-background`，內部 `font-mono text-xs leading-5`，`max-h-[480px] overflow-auto`。
- 行號 `text-subtle-foreground select-none w-10 text-right pr-3`；等級著色：`ERROR` `text-destructive`、`WARN` `text-warning`、`INFO` 預設、`DEBUG` `text-muted-foreground`。
- 工具列：自動捲動開關、換行開關、下載、複製；running 時標題旁放 `StatusBadge`。
- 透過 SSE 追加，單次最多保留 5,000 行（舊的截斷並顯示「已省略 N 行」）。

### 8.12 EmptyState（features）
- 置中 `py-16`：圖示容器 `size-12 rounded-xl bg-muted text-muted-foreground`（icon `size-6`）→ 標題 `text-base font-medium` → 說明 `text-sm text-muted-foreground max-w-sm` → 一個主按鈕（可選次要連結）。
- 首頁 / 專案列表的空狀態可加 `bg-dots` 淡出背景。

### 8.13 Skeleton、Spinner、Progress
- `Skeleton` 用 `skeleton` utility，形狀對齊真實內容（標題 `h-6 w-48`、列 `h-10`）。
- 行內等待用 `Spinner size-4`；頁面級用 `loading.tsx` 的 skeleton，不用全頁 spinner。
- `Progress`：軌道 `bg-muted`，填色 `bg-primary`，右側 `font-mono text-xs` 百分比。

### 8.14 Avatar、MemberAvatars、Kbd、Breadcrumb
- `Avatar`：姓名縮寫兩字，底 `bg-muted text-muted-foreground`；admin 加 `ring-1 ring-primary/50`。
- `MemberAvatars`：最多 4 個重疊 `-space-x-2`，超過顯示 `+N`（`font-mono`）。
- `Kbd`：`rounded-sm border border-border bg-muted px-1.5 font-mono text-[11px] text-muted-foreground`。
- `Breadcrumb`：分隔用 `ChevronRight size-3.5 text-subtle-foreground`。

## 9. 頁面模式

### 9.1 首頁
- 歡迎列：「早安，王小明」+ 今日節點 GPU 可用數（`font-mono`）。
- 一般使用者：stat 列（我的專案、執行中 job、待審申請、儲存使用）→ 「我的專案」卡片網格（名稱、`DataTypeChip`、成員頭像、`ResourceMeter`×3、最新 job `StatusBadge`）→ 「最近的訓練」表 → 「我的申請」清單。
- admin 額外：待審批數 stat（`text-warning`）、節點 GPU 使用率。
- 主按鈕：`申請新專案`（導向討論區新單，type = project_request）。

### 9.2 討論區（類 GitLab Issues）
- 列表：篩選列（類型、狀態、`我的`、搜尋）；每列：`#id`（mono）、標題、type chip、`StatusBadge`、作者 `Avatar`、相對時間、留言數（mono）。
- 新單：`type` 選擇後，`project_request` 展開結構化欄位（資料類型、任務、資料量級、資源需求 GPU / CPU / Memory / Storage、預計成員）；其餘類型只有標題與 markdown 內文。
- 詳情：`grid lg:grid-cols-[minmax(0,1fr)_320px]`。左：內文（markdown 渲染）+ 時間軸（留言 `Card`；系統事件如「管理員將狀態改為 in_review」以一行 `text-label` 樣式插在時間軸中）+ 回覆輸入。右：屬性卡（狀態、類型、作者、指派、建立時間）、申請摘要卡（結構化欄位）、admin 面板（`核准` primary：填寫 slug 與配額後直接建立專案並關單；`退回` destructive：需理由）。

### 9.3 專案
- 列表：卡片 / 表格切換；篩選（資料類型、狀態、我參與的）。
- 詳情 tabs：`總覽`（配額 `ResourceMeter`、儲存用量、最近 jobs、預設模型、成員）、`資料集`（表 + 新增 `Dialog`：三種來源 `Tabs`）、`訓練`（job 表 + 新建精靈：資料集 → 任務 → 模式 自動 / 手動 → 模型與參數（手動）或 候選與預算（自動）→ 資源 → 確認；job 詳情頁：狀態列 + 進度、metrics `StatCard` 列、`LogViewer`、AutoML leaderboard 表、產物清單）、`模型`（artifacts 表：設為預設、下載、刪除）、`推論`（選模型 → 輸入來源 → 送出 → 結果表 / 下載）、`成員`（表 + 邀請、角色變更）、`設定`（名稱、描述、封存）。
- SOP 入口：新建精靈第 2 步右側 `Sheet` 顯示對應資料類型的 SOP 章節（來源 `docs/MODEL_CATALOG.md` 經 API 提供）。

### 9.4 管理員 Dashboard
- 節點資源：每張 GPU 一張 `Card`（名稱、使用率與記憶體 `ResourceMeter`、正在跑的 job 連結）+ CPU / Memory / Disk stat。
- 佇列：`queued` / `running` 表（可取消、調整優先權）。
- 待審批：issue 清單捷徑。
- 使用者：表（角色切換 admin / user、停用）。
- 專案配額：表（可直接編輯配額，儲存前 `AlertDialog` 確認）。
- 稽核紀錄：表（時間、操作者、動作、對象）。

## 10. Dark mode 與實作

- `next-themes`：`<ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>`；`<html lang="zh-Hant" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable}`}>`。
- Tailwind v4：`@custom-variant dark (&:where(.dark, .dark *));`；token 以 CSS 變數定義在 `:root` 與 `.dark`，透過 `@theme inline` 映射成 utility，因此元件不需要 `dark:`。
- 例外：`components/ui`、`components/layout` 可用 `dark:` 處理極少數形狀 / 陰影差異（例：light 用陰影、dark 用邊框）。
- 主題切換 UI：sidebar 使用者選單 + topbar 按鈕（`Sun` / `Moon` / `Monitor`）。
- 圖表：Recharts 顏色一律 `var(--chart-1)`…`var(--chart-5)`，格線 `var(--border)`，tooltip 用 `bg-popover`。
- 品牌標誌 SVG 用 `currentColor` 或 token；不內嵌固定色。

## 11. 無障礙

- 文字對比 ≥ 4.5:1，UI 元件 ≥ 3:1（§2.4 已驗證；新 token 必須重新計算）。
- 顏色不是唯一訊號：狀態一定有文字 + 點；錯誤有文字訊息。
- 鍵盤：所有互動元素可 Tab 到達，focus ring 可見；側欄 `⌘B`、搜尋 `⌘K`、對話框 `Esc` 關閉。
- `aria-label` 給 icon-only 按鈕；表格 `<th scope>`；即時 log 區加 `aria-live="polite"`（只在非自動捲動時）。
- `prefers-reduced-motion` 尊重；`prefers-color-scheme` 由 next-themes `enableSystem` 處理。

## 12. Do / Don't

| Do | Don't |
|---|---|
| 用語意 token（`bg-card`、`text-muted-foreground`） | 寫 hex、`bg-orange-500`、`text-gray-400`、`text-white` |
| 用 `components/ui` 與 `features` 組合頁面 | 在頁面重寫按鈕 / 卡片樣式 |
| 一個畫面一個橘色主按鈕 | 到處用橘色強調 |
| 數字一律 `font-mono tabular-nums` | 比例字數字對不齊 |
| 狀態用 `StatusBadge` | 自己拼 `bg-green-100 text-green-800` |
| Dark 靠明度三層 + 線框 | Dark 用大陰影或純黑 `#000` |
| 動效只做狀態 / 空間變化 | hover 放大、彈跳、裝飾動畫 |
| 空 / 載入 / 錯誤三態都做 | 只做 happy path |
| 新顏色先改 DESIGN.md + globals.css + lint | 直接在元件加顏色 |

## 13. 檢查清單（完成任何 UI 前）

- [ ] 只用語意 token；`python3 scripts/design_lint.py frontend/src` 無錯誤與警告
- [ ] 沒有在頁面 / features 用 `dark:`；light 與 dark 都實際看過
- [ ] 元件分層正確（ui → layout → features → 頁面）；沒有重造已存在的元件
- [ ] 一個畫面一個主按鈕；破壞性操作有 `AlertDialog`
- [ ] 數字 `font-mono tabular-nums`；狀態用 `StatusBadge`；資料類型用 `DataTypeChip`
- [ ] `loading.tsx`、`error.tsx`、`EmptyState` 齊全
- [ ] 間距 4 / 8 倍數；圓角依 §4；版面寬度 `max-w-7xl`
- [ ] focus ring 可見；icon-only 有 `aria-label`；顏色非唯一訊號
- [ ] 動效限 §5 的用途與時長；有 `motion-reduce`
- [ ] 文案繁體中文、動詞開頭；錯誤訊息含可行動的下一步

---

## 附錄 A：`frontend/src/app/globals.css`

shadcn `init` 產生的 `globals.css` 以這份整個取代；變數名稱與 shadcn 相容，元件不需改。

```css
/* QR AI Lab design tokens — Tailwind CSS v4. Source of truth: DESIGN.md */
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:where(.dark, .dark *));

/* 1. Raw brand scale: only this file and components/ui may reference brand-* */
:root {
  --brand-50: #fff5ec;
  --brand-100: #ffe8d2;
  --brand-200: #ffcda3;
  --brand-300: #ffab6a;
  --brand-400: #ff8a3d;
  --brand-500: #ff6b1a;
  --brand-600: #e8570d;
  --brand-700: #c2450a;
  --brand-800: #9a370c;
  --brand-900: #7c2f0e;
  --brand-950: #431505;
  --radius: 0.625rem;
}

/* 2. Semantic tokens — light */
:root {
  --background: #f6f7f9;
  --foreground: #0f1420;
  --card: #ffffff;
  --card-foreground: #0f1420;
  --popover: #ffffff;
  --popover-foreground: #0f1420;
  --muted: #f1f3f6;
  --muted-foreground: #525c6e;
  --subtle-foreground: #7c8699;
  --accent: #f1f3f6;
  --accent-foreground: #0f1420;
  --primary: var(--brand-500);
  --primary-hover: var(--brand-600);
  --primary-foreground: #1a0b02;
  --brand-ink: var(--brand-700);
  --secondary: #e9ecf1;
  --secondary-foreground: #0f1420;
  --destructive: #e11d48;
  --destructive-foreground: #ffffff;
  --success: #15803d;
  --success-foreground: #ffffff;
  --warning: #b45309;
  --warning-foreground: #ffffff;
  --info: #0369a1;
  --info-foreground: #ffffff;
  --signal: #0e7490;
  --signal-foreground: #ffffff;
  --border: #e3e7ee;
  --border-strong: #cbd2dd;
  --input: #e3e7ee;
  --ring: var(--brand-500);
  --sidebar: #ffffff;
  --sidebar-foreground: #0f1420;
  --sidebar-primary: var(--brand-500);
  --sidebar-primary-foreground: #1a0b02;
  --sidebar-accent: #f1f3f6;
  --sidebar-accent-foreground: #0f1420;
  --sidebar-border: #e3e7ee;
  --sidebar-ring: var(--brand-500);
  --chart-1: var(--brand-500);
  --chart-2: #0e7490;
  --chart-3: #6d28d9;
  --chart-4: #15803d;
  --chart-5: #b45309;
}

/* 3. Semantic tokens — dark (default theme) */
.dark {
  --background: #0a0d13;
  --foreground: #e6eaf2;
  --card: #10141c;
  --card-foreground: #e6eaf2;
  --popover: #161b25;
  --popover-foreground: #e6eaf2;
  --muted: #161b25;
  --muted-foreground: #9aa4b8;
  --subtle-foreground: #6b7589;
  --accent: #1c2230;
  --accent-foreground: #e6eaf2;
  --primary: var(--brand-500);
  --primary-hover: var(--brand-400);
  --primary-foreground: #1a0b02;
  --brand-ink: var(--brand-400);
  --secondary: #1c2230;
  --secondary-foreground: #e6eaf2;
  --destructive: #fb7185;
  --destructive-foreground: #0a0d13;
  --success: #34d399;
  --success-foreground: #0a0d13;
  --warning: #fbbf24;
  --warning-foreground: #0a0d13;
  --info: #38bdf8;
  --info-foreground: #0a0d13;
  --signal: #22d3ee;
  --signal-foreground: #0a0d13;
  --border: #232a38;
  --border-strong: #2f3849;
  --input: #2f3849;
  --ring: var(--brand-400);
  --sidebar: #0d1118;
  --sidebar-foreground: #c9d1e0;
  --sidebar-primary: var(--brand-500);
  --sidebar-primary-foreground: #1a0b02;
  --sidebar-accent: #161b25;
  --sidebar-accent-foreground: #e6eaf2;
  --sidebar-border: #1c2230;
  --sidebar-ring: var(--brand-400);
  --chart-1: var(--brand-400);
  --chart-2: #22d3ee;
  --chart-3: #a78bfa;
  --chart-4: #34d399;
  --chart-5: #fbbf24;
}

/* 4. Expose tokens as Tailwind utilities (bg-card, text-brand-ink, border-border-strong, ...) */
@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-subtle-foreground: var(--subtle-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-primary: var(--primary);
  --color-primary-hover: var(--primary-hover);
  --color-primary-foreground: var(--primary-foreground);
  --color-brand-ink: var(--brand-ink);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-success: var(--success);
  --color-success-foreground: var(--success-foreground);
  --color-warning: var(--warning);
  --color-warning-foreground: var(--warning-foreground);
  --color-info: var(--info);
  --color-info-foreground: var(--info-foreground);
  --color-signal: var(--signal);
  --color-signal-foreground: var(--signal-foreground);
  --color-border: var(--border);
  --color-border-strong: var(--border-strong);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);
  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);
  --color-chart-4: var(--chart-4);
  --color-chart-5: var(--chart-5);
  --color-brand-50: var(--brand-50);
  --color-brand-100: var(--brand-100);
  --color-brand-200: var(--brand-200);
  --color-brand-300: var(--brand-300);
  --color-brand-400: var(--brand-400);
  --color-brand-500: var(--brand-500);
  --color-brand-600: var(--brand-600);
  --color-brand-700: var(--brand-700);
  --color-brand-800: var(--brand-800);
  --color-brand-900: var(--brand-900);
  --color-brand-950: var(--brand-950);

  --font-sans: var(--font-geist-sans), "Noto Sans TC", "PingFang TC", "Microsoft JhengHei",
    ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  --radius-2xl: calc(var(--radius) + 10px);

  --shadow-elevated: 0 1px 2px rgb(0 0 0 / 0.06), 0 12px 32px -12px rgb(0 0 0 / 0.28);
  --shadow-glow-sm: 0 0 18px -6px color-mix(in oklab, var(--primary) 65%, transparent);
  --shadow-glow: 0 0 0 1px color-mix(in oklab, var(--primary) 45%, transparent),
    0 0 32px -6px color-mix(in oklab, var(--primary) 75%, transparent);

  --ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);
  --animate-pulse-dot: pulse-dot 1.6s ease-in-out infinite;
  --animate-shimmer: shimmer 1.8s linear infinite;

  @keyframes pulse-dot {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.55; transform: scale(0.85); }
  }
  @keyframes shimmer {
    from { background-position: -200% 0; }
    to { background-position: 200% 0; }
  }
}

/* 5. Base */
@layer base {
  * {
    @apply border-border outline-ring/50;
  }
  html {
    color-scheme: light;
  }
  .dark {
    color-scheme: dark;
  }
  body {
    @apply bg-background font-sans text-sm text-foreground antialiased;
  }
  h1, h2, h3, h4 {
    @apply tracking-tight;
  }
  ::selection {
    background: color-mix(in oklab, var(--primary) 35%, transparent);
  }
}

/* 6. Project utilities */
@utility text-label {
  @apply text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground;
}
@utility glass {
  background-color: color-mix(in oklab, var(--background) 80%, transparent);
  backdrop-filter: blur(12px);
}
@utility bg-grid {
  background-image:
    linear-gradient(to right, color-mix(in oklab, var(--border) 70%, transparent) 1px, transparent 1px),
    linear-gradient(to bottom, color-mix(in oklab, var(--border) 70%, transparent) 1px, transparent 1px);
  background-size: 32px 32px;
}
@utility bg-dots {
  background-image: radial-gradient(color-mix(in oklab, var(--border-strong) 80%, transparent) 1px, transparent 1px);
  background-size: 20px 20px;
}
@utility skeleton {
  border-radius: var(--radius-md);
  background: linear-gradient(90deg, var(--muted) 25%, var(--accent) 50%, var(--muted) 75%);
  background-size: 200% 100%;
  animation: var(--animate-shimmer);
}
```

## 附錄 B：shadcn/ui 設定與安裝

```bash
# 1. 建立專案（Node ≥ 20.9；Next.js 16 預設 Turbopack）
pnpm create next-app@latest frontend --ts --tailwind --eslint --app --src-dir --import-alias "@/*"
cd frontend

# 2. 依賴
pnpm add geist next-themes lucide-react sonner @tanstack/react-query react-hook-form zod @hookform/resolvers next-auth@beta
pnpm add -D tw-animate-css prettier prettier-plugin-tailwindcss

# 3. shadcn（style: new-york、base color: neutral、CSS variables: yes）→ 之後用附錄 A 覆蓋 globals.css
pnpm dlx shadcn@latest init
pnpm dlx shadcn@latest add button card badge input label textarea select switch checkbox table tabs \
  dialog alert-dialog sheet dropdown-menu tooltip popover command sidebar breadcrumb separator \
  skeleton avatar sonner form progress scroll-area kbd spinner empty
```

`frontend/components.json`：

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": true,
  "tsx": true,
  "tailwind": { "config": "", "css": "src/app/globals.css", "baseColor": "neutral", "cssVariables": true, "prefix": "" },
  "aliases": { "components": "@/components", "utils": "@/lib/utils", "ui": "@/components/ui", "lib": "@/lib", "hooks": "@/hooks" },
  "iconLibrary": "lucide"
}
```

`src/app/layout.tsx` 骨架：

```tsx
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { ThemeProvider } from "@/components/layout/theme-provider";
import "./globals.css";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
```

`src/app/(app)/layout.tsx` 骨架：

```tsx
import { cookies } from "next/headers";
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { Topbar } from "@/components/layout/topbar";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const defaultOpen = cookieStore.get("sidebar_state")?.value !== "false"; // 名稱以 sidebar.tsx 的 SIDEBAR_COOKIE_NAME 為準
  return (
    <SidebarProvider defaultOpen={defaultOpen}>
      <AppSidebar />
      <SidebarInset>
        <Topbar />
        <main className="flex-1 p-4 md:p-6">
          <div className="mx-auto w-full max-w-7xl space-y-6">{children}</div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
```

## 附錄 C：元件檔案地圖

```
frontend/src/components/
├─ ui/                      shadcn 基底（可調樣式，不改 API；唯一可用 brand-* 的地方）
├─ layout/
│  ├─ theme-provider.tsx    next-themes 包裝（client）
│  ├─ app-sidebar.tsx       §7.1
│  ├─ topbar.tsx            §7.2
│  ├─ page-header.tsx       §7.3
│  ├─ user-menu.tsx         sidebar footer 使用者卡 + DropdownMenu
│  ├─ theme-toggle.tsx      Sun / Moon / Monitor
│  └─ brand-mark.tsx        品牌標誌
└─ features/
   ├─ status-badge.tsx      §2.5 + §8.3
   ├─ data-type-chip.tsx    §8.3
   ├─ stat-card.tsx         §8.9
   ├─ resource-meter.tsx    §8.10
   ├─ log-viewer.tsx        §8.11（client，SSE）
   ├─ empty-state.tsx       §8.12
   ├─ member-avatars.tsx    §8.14
   ├─ stepper.tsx           §8.4
   ├─ issue-timeline.tsx    §9.2
   ├─ project-card.tsx      §9.3
   └─ model-picker.tsx      §9.3（讀 /api/v1/catalog）
```
