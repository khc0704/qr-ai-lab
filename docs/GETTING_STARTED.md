# 從零啟動（本地開發 SOP）

從 `git pull` 到前端、基礎服務、後端全部跑起來。前端已實際串接 backend（登入、申請、任務、即時 log 都打真的 API），所以要看完整 UI 需要先把後端跑起來（§4.1 用 SQLite 與內建帳號即可，不需要 MariaDB）。

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

- 前端透過 `BACKEND_URL`（預設 `http://localhost:8000`，可放在 `frontend/.env.local`）呼叫 backend；先照 §4.1 啟動後端，再用內建帳號登入：`admin / admin1234`（管理員，看得到管理員區）或 `user / user1234`（一般使用者）。
- 登入後 token 存在 httpOnly cookie `qr_token`（瀏覽器拿不到），所有資料都由 Server Component / Server Action 在伺服器端帶 `Authorization` 去打 backend；上傳、SSE、下載走 `src/app/api/*` 的 Route Handler 代理。
- 常用指令：

| 指令 | 用途 |
|---|---|
| `npm run lint` | ESLint（Next.js 16 已移除 `next lint`） |
| `npm run typecheck` | 產生路由型別並做 TypeScript 檢查 |
| `npm run format` | Prettier（含 Tailwind class 排序） |
| `npm run build && npm run start` | 正式建置與啟動（http://localhost:3000） |
| `npm run screenshots` | 端到端串接測試 + 截圖（見 §4.8；需要 backend、排程器、前端都已啟動） |
| `npm run screenshots:report` | 把截圖整理成 `docs/manuals/QR-AI-Lab-串接測試報告.pdf` |
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
- `.env.example` 預設 `SCHEDULER_EMBEDDED=true`：排程器迴圈跑在這個程序裡，不用 Redis、不用第二個終端，任務頁的即時 log 照常。要測兩個程序的正式拓樸再照 §4.2 分開跑。
- 登入拿 token，之後所有 API 帶 `Authorization: Bearer <token>`：

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin1234"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/api/v1/me -H "Authorization: Bearer $TOKEN"
curl -s localhost:8000/api/v1/catalog -H "Authorization: Bearer $TOKEN" | head -c 400
curl -s localhost:8000/api/v1/admin/model-zoo -H "Authorization: Bearer $TOKEN"
```

- 流程：`user` 送出專案申請（`POST /project-requests`）→ `admin` 核准（`POST /project-requests/{id}/approve`，給 slug 與配額）→ 專案內上傳檔案（`POST /projects/{slug}/uploads`）→ 建 Job（`POST /projects/{slug}/jobs`，回 202）→ 排程器執行 → `GET /jobs/{id}`、`/logs`、`/events`（SSE）、`/artifacts`。`/docs` 有完整清單。

### 4.2 排程器與任務執行方式（沒有容器）

```bash
cd trainer && uv sync && cd ../backend        # 第一次：建立 trainer 的 venv（CPU 家族：sklearn / XGBoost / Optuna）
# 分開跑（正式拓樸）：backend 與排程器各一個程序，兩邊都設 REDIS_URL 讓即時事件互通
REDIS_URL=redis://localhost:6379/0 SCHEDULER_EMBEDDED=false uv run uvicorn app.main:app --reload
REDIS_URL=redis://localhost:6379/0 uv run python -m app.scheduler
```

- 每個任務 = `trainer/.venv/bin/python -m trainer run` 的主機子程序，環境變數帶 `JOB_*`、`CUDA_VISIBLE_DEVICES` 與離線旗標（`HF_HUB_OFFLINE=1`、`YOLO_OFFLINE=1`…）。
- `JOB_RUNNER=auto`（預設）：啟動時試跑 `systemd-run --user --scope`，成功就用 **systemd**（cgroup 強制 MemoryMax / CPUQuota / AllowedCPUs，`systemctl stop` 殺整棵程序樹，排程器重啟後靠 unit 名接回）；失敗就用 **subprocess**（process group、`cpu_affinity` 釘核心、執行緒數上限，記憶體由排程器每 3 秒的 watchdog 監看，超過申請量就停止並寫明原因）。管理員 Dashboard 的「任務執行方式」會顯示實際偵測結果。
- systemd 模式的前提：跑排程器的使用者 `loginctl enable-linger`，而且 user slice 有委派 `cpu memory pids cpuset`（`cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.subtree_control`）。WSL2 要在 `/etc/wsl.conf` 開 `systemd=true`。
- GPU：`CUDA_VISIBLE_DEVICES` 指定；啟動前用 pynvml 檢查那顆 GPU 顯存是否被別的程序占用（`GPU_BUSY_THRESHOLD`），忙就先等。backend venv 請裝 `--extra gpu`（nvidia-ml-py）。
- 深度學習家族：`cd trainer && uv sync --extra dl`（CUDA 版 torch，走公司 PyPI 鏡像：`UV_INDEX_URL=https://mirror.example.com/pypi/simple`）；開發機只想裝 CPU torch 見 §7。

