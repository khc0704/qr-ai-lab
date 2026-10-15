# QR AI Lab

公司內部的 AI 模型實驗室：在「專案申請」區提出申請 → 管理員審核與分配資源配額 → 專案內指定資料來源（一次性上傳，或使用者自己的 MinIO / URL）→ 選模型或 AutoML → 訓練 → 產物存入本機專案資料夾 → 推論。另有獨立的「討論區」供問答與問題單。

本服務不保存使用者的資料集；只保存訓練產物、log 與指標。管理員可設定所有專案合計的總資源池、重排佇列、強制中斷 Job；每個 Job 都有 log。

前端 Next.js 16 + Tailwind v4 + shadcn/ui（npm）；後端 FastAPI + SQLAlchemy（排程器以 Docker 啟動硬化的訓練容器）；trainer 套件涵蓋 sklearn / XGBoost / YOLO / DINOv2 / 光譜與序列自編碼器 / BERT，預訓練權重只從離線模型庫載入；MariaDB、Redis；本機磁碟 `DATA_ROOT`；過渡期本地帳號，之後接 Keycloak；單台 Ubuntu GPU 伺服器以 docker compose 部署。

## 文件

| 文件 | 內容 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 專案總覽、技術棧、目錄結構、指令、領域詞彙、工作規則（Claude Code 與開發者共用） |
| [DESIGN.md](DESIGN.md) | 前端設計系統：token、字體、元件、版面、dark mode、檢查清單 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系統架構、認證、申請審批、資料不留存政策、Job 生命週期與佇列、資源池、log、儲存、API、部署 |
| [docs/DATABASE.md](docs/DATABASE.md) | 資料表定義與索引 |
| [docs/MODEL_CATALOG.md](docs/MODEL_CATALOG.md) | 資料類型 × 任務 × 模型 × 推論模式 × AutoML 搜尋空間 × 模型庫（使用者 SOP 底稿） |
| [docs/USE_CASES.md](docs/USE_CASES.md) | 半導體 / 電子製造情境：機台資料 → 模型 → 推論目的 |
| [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) | 從 `git pull` 到前端、後端、排程器、模型庫、compose 的啟動 SOP |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 已知缺口與改善方向 |
| [docs/manuals/](docs/manuals/) | 使用者手冊（DOCX / PDF） |

## 設計一致性如何被維持

1. `DESIGN.md` 是唯一的視覺真相；token 實作在 `frontend/src/app/globals.css`。
2. `.claude/rules/frontend.md` 在 Claude 動到 `frontend/` 時自動載入，強制只用語意 token 與共用元件。
3. `scripts/design_lint.py` 透過 `.claude/settings.json` 的 PostToolUse hook 在每次寫檔後檢查，也可在 CI 跑 `python3 scripts/design_lint.py frontend/src`。
4. `/design-review` skill 做完整的人工檢查清單。

## 狀態

- 前端第一版頁面已完成（Next.js 16、假資料；見 `docs/screenshots/`），尚未接 backend。
- backend 已完成：本地帳號 `admin` / `user`、專案申請與審批、討論區、資料來源（憑證加密）、一次性上傳、Job 佇列與資源池、管理員 API（資源池、重排、強制中斷、稽核、模型庫）、SSE 事件、log；排程器（Docker / subprocess runner）。
- trainer 已完成 12 個模型家族（含影像品質基準 / 機台比對）與 AutoML、推論模式；sklearn、PyTorch（CPU、小型權重）與 YOLO（CPU，從 yaml 與從 yolo11n.pt 微調）皆有測試。
- 資料前處理：`libs/preprocess` 共用套件，上傳後抽樣預覽、訓練時 fit、推論自動沿用。
- 使用者手冊：`docs/manuals/`（DOCX / PDF）。
- 本地啟動流程見 [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)。
