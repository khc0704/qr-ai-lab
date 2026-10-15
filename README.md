# QR AI Lab

公司內部的 AI 模型實驗室：在討論區申請專案 → 管理員審批與分配資源配額 → 掛載資料集 → 選模型或 AutoML → 訓練 → 產物存入專案空間 → 推論。

前端 Next.js 16 + Tailwind v4 + shadcn/ui；後端 FastAPI + SQLAlchemy；MariaDB、Redis、MinIO；Keycloak 登入；單台 Ubuntu GPU 伺服器以 docker compose 部署。

## 文件

| 文件 | 內容 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 專案總覽、技術棧、目錄結構、指令、領域詞彙、工作規則（Claude Code 與開發者共用） |
| [DESIGN.md](DESIGN.md) | 前端設計系統：token、字體、元件、版面、dark mode、檢查清單 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系統架構、認證、Job 生命週期、資源排程、儲存、API、部署 |
| [docs/DATABASE.md](docs/DATABASE.md) | 資料表定義與索引 |
| [docs/MODEL_CATALOG.md](docs/MODEL_CATALOG.md) | 資料類型 × 任務 × 模型 × AutoML 搜尋空間（使用者 SOP 底稿） |

## 設計一致性如何被維持

1. `DESIGN.md` 是唯一的視覺真相；token 實作在 `frontend/src/app/globals.css`。
2. `.claude/rules/frontend.md` 在 Claude 動到 `frontend/` 時自動載入，強制只用語意 token 與共用元件。
3. `scripts/design_lint.py` 透過 `.claude/settings.json` 的 PostToolUse hook 在每次寫檔後檢查，也可在 CI 跑 `python3 scripts/design_lint.py frontend/src`。
4. `/design-review` skill 做完整的人工檢查清單。

## 狀態

規劃階段。`frontend/`、`backend/`、`trainer/`、`infra/` 尚未建立，依 CLAUDE.md 的結構逐步建立。
