# 從零啟動（本地開發 SOP）

從 `git pull` 到前端、基礎服務、（未來的）後端全部跑起來。每一節都可以獨立執行；前端目前用假資料，不需要後端就能看完整 UI；後端用 SQLite 與內建帳號就能跑完整流程。

## 0. 前置需求

| 工具 | 版本 | 檢查指令 | 備註 |
|---|---|---|---|
| Git | 任意 | `git --version` | |
| Node.js | ≥ 20.9，建議 22 LTS | `node --version` | Next.js 16 要求；用 [nvm](https://github.com/nvm-sh/nvm) 或 [fnm](https://github.com/Schniz/fnm) 管理 |
| npm | ≥ 10 | `npm --version` | 隨 Node 安裝；本專案用 npm，不用 pnpm / yarn |
| Python | ≥ 3.12 | `python3 --version` | backend、trainer（uv 會自行管理版本）、`scripts/*.py` |
| uv | 最新 | `uv --version` | backend 套件管理：`curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker Engine + Compose v2 | 最新 | `docker compose version` | MariaDB、Redis；伺服器上也跑 backend / scheduler |
| NVIDIA driver + NVIDIA Container Toolkit | 配合 GPU | `nvidia-smi`、`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` | 只有 GPU 伺服器需要（跑訓練容器） |
| Playwright Chromium | 隨 `playwright` 套件 | `cd frontend && npx playwright install chromium` | 只有要跑截圖 / 設計檢查時需要 |

## 1. 取得程式碼

```bash
git clone https://github.com/khc0704/qr-ai-lab.git
cd qr-ai-lab
git checkout <分支>          # 例如 main 或 claude/beautiful-pasteur-i6dgoc
```

## 2. 前端（Next.js 16）

```bash
cd frontend
npm ci                        # 依 package-lock.json 安裝（第一次或 lock 變更後）
npm run dev                   # http://localhost:3000，Turbopack，熱更新
```

- 預設登入身分是假資料的管理員「王小明」，所有頁面（含管理員區）都看得到；Keycloak 接上後才會有真正的登入。
- 常用指令：

| 指令 | 用途 |
|---|---|
| `npm run lint` | ESLint（Next.js 16 已移除 `next lint`） |
| `npm run typecheck` | 產生路由型別並做 TypeScript 檢查 |
| `npm run format` | Prettier（含 Tailwind class 排序） |
| `npm run build && npm run start` | 正式建置與啟動（http://localhost:3000） |
| `npm run screenshots` | 對所有主要頁面截圖到 `docs/screenshots/`（需先啟動 dev 或 start，並已安裝 Playwright Chromium） |
| `python3 ../scripts/design_lint.py src` | 設計 token 檢查（從 repo 根目錄則是 `python3 scripts/design_lint.py frontend/src`） |

- 改 UI 前先讀 `DESIGN.md`；Claude Code 使用者會自動載入 `.claude/rules/frontend.md`，而且 `.claude/settings.json` 的 hook 會在每次寫檔後跑設計檢查。

## 3. 基礎服務（MariaDB、Redis）

```bash
cp infra/.env.example infra/.env     # 填入 MARIADB_ROOT_PASSWORD、MARIADB_PASSWORD
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
docker compose -f infra/docker-compose.yml ps                      # 兩個 service 都應為 healthy
docker compose -f infra/docker-compose.yml exec mariadb mariadb -uqr -p qr_ai_lab -e "SELECT VERSION();"
docker compose -f infra/docker-compose.yml exec redis redis-cli ping
```

- 資料存在 docker volume（`qr-ai-lab_mariadb-data`、`qr-ai-lab_redis-data`）。
- 停止：`docker compose -f infra/docker-compose.yml down`；連資料一起刪：加 `-v`。
- 第一次啟動會執行 `infra/mariadb/init/01_create.sql`（字集與測試用資料庫）。

## 4. 後端（FastAPI）+ 排程器

### 4.1 最快的路：SQLite + 內建帳號（不需要第 3 節）

```bash
cd backend
cp .env.example .env                  # AUTH_SECRET / JOB_TOKEN_SECRET 改掉即可；其餘預設可用
uv sync                               # 建立 .venv 並安裝依賴（Python ≥ 3.12）
uv run uvicorn app.main:app --reload  # http://localhost:8000/docs
```

- `APP_ENV=dev` 時啟動會自動建表（SQLite `backend/dev.db`）並建立兩個帳號：`admin / admin1234`、`user / user1234`（`SEED_*` 可改）。
- 登入拿 token，之後所有 API 帶 `Authorization: Bearer <token>`：

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin1234"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/api/v1/me -H "Authorization: Bearer $TOKEN"
curl -s localhost:8000/api/v1/catalog -H "Authorization: Bearer $TOKEN" | head -c 400
curl -s localhost:8000/api/v1/admin/model-zoo -H "Authorization: Bearer $TOKEN"
```

- 流程：`user` 送出專案申請（`POST /project-requests`）→ `admin` 核准（`POST /project-requests/{id}/approve`，給 slug 與配額）→ 專案內上傳檔案（`POST /projects/{slug}/uploads`）→ 建 Job（`POST /projects/{slug}/jobs`，回 202）→ 排程器執行 → `GET /jobs/{id}`、`/logs`、`/events`（SSE）、`/artifacts`。`/docs` 有完整清單。

### 4.2 排程器（跑 Job 的那個程式）

```bash
cd trainer && uv sync && cd ../backend        # 第一次：建立 trainer 的 venv（CPU 家族：sklearn / XGBoost / Optuna）
uv run python -m app.scheduler                # 另一個終端；每 3 秒：回收已結束的 Job → 依佇列與資源池啟動新 Job
```

- 開發機預設 `JOB_RUNNER=subprocess`：直接用 `../trainer/.venv` 執行 `python -m trainer run`（無隔離，只適合 CPU 家族）。
- GPU 伺服器用 `JOB_RUNNER=docker`：先建 image `docker build -t qr-ai-lab/trainer:dev -f infra/trainer/Dockerfile .`（context 是 repo 根目錄，因為會一起裝 `libs/preprocess`），排程器以硬化容器（唯讀 rootfs、cap_drop ALL、只掛該 Job 的目錄）啟動，並用 `CUDA_VISIBLE_DEVICES` 指定 GPU。
- 資源池預設 = 偵測到的 GPU / CPU / 記憶體；管理員可在 `PUT /admin/settings/resource-pool` 調整（或 UI 管理員頁）。
- 深度學習家族在開發機測試：`cd trainer && uv sync --extra dl`（會抓 CUDA 版 torch，很大）；或只裝 CPU torch：`uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu` 再 `uv pip install --python .venv/bin/python transformers pillow`。

### 4.3 模型庫（預訓練權重；伺服器不連網）

```bash
pip install pyyaml huggingface_hub                       # 在「有網路」的機器
python3 scripts/fetch_model_zoo.py --dest ./model_zoo    # 下載 yaml 列出的全部權重並產生 manifest.json
python3 scripts/fetch_model_zoo.py --dest ./model_zoo --only yolo11s dinov2-small
# 複製 model_zoo/ 到伺服器的 MODEL_ZOO_ROOT（預設 DATA_ROOT/model_zoo），然後驗證：
cd backend && uv run python -m app.cli model-zoo --verify
```

sklearn / XGBoost 家族不需要權重；YOLO `pretrained=false` 也不需要。缺權重的 Job 會失敗並在 log 說明缺哪個檔。

### 4.4 MariaDB（正式環境）

```bash
# backend/.env：DATABASE_URL=mariadb+asyncmy://qr:<密碼>@localhost:3306/qr_ai_lab、REDIS_URL=redis://localhost:6379/0、APP_ENV=prod
uv run alembic upgrade head           # 建表（需要第 3 節的 MariaDB）
uv run python -m app.cli seed         # 建立 admin / user（密碼取自 SEED_*）
uv run python -m app.cli create-user --username alice --password '…' --email alice@example.com --role user
```

`APP_ENV=prod` 不會自動建表；Redis 讓 SSE 事件在多個 backend 程序間共享（未設定時用單程序記憶體 bus）。

### 4.5 測試與檢查

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest          # 含排程器（假 runner）與端到端（真的 trainer 子程序）
cd trainer && uv run ruff check . && uv run pytest                                          # 模型家族、registry 與 yaml 對照、runtime
cd libs/preprocess && ../../trainer/.venv/bin/python -m pytest                            # 共用前處理套件（backend 與 trainer 都以 path dependency 安裝）
QR_TEST_ZOO=/path/to/zoo uv run pytest tests/test_yolo_cpu.py                              # trainer：YOLO 從 yolo11n.pt 微調（CPU）
uv run python -m trainer check                                                              # 這個環境能跑哪些家族
```

### 4.6 docker compose 一次全起（伺服器）

```bash
cp infra/.env.example infra/.env   # 填密碼、DATA_ROOT_HOST、AUTH_SECRET、JOB_TOKEN_SECRET、DATASET_SECRET_KEY
docker build -t qr-ai-lab/trainer:dev -f infra/trainer/Dockerfile .
docker compose -f infra/docker-compose.yml --env-file infra/.env --profile app build
docker compose -f infra/docker-compose.yml --env-file infra/.env --profile app run --rm backend alembic upgrade head
docker compose -f infra/docker-compose.yml --env-file infra/.env --profile app run --rm backend python -m app.cli seed
docker compose -f infra/docker-compose.yml --env-file infra/.env --profile app up -d
```

- 前端接上後端：在 `frontend/.env.local` 設 `BACKEND_URL=http://localhost:8000`，並把 `src/lib/api/index.ts` 的假資料換成 fetch（頁面不用改）；這一步尚未完成。

### 4.7 使用手冊（DOCX / PDF）

```bash
node scripts/build_manual.js                                                   # docs/manuals/QR-AI-Lab-使用手冊.docx
soffice --headless --convert-to pdf --outdir docs/manuals "docs/manuals/QR-AI-Lab-使用手冊.docx"
```

## 5. Keycloak（外部）

公司既有的 Keycloak。需要向管理 Keycloak 的人取得：realm 名稱、client id / secret（confidential client，Authorization Code + PKCE）、允許的 redirect URI `http://localhost:3000/api/auth/callback/keycloak`、realm role `admin` 與 `user`。填入 `frontend/.env.local`（`AUTH_*`）與 backend 的 `KEYCLOAK_*`。接上前所有身分都是假資料。

## 6. 推薦的日常流程

```bash
git pull
cd frontend && npm ci && npm run dev          # 終端 1：前端
cd backend && uv sync && uv run uvicorn app.main:app --reload   # 終端 2：後端（SQLite）
cd backend && uv run python -m app.scheduler  # 終端 3：排程器（subprocess runner）
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d   # 需要 MariaDB / Redis 時
# 改完 UI
cd frontend && npm run lint && npm run typecheck && python3 ../scripts/design_lint.py src
# 改完後端 / trainer
cd backend && uv run ruff check . && uv run pytest
cd trainer && uv run ruff check . && uv run pytest
```

## 7. 常見問題

- **`EADDRINUSE: 3000`**：有別的 dev server 在跑；`npm run dev -- -p 3001` 換 port，或關掉舊的。
- **Node 版本太舊**：Next.js 16 需要 ≥ 20.9；`nvm install 22 && nvm use 22`。
- **Turbopack 快取怪異**：`rm -rf frontend/.next` 後重跑。
- **`npm ci` 失敗提到 lock 不一致**：確認用的是 npm 10 以上，且沒有用 pnpm / yarn 動過 `node_modules`。
- **Playwright 找不到瀏覽器**：`cd frontend && npx playwright install chromium`；或設 `CHROMIUM_PATH=/path/to/chrome` 再跑 `npm run screenshots`。
- **MariaDB 一直不 healthy**：第一次初始化要 20–40 秒；看 `docker compose -f infra/docker-compose.yml logs mariadb`。
- **Windows**：建議在 WSL2 內操作（Docker Desktop + WSL 整合），避免路徑與換行問題。
