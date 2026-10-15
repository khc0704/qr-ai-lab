# QR AI Lab — CLAUDE.md

給 Claude Code 與開發者的專案記憶。開工前先讀這份；細節在 `DESIGN.md` 與 `docs/`，
依路徑自動載入的細部規則在 `.claude/rules/`（動到對應檔案時才會進入 context）。

## 專案是什麼

公司內部的「AI 模型實驗室」Web 應用，部署在單台公司 Ubuntu GPU 伺服器：

- 使用者在「討論區」開單申請專案（題目、資料類型 TABULAR / IMAGE / SEQUENCE / TEXT / SPECTRUM、任務、資源需求）。
- 管理員審批、分配配額（GPU / CPU / Memory / Storage）、管理成員；核准後自動建立專案。
- 專案頁：掛載資料集（一次性上傳、MinIO 路徑、URL）→ 選模型或 AutoML → 建立 Train Job → 產物存到專案空間 → 用產物做 Inference。
- 內建 SOP 讓不懂程式的人也能依資料類型選模型；AutoML 模式自動挑多個候選模型並搜尋超參數。

## 技術棧（固定，不要擅自替換）

| 層 | 選型 |
|---|---|
| Frontend | Next.js 16（App Router、Turbopack、`proxy.ts`）+ React 19 + TypeScript strict + Tailwind CSS v4 + shadcn/ui + next-themes + Auth.js（next-auth v5，Keycloak provider）+ pnpm |
| Backend API | Python 3.12 + FastAPI + SQLAlchemy 2.0 async（`mariadb+asyncmy`）+ Alembic + Pydantic v2 + uv + Ruff + pytest |
| Scheduler | 與 backend 同一套件（`app/scheduler`）：Redis（佇列、log stream）+ Docker SDK 啟動訓練容器並套用 GPU / CPU / Memory 限制 |
| Trainer | 獨立套件 `trainer/` 打成 CUDA Docker image：scikit-learn、XGBoost、PyTorch、ultralytics、transformers、timm、Optuna |
| DB | MariaDB 11（Docker）、utf8mb4、InnoDB |
| Object storage | MinIO：專案產物空間、暫存資料集、推論輸出 |
| Auth | 外部 Keycloak（OIDC）；本地只存 `users`（id、角色）與專案 / 成員等業務表 |
| Infra | docker compose、nginx、NVIDIA Container Toolkit |

## Monorepo 結構

```
qr-ai-lab/
├─ CLAUDE.md  DESIGN.md  README.md
├─ .claude/rules/      路徑觸發的規則：frontend.md、backend.md、database.md
├─ .claude/skills/     /design-review
├─ .claude/settings.json  PostToolUse hook → scripts/design_lint.py
├─ docs/               ARCHITECTURE.md、DATABASE.md、MODEL_CATALOG.md
├─ scripts/            design_lint.py 等工具腳本
├─ frontend/           Next.js 16（src/app、src/components/{ui,layout,features}、src/lib、src/proxy.ts）
├─ backend/            FastAPI：app/{core,db,models,schemas,routers,services,scheduler,storage,catalog,utils}、alembic/、tests/
├─ trainer/            訓練 / 推論 runtime：trainer/{data,models,automl,reporting}、Dockerfile
└─ infra/              docker-compose.yml、mariadb/、minio/、keycloak/、nginx/、trainer/
```

frontend / backend / trainer / infra 尚未建立；建立時依上述結構與 `docs/ARCHITECTURE.md`，不要自創頂層目錄。

## 常用指令

```bash
# frontend
cd frontend && pnpm install && pnpm dev          # http://localhost:3000
pnpm lint && pnpm typecheck && pnpm test          # 提交前
pnpm gen:api                                      # 由 backend OpenAPI 產生 src/types/api.ts
# backend
cd backend && uv sync && uv run uvicorn app.main:app --reload   # http://localhost:8000/docs
uv run ruff check . && uv run ruff format . && uv run pytest
uv run alembic revision --autogenerate -m "add_x" && uv run alembic upgrade head
uv run python -m app.scheduler                    # 排程器（需要 docker socket）
# infra
docker compose -f infra/docker-compose.yml up -d mariadb redis minio
docker build -t qr-ai-lab/trainer:dev -f infra/trainer/Dockerfile trainer
# design system
python3 scripts/design_lint.py frontend/src      # UI 變更後必跑
```

