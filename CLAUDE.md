# QR AI Lab — CLAUDE.md

給 Claude Code 與開發者的專案記憶。開工前先讀這份；細節在 `DESIGN.md` 與 `docs/`，
依路徑自動載入的細部規則在 `.claude/rules/`（動到對應檔案時才會進入 context）。

## 專案是什麼

公司內部的「AI 模型實驗室」Web 應用，部署在單台公司 Ubuntu GPU 伺服器：

- 「專案申請」區：使用者填結構化申請（題目、資料類型 TABULAR / IMAGE / SEQUENCE / TEXT / SPECTRUM、任務、資源需求）；管理員審核、分配配額（GPU / CPU / Memory / Storage）、管理成員；核准後自動建立專案。
- 「討論區」是獨立的問答 / 問題單區（question / bug / feature），管理員回覆與關閉；與專案申請分開。
- 專案頁：指定資料來源（一次性上傳、或使用者自己的 MinIO / URL + 憑證）→ 選模型或 AutoML → 建立 Job → 產物存到本機專案資料夾 → 用產物做推論。
- 本服務不保存使用者的資料集：上傳檔與從使用者 MinIO / URL 抓下的副本只存在於該 Job 執行期間，Job 結束即刪。保存的只有訓練產物、log 與指標。
- 管理員後台：設定所有專案合計可用的總資源池、檢視並重排佇列、強制中斷執行中的 Job；每個 Job 都有 log，專案頁與管理員頁都能看。
- 內建 SOP 讓不懂程式的人也能依資料類型選模型；AutoML 模式自動挑多個候選模型並搜尋超參數。

## 技術棧（固定，不要擅自替換）

| 層 | 選型 |
|---|---|
| Frontend | Next.js 16（App Router、Turbopack、`proxy.ts`）+ React 19 + TypeScript strict + Tailwind CSS v4 + shadcn/ui + next-themes + Auth.js（next-auth v5，Keycloak provider）+ npm |
| Backend API | Python ≥ 3.12 + FastAPI + SQLAlchemy 2.0 async（`mariadb+asyncmy`；dev / test 用 `sqlite+aiosqlite`）+ Alembic + Pydantic v2 + uv + Ruff + pytest；`AUTH_MODE=local`（dev：argon2 + HS256 本地帳號）或 `keycloak`（prod：驗 realm JWKS、`KEYCLOAK_ROLE_MAP` 對應角色）；權限矩陣在 `app/core/permissions.py`（`require_perm`） |
| Scheduler | 與 backend 同一套件（`app/scheduler`）：Job 是主機子程序（trainer venv），`JOB_RUNNER=auto` 優先用 `systemd-run --scope`（cgroup 限 Memory / CPU / 核心），否則 subprocess + affinity + 記憶體 watchdog；GPU 以 `CUDA_VISIBLE_DEVICES` 分配並用 pynvml 預檢；事件走 Redis（兩個程序）或記憶體（`SCHEDULER_EMBEDDED=true` 單程序）；容量上限 = 管理員設定的總資源池 |
| Trainer | 獨立套件 `trainer/`，裝在主機的 `trainer/.venv`（torch CUDA wheel、ultralytics、transformers、Optuna、scikit-learn、XGBoost）：自行從使用者的 MinIO / URL 抓資料；**離線執行（runner 設 HF_HUB_OFFLINE 等），預訓練權重只從模型庫 `MODEL_ZOO_ROOT` 載入**，由管理員經「模型庫」頁上傳 / 路徑匯入 / 內網 URL 帶進來 |
| DB | MariaDB 11（Docker）、utf8mb4、InnoDB |
| Storage | 本機磁碟 `DATA_ROOT`（產物、log、暫存輸入）；`backend/app/storage/` 抽象成介面，未來可換自有 MinIO |
| 外部資料來源 | 使用者的 MinIO / S3 相容服務、HTTP(S) URL；憑證 Fernet 加密存 DB，只在 Job 容器內解密使用 |
| Auth | dev：本地帳號 `superadmin` / `admin` / `user`（`POST /auth/login`，cookie `qr_token`）；prod：公司 Keycloak（前端 Auth.js `src/auth.ts`，登入按鈕用 `next-auth/react` 的 `signIn` 走 Authorization Code + PKCE，session cookie 內存 access / refresh / id token，`getToken()` 把 access token 轉給 FastAPI）。兩邊都用 `AUTH_MODE` 切換；只存 `users`（id、角色）與專案 / 成員等業務表。系統角色可在 `/admin/users` 調整（superadmin） |
| Infra | docker compose 只跑 MariaDB / Redis（image 來自公司鏡像）；backend / scheduler / frontend 是 systemd 服務（`infra/systemd/`）；nginx 原生；伺服器不連外，套件來自 PyPI / npm 鏡像 |