### 4.3 模型庫（預訓練權重；伺服器不連外）

- 管理員登入後到 **管理 → 模型庫**（`/admin/model-zoo`）：每個權重都可以用三種方式帶進來，匯入時比對目錄登記的 sha256、記進 `MODEL_ZOO_ROOT/manifest.json` 與稽核紀錄：
  1. 瀏覽器上傳（單檔權重如 YOLO `.pt` 直接傳；Hugging Face 類型傳整個 snapshot 資料夾的 zip）。
  2. 伺服器路徑：先把檔案放到 `MODEL_ZOO_IMPORT_ROOT`（NAS、USB 掛載點），頁面填相對路徑。
  3. 內網 URL：公司鏡像 / 檔案伺服器，主機要在 `MODEL_ZOO_ALLOWED_HOSTS`。
- 有網路的機器可以先用 `python3 scripts/fetch_model_zoo.py --dest ./model_zoo` 把全部抓好、整個資料夾放到傳輸資料夾再逐一匯入，或直接複製到 `MODEL_ZOO_ROOT`（manifest 相容）。
- 權重缺少時：精靈的模型卡片會標「缺權重」，建立任務會被拒絕（`WEIGHTS_MISSING`）；AutoML 會自動跳過缺權重的候選。sklearn / XGBoost / 影像品質 / 光譜 MAE 家族不需要權重。
- 命令列檢查：`cd backend && uv run python -m app.cli model-zoo --verify`。

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

### 4.6 正式安裝（Ubuntu GPU 伺服器，不連外、有 PyPI / npm / image 鏡像）

```bash
sudo mkdir -p /opt && sudo git clone <內部 git> /opt/qr-ai-lab && cd /opt/qr-ai-lab
cp infra/.env.example infra/.env && docker compose -f infra/docker-compose.yml --env-file infra/.env up -d   # mariadb、redis
PIP_INDEX_URL=https://mirror.example.com/pypi/simple NPM_REGISTRY=https://mirror.example.com/npm ./infra/install.sh
sudo nano /etc/qr-ai-lab/qrlab.env     # DATABASE_URL、AUTH_SECRET、JOB_TOKEN_SECRET、DATASET_SECRET_KEY、MODEL_ZOO_*、PUBLIC_URL
./infra/install.sh                     # 第二次：migration、seed、啟動 qrlab-backend / qrlab-scheduler / qrlab-frontend
sudo cp infra/nginx/qr-ai-lab.conf /etc/nginx/sites-available/qr-ai-lab && sudo ln -s ../sites-available/qr-ai-lab /etc/nginx/sites-enabled/ && sudo nginx -s reload
```