## 核心領域詞彙（程式碼與 DB 都用這些值）

- `data_type`：`TABULAR | IMAGE | SEQUENCE | TEXT | SPECTRUM`
- `task_type`：`classification | regression | detection | segmentation | anomaly_detection`
- `model_family`（見 `docs/MODEL_CATALOG.md`）：`tabular.linear | tabular.svm | tabular.random_forest | tabular.xgboost | vision.yolo | vision.dino | sequence.patch_autoencoder | text.bert_classifier`
- Issue（討論區單）`type`：`project_request | question | bug | feature`；`status`：`open | in_review | approved | rejected | closed`
- Project `status`：`active | archived`（申請中的專案只存在於 issue，核准才建立）
- TrainJob / InferenceJob `status`：`queued → scheduled → running → succeeded | failed | cancelled`
- TrainJob `mode`：`manual | auto`（auto = AutoML，候選模型 + Optuna 搜尋）
- Artifact `kind`：`model | weights | preprocessor | report | metrics`；存 MinIO `projects/{slug}/jobs/{job_id}/`
- 角色：系統角色 `admin | user`（來自 Keycloak realm role）；專案角色 `owner | maintainer | member | viewer`

## 全域工作規則

1. 先讀再做：動 UI 前讀 `DESIGN.md`；動 API / DB 前讀 `docs/ARCHITECTURE.md`、`docs/DATABASE.md`；新增模型種類先改 `docs/MODEL_CATALOG.md` 與 `backend/app/catalog/model_catalog.yaml`。
2. 大改動（新頁面、新 router、schema 變更、排程邏輯）先列計畫：檔案清單 + 資料流 + 要跑的測試，再動手。
3. 後端是權限的唯一真相：授權在 FastAPI dependency 判斷；前端只負責隱藏 UI。
4. 秘密只從環境變數讀（Keycloak client secret、MinIO、DB、`DATASET_SECRET_KEY`、`JOB_TOKEN_SECRET`）；使用者提供的資料集憑證以 Fernet 加密存 DB；log 不得含 token / 密碼。
5. 長任務（訓練、推論）一律非同步：API 只建立 job row 並回 202，由 scheduler 執行。
6. 提交前必跑：前端 `pnpm lint && pnpm typecheck`；後端 `uv run ruff check . && uv run pytest`；有 UI 變更再跑 `python3 scripts/design_lint.py frontend/src`。
7. Next.js 16：用 `src/proxy.ts`（不是 `middleware.ts`）；`params`、`searchParams`、`cookies()`、`headers()` 都要 `await`；不用 Pages Router；Tailwind v4 用 CSS `@theme`，不建 `tailwind.config.js`。
8. Commit 用 Conventional Commits + scope：`feat(frontend): …`、`fix(backend): …`、`docs: …`、`chore(infra): …`。
9. 語言：程式碼、識別字、commit、API 欄位用英文；UI 文案與文件用繁體中文。
10. 不確定時選最簡單、單機可跑、可觀測（有 log、有狀態）的做法；v1 不做多節點、不做 Kubernetes。

## 文件地圖

- `DESIGN.md`：設計系統（token、字體、元件、版面、dark mode、檢查清單）。前端設計一致性的真相來源。
- `docs/ARCHITECTURE.md`：系統架構、認證流程、Job 生命週期、資源排程、儲存配置、API 清單、部署。
- `docs/DATABASE.md`：資料表定義、索引、狀態機。
- `docs/MODEL_CATALOG.md`：資料類型 × 任務 × 模型 × AutoML 搜尋空間；也是給使用者看的 SOP 底稿。
- `.claude/rules/frontend.md`、`backend.md`、`database.md`：動到對應路徑時自動載入的細部慣例。