## Monorepo 結構

```
qr-ai-lab/
├─ CLAUDE.md  DESIGN.md  README.md
├─ .claude/rules/      路徑觸發的規則：frontend.md、backend.md、database.md
├─ .claude/skills/     /design-review
├─ .claude/settings.json  PostToolUse hook → scripts/design_lint.py
├─ docs/               ARCHITECTURE.md、DATABASE.md、MODEL_CATALOG.md、USE_CASES.md、GETTING_STARTED.md、ROADMAP.md、manuals/
├─ scripts/            design_lint.py、fetch_model_zoo.py（在有網路的機器下載預訓練權重）、build_manual.js（使用手冊 DOCX）
├─ libs/preprocess/    共用套件 qrlab_preprocess：資料前處理步驟（backend 預覽 / 驗證、trainer fit + replay）
├─ frontend/           Next.js 16（src/app、src/components/{ui,layout,features}、src/lib、src/proxy.ts）
├─ backend/            FastAPI：app/{core,db,events,models,schemas,routers,services,scheduler,storage,catalog}、alembic/、tests/
├─ trainer/            訓練 / 推論 runtime：trainer/{runtime,automl,dataset,fetch,metrics}.py、trainer/{data,models}/、tests/
└─ infra/              docker-compose.yml（mariadb、redis）、systemd/（三個 service + qrlab.env.example）、nginx/、install.sh、mariadb/
```

frontend（已接 backend：`src/lib/api` 為 server-only fetch 層、`src/lib/actions.ts` 為 Server Actions、`src/app/api/*` 代理上傳 / SSE / 下載）、backend、trainer、infra 都已建立。不要自創頂層目錄。

## 常用指令

```bash
# frontend（npm，提交 package-lock.json）
cd frontend && npm install && npm run dev        # http://localhost:3000
npm run lint && npm run typecheck && npm run format:check && npm test     # 提交前（npm test = vitest）
npm run build && npm run start                    # 正式建置（BACKEND_URL 預設 http://localhost:8000）
npm run screenshots && npm run screenshots:report  # 端到端串接測試 + 截圖 + PDF 報告（需要 backend、排程器、前端、Redis 都在跑）
# backend（dev：SQLite 自動建表並建立 superadmin/superadmin1234、admin/admin1234、user/user1234）
cd backend && uv sync && uv run uvicorn app.main:app --reload   # http://localhost:8000/docs
uv run ruff check . && uv run ruff format . && uv run pytest      # 含排程器測試與 e2e（真的 trainer 子程序）
uv run alembic revision --autogenerate -m "add_x" && uv run alembic upgrade head   # MariaDB
uv run python -m app.scheduler                    # 排程器（或 SCHEDULER_EMBEDDED=true 讓 backend 內嵌，開發時不用 Redis）；JOB_RUNNER=auto|systemd|subprocess
uv run python -m app.cli seed|create-user|set-password|set-role|model-zoo [--verify]
bash scripts/export_requirements.sh               # uv add / uv lock 之後：重新匯出 backend / trainer 的 requirements.txt（伺服器用 pip 裝，CI 會比對）
npm run screenshots:keycloak                      # 以 AUTH_MODE=keycloak 啟動的前後端 + 假 Keycloak 跑登入 / 登出截圖
# trainer
cd trainer && uv sync && uv run pytest && uv run python -m trainer check   # check：這個環境能跑哪些家族
cd libs/preprocess && ../../trainer/.venv/bin/python -m pytest             # 共用前處理套件
node scripts/build_manual.js                      # 使用手冊 DOCX（再用 soffice 轉 PDF）
# model zoo（在有網路的機器）
python3 scripts/fetch_model_zoo.py --dest ./model_zoo     # 再複製到伺服器的 MODEL_ZOO_ROOT
# infra
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d            # mariadb、redis（只有這兩個跑在 docker）
./infra/install.sh            # 伺服器：venv（pip + requirements.txt，走 /etc/pip.conf 的 proxy；不用 uv）、前端 build、migration、systemd 服務；--update 升級
# design system
python3 scripts/design_lint.py frontend/src      # UI 變更後必跑
```

## 核心領域詞彙（程式碼與 DB 都用這些值）