- `install.sh` 做的事：建 `qrlab` 使用者並 `enable-linger`、建 `/srv/qr-ai-lab/{data,transfer}`、backend / trainer 的 venv（`uv sync --frozen`，走鏡像）、`next build`、`alembic upgrade head` + `app.cli seed`、安裝三個 systemd service。`--update` 在 `git pull` 後重跑全部並重啟服務；執行中的任務不受影響（systemd scope 不是排程器的子程序）。
- 沒有 TLS 憑證前要在 `qrlab-frontend.service` 加 `Environment=COOKIE_SECURE=0`，否則登入 cookie 不會被瀏覽器保存。
- 上線後第一件事：Dashboard 看「任務執行方式」是不是 systemd 且記憶體 / CPU 都是 cgroup；`app.cli set-password` 改掉兩個預設密碼；在資源池勾選可用的 GPU。

### 4.7 使用手冊（DOCX / PDF）

```bash
node scripts/build_manual.js                                                   # docs/manuals/QR-AI-Lab-使用手冊.docx
soffice --headless --convert-to pdf --outdir docs/manuals "docs/manuals/QR-AI-Lab-使用手冊.docx"
```

## 5. Keycloak（外部）

公司既有的 Keycloak。需要向管理 Keycloak 的人取得：realm 名稱、client id / secret（confidential client，Authorization Code + PKCE）、允許的 redirect URI `http://localhost:3000/api/auth/callback/keycloak`、realm role `admin` 與 `user`。填入 `frontend/.env.local`（`AUTH_*`）與 backend 的 `KEYCLOAK_*`。接上前用 backend 的本地帳號（`AUTH_MODE=local`）。

## 6. 推薦的日常流程

```bash
git pull
cd frontend && npm ci && npm run dev          # 終端 1：前端（BACKEND_URL 預設 http://localhost:8000）
cd backend && uv sync && uv run uvicorn app.main:app --reload   # 終端 2：後端（SQLite + 內嵌排程器，任務直接用 trainer/.venv 跑）
# 要測正式拓樸（分開的排程器 + Redis）才需要終端 3：REDIS_URL=… uv run python -m app.scheduler
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d   # 需要 MariaDB / Redis 時（開發機通常不用）
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
- **登入後被導回 `/login?reason=expired`**：backend 沒啟動、`BACKEND_URL` 不對，或 token 已過期（`ACCESS_TOKEN_MINUTES`，預設 12 小時）。
- **任務頁看不到即時 log，重新整理才有**：backend 與排程器分開跑時沒有 `REDIS_URL`，事件只在各自記憶體裡；設 `REDIS_URL=redis://localhost:6379/0` 給兩邊，或用 `SCHEDULER_EMBEDDED=true` 讓排程器跑在 backend 內。
- **Dashboard 顯示 runner 是 subprocess 而不是 systemd**：`systemd-run --user --scope -p MemoryMax=64M -- /bin/true` 手動跑看錯誤；常見原因是沒有 `loginctl enable-linger`、`XDG_RUNTIME_DIR` 沒指到該使用者、或 WSL 沒開 systemd。subprocess 模式仍會釘核心並由 watchdog 管記憶體。
- **任務因「memory limit exceeded」失敗**：申請的記憶體不夠；在精靈的資源步驟調高，或請管理員調整專案配額。
- **開發機只想裝 CPU torch**：`cd trainer && uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu && uv pip install --python .venv/bin/python transformers pillow ultralytics`。
- **上傳預覽逾時（`PREVIEW_TIMEOUT`）**：預覽在 API 程序內以執行緒計算，預設 30 秒（`PREVIEW_TIMEOUT_S`）；縮小取樣數或先用較小的檔案試步驟。
- **MariaDB 一直不 healthy**：第一次初始化要 20–40 秒；看 `docker compose -f infra/docker-compose.yml logs mariadb`。
- **Windows**：建議在 WSL2 內操作（Docker Desktop + WSL 整合），避免路徑與換行問題。