- `data_type`：`TABULAR | IMAGE | SEQUENCE | TEXT | SPECTRUM`
- `task_type`：`classification | regression | detection | segmentation | anomaly_detection`
- `model_family`（見 `docs/MODEL_CATALOG.md`）：`tabular.linear | tabular.svm | tabular.random_forest | tabular.xgboost | tabular.isolation_forest | vision.yolo | vision.dino_fewshot | vision.dino_patchcore | vision.image_quality | sequence.patch_autoencoder | spectrum.masked_autoencoder | text.bert_classifier`
- 推論模式（推論 Job 的 `config.mode`）：`predict | score | compare | embed | retrieve | detect | segment | measure | extend`（見 `docs/USE_CASES.md` §1）
- 前處理：`input.spec.preprocess = [{op, params}]`，op id 形如 `tabular.impute`、`image.align`、`sequence.msc`、`text.dedupe`（`libs/preprocess`）
- ProjectRequest（專案申請）`status`：`submitted | in_review | approved | rejected | withdrawn`；核准才建立 project
- Issue（討論區）`type`：`question | bug | feature`；`status`：`open | closed`
- Project `status`：`active | archived`；`kind`：`standard | personal`（personal = 每人一個的個人工作區 `ws-<username>`，放工具任務，配額來自管理員「工具預設」，不列在一般專案列表）
- Job（`jobs` 表統一訓練與推論）`kind`：`train | inference | preprocess | analysis`（後兩者是個人工作區的工具任務）；`status`：`queued → scheduled → running → succeeded | failed | cancelled`；`queue_rank` 決定佇列順序（小的先跑，admin 可重排）
- Job `mode`（train）：`manual | auto`（auto = AutoML，候選模型 + Optuna 搜尋）
- Job `input.kind`：`upload`（一次性上傳，Job 結束即刪）| `data_source`（使用者的 MinIO / URL）| `inline`（推論的小量 JSON）
- DataSource `kind`：`minio | url`；只存連線參考與加密憑證，不存資料
- Artifact `kind`：`model | weights | preprocessor | report | metrics`；存 `DATA_ROOT/projects/{slug}/jobs/{job_id}/`
- 角色：系統角色 `superadmin | admin | user`（`users.role`；Keycloak 登入時依 `KEYCLOAK_ROLE_MAP` 覆蓋，否則以 UI 設定為準）；權限名稱 `admin.view | requests.review | jobs.control | issues.moderate | users.view | audit.view | usage.view`（admin 以上）與 `pool.manage | quota.manage | projects.delete | users.manage | model_zoo.manage | gpu.reset`（superadmin），`/me` 回傳 `permissions`，前端用 `can(user, perm)` 只做隱藏；專案角色 `owner | maintainer | member | viewer`
- Job 的 `requested_gpu_memory_mb`：有值 = 可與其他任務依剩餘顯存共用一張 GPU（資源池 `gpu_share`，trainer 以 `set_per_process_memory_fraction` 自限）；`null` = 獨占整張
- 工具（不需專案）：`POST /tools/uploads` → `/preview`（即時抽樣）→ `/process`（preprocess 任務）或 `/analyze`（analysis 任務：`tabular_profile | image_quality`，實作在 `trainer/trainer/analysis/`）；上傳只在 `DATA_ROOT/tools/<id>/`（無資料庫列），建任務時移進任務 input；前處理結果 `GET /jobs/{id}/download` 交付一次即刪
- GPU 共用是**實測模式**：`services/gpu.py` 用 pynvml 實際用量 + 暖機期（`GPU_WARMUP_S`）的「申請 − 實測」；不要改回以申請量保留
- 所有環境變數檔與變數清單：`docs/ENVIRONMENT.md`

## 全域工作規則

1. 先讀再做：動 UI 前讀 `DESIGN.md`；動 API / DB 前讀 `docs/ARCHITECTURE.md`、`docs/DATABASE.md`；新增模型家族依序改 `backend/app/catalog/model_catalog.yaml`（含 `weights`）→ `docs/MODEL_CATALOG.md` → `trainer/trainer/models/registry.py` 與實作 → 測試（`test_catalog.py` / `test_registry.py` 會比對）。
2. 大改動（新頁面、新 router、schema 變更、排程邏輯）先列計畫：檔案清單 + 資料流 + 要跑的測試，再動手。
3. 後端是權限的唯一真相：授權在 FastAPI dependency 判斷；前端只負責隱藏 UI。
4. 不留存使用者資料：上傳檔只能寫到 `DATA_ROOT/uploads/` 與 Job 的 `input/`，Job 結束（任何狀態）必刪；使用者 MinIO / URL 的憑證只在 Job 容器的環境變數出現，不回前端、不進 log。
5. 秘密只從環境變數讀（Keycloak client secret、DB、`DATASET_SECRET_KEY`、`JOB_TOKEN_SECRET`）；log 不得含 token / 密碼。
6. 長任務（訓練、推論）一律非同步：API 只建立 `jobs` row 並回 202，由 scheduler 依 `queue_rank` 與總資源池執行；每個 Job 都要有 log 檔與即時事件，缺一不可。
7. 管理員能力不能繞過：總資源池、佇列重排、強制中斷 / 重啟、GPU 重置、刪專案 / 討論串都只走對應 API、以 `require_perm` 判斷並寫 `audit_logs`；superadmin 與 admin 的差別見 `app/core/permissions.py`，前端只能隱藏按鈕。
8. 提交前必跑：前端 `npm run lint && npm run typecheck`；後端 `uv run ruff check . && uv run pytest`；有 UI 變更再跑 `python3 scripts/design_lint.py frontend/src`。
9. Next.js 16：用 `src/proxy.ts`（不是 `middleware.ts`）；`params`、`searchParams`、`cookies()`、`headers()` 都要 `await`；不用 Pages Router；Tailwind v4 用 CSS `@theme`，不建 `tailwind.config.js`。
10. Commit 用 Conventional Commits + scope：`feat(frontend): …`、`fix(backend): …`、`docs: …`、`chore(infra): …`。
11. 語言：程式碼、識別字、commit、API 欄位用英文；UI 文案與文件用繁體中文。
12. 不確定時選最簡單、單機可跑、可觀測（有 log、有狀態）的做法；v1 不做多節點、不做 Kubernetes。
13. 資源限制要在程序內也成立：runner 設齊 `*_NUM_THREADS` / `LOKY_MAX_CPU_COUNT`，trainer 啟動時 `limits.apply_from_env`（threadpoolctl + torch threads + 共用 GPU 的 memory fraction）並把實際限制印進 log；新增用原生函式庫的模型時 `n_jobs` 取 `ctx.cpu`。
14. 排程器每 `USAGE_SAMPLE_INTERVAL_S` 秒寫一筆 `resource_samples`（節點 / 資源池 / 各專案配置與實測），管理員「使用率歷史」頁讀 `GET /admin/usage?range=`；取樣與清理都在 `app/scheduler/loop.py`，不要在 API 程序另外採樣。
15. 預訓練權重不自動下載：trainer 只透過 `ctx.weight(id)` 從模型庫取檔，runner 設 `HF_HUB_OFFLINE=1` 等離線變數；需要新權重先在 yaml 的 `weights` 登記（`kind: file | hf_repo`），管理員再經 `/admin/model-zoo` 帶進來。Job 永遠是主機子程序，不要再引入任務容器。
16. 前處理步驟只在 `libs/preprocess` 定義（一個 op = 一個類別，含參數規格與可選的 fit 狀態），backend 與 trainer 都從那裡 import；新增步驟要能在上傳預覽中套用、能序列化狀態、推論能 replay。

17. 環境變數範本（`infra/systemd/*.env.example`、`backend/.env.example`）的註解一律獨立成行（systemd 會把行尾 `# …` 當成值）；新增 `Settings` 欄位要同時加到兩份範本與 `docs/ENVIRONMENT.md`（`backend/tests/test_infra_contracts.py` 會檢查）。伺服器不用 uv：改了依賴就跑 `scripts/export_requirements.sh`。
18. 任何寫入由不可信名稱決定路徑的地方（zip 成員、MinIO 物件、URL 檔名、trainer 回報的路徑）都走 `safe_join` / `job_relpath`；任務子程序的環境只從 `runner.ENV_PASSTHROUGH` 白名單繼承，不要把伺服器 secret 傳進去。

## 文件地圖

- `DESIGN.md`：設計系統（token、字體、元件、版面、dark mode、檢查清單）。前端設計一致性的真相來源。
- `docs/ARCHITECTURE.md`：系統架構、認證流程、申請審批、資料不留存政策、Job 生命週期與佇列、資源池、log、儲存配置、API 清單、部署。
- `docs/DATABASE.md`：資料表定義、索引、狀態機。
- `docs/MODEL_CATALOG.md`：資料類型 × 任務 × 模型 × 推論模式 × AutoML 搜尋空間 × 模型庫；也是給使用者看的 SOP 底稿。
- `docs/USE_CASES.md`：半導體 / 電子製造的機台資料 → 模型 → 推論目的（OCD 光譜鑑別器、TEM few-shot bin code、PatchCore、FDC、WAT…）。
- `docs/GETTING_STARTED.md`：pull 之後從零啟動前端、基礎服務、後端的 SOP；`docs/screenshots/e2e/`：實際串接 backend 的端到端截圖（`captions.json` 有每張說明）；`docs/manuals/`：使用者手冊（DOCX / PDF，由 `scripts/build_manual.js` 產生）與串接測試報告 PDF。
- `docs/ENVIRONMENT.md`：五個環境變數檔（backend/.env、frontend/.env.local、infra/.env、/etc/qr-ai-lab/qrlab.env、/etc/qr-ai-lab/frontend.env）與每個變數的意義。
- `docs/ROADMAP.md`：已知缺口與改善方向（審視清單）。
- `.claude/rules/frontend.md`、`backend.md`、`database.md`：動到對應路徑時自動載入的細部慣例。
