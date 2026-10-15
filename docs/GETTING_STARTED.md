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

- `APP_ENV=dev` 時啟動會自動建表（SQLite `backend/dev.db`）並建立三個帳號：`superadmin / superadmin1234`（什麼都能改：資源池、配額、刪專案、模型庫、使用者角色、GPU 重置）、`admin / admin1234`（日常營運：審核、中斷 / 重啟 / 重排任務、討論區）、`user / user1234`（沒有管理操作）。密碼由 `SEED_*_PASSWORD` 改；角色可在 **管理 → 使用者** 調整或 `uv run python -m app.cli set-role --username alice --role admin`。
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
- CPU 限制對原生函式庫也有效：runner 把 `OMP / MKL / OPENBLAS / NUMEXPR / TBB / NUMBA / LOKY_MAX_CPU_COUNT / TORCH_NUM_THREADS…` 全設成申請的核數，trainer 啟動時再用 threadpoolctl + torch 夾一次並把實際 affinity / 執行緒數印進任務 log（搜 `limits:`）。所以 sklearn 的 TSNE / HistGradientBoosting、numpy BLAS、torch 都只會用到分到的核心，不會把 88 核全吃掉。
- GPU：`CUDA_VISIBLE_DEVICES` 指定。任務可填「每張 GPU 需要的顯存」→ 多個任務依 pynvml 的剩餘顯存共用一張（資源池的「依顯存共用 GPU」開關；子程序以 `set_per_process_memory_fraction` 自限）；沒填就要整張空卡（`GPU_BUSY_THRESHOLD`）。Dashboard 的 GPU 卡片顯示顯存 / 保留量 / 任務，superadmin 可「重置」（中斷本系統任務 → kill 所有程序 → `GPU_RESET_COMMAND`）。backend venv 請裝 `--extra gpu`（nvidia-ml-py）。
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

### 4.7 使用率歷史與資料前處理服務

- **管理 → 使用率歷史**（`/admin/usage`）：排程器每 30 秒（`USAGE_SAMPLE_INTERVAL_S`）寫一筆 `resource_samples`；頁面可切 1h / 6h / 24h / 7d / 30d，分母可切「專案配額 / 資源池 / 系統總量」；下方表格是各專案在該區間的時間加權配置（相對分母的百分比）與實測 CPU / 記憶體。保留 `USAGE_RETENTION_DAYS`（預設 90 天）。
- **資料前處理**（`/tools/preprocess`，所有登入者）：不需要專案；選資料類型 → 上傳 → 挑步驟 → 抽樣預覽（即時，只取樣）→ 「建立前處理任務」。整檔處理是個人工作區裡的任務（全域佇列、CPU / 記憶體配額、即時 log），完成後在任務頁下載 zip（`processed.*`、`pipeline.json`、`summary.json`）；下載一次就刪，沒下載的在「工具預設」的保留時間（預設 24 小時）後刪。
- **資料分析**（`/tools/analyze`）：表格資料探勘（相關性、VIF 共線性、對目標的解釋力、建議）與影像品質分析（zip 子資料夾 = 機台 / 條件；最會飄的 IQA 指標、embedding 相似度與散佈、離群影像）。同樣是任務，報告在任務頁。
- 個人工作區：第一次用工具時自動建立（`ws-<帳號>`），配額由 Dashboard 的「工具預設」決定，管理員可在專案配額頁個別調整。

### 4.8 使用手冊（DOCX / PDF）

```bash
node scripts/build_manual.js                                                   # docs/manuals/QR-AI-Lab-使用手冊.docx
soffice --headless --convert-to pdf --outdir docs/manuals "docs/manuals/QR-AI-Lab-使用手冊.docx"
```

## 5. Keycloak（正式環境的登入）

dev 用本地帳號（`AUTH_MODE=local`）；正式環境把前後端都切到 `AUTH_MODE=keycloak`，不用改任何業務表。

1. 向 Keycloak 管理員要一個 **confidential client**（Standard flow / Authorization Code + PKCE）：
   - Valid redirect URIs：`https://<你的網址>/api/auth/callback/keycloak`
   - Valid post logout redirect URIs：`https://<你的網址>/login`
   - 角色：realm role 或這個 client 的 client role 皆可，例如 `superadmin`、`admin`（名稱可自訂，用 `KEYCLOAK_ROLE_MAP` 對應）。沒有任何對應 role 的人登入後是 `user`。
2. 前端（`/etc/qr-ai-lab/frontend.env`，或開發時 `frontend/.env.local`）：
   ```
   AUTH_MODE=keycloak
   AUTH_SECRET=<openssl rand -base64 32>
   AUTH_URL=https://<你的網址>
   AUTH_KEYCLOAK_ID=<client id>
   AUTH_KEYCLOAK_SECRET=<client secret>
   AUTH_KEYCLOAK_ISSUER=https://<sso>/realms/<realm>
   ```
3. backend（`/etc/qr-ai-lab/qrlab.env` 或 `backend/.env`）：
   ```
   AUTH_MODE=keycloak
   KEYCLOAK_ISSUER=https://<sso>/realms/<realm>        # 要和 token 的 iss 一字不差
   KEYCLOAK_CLIENT_ID=<client id>
   KEYCLOAK_ROLE_MAP=superadmin:superadmin,admin:admin  # <Keycloak role>:<系統角色>
   SUPERADMIN_USERNAMES=<你的帳號>                        # 第一位 superadmin；之後其他人在 UI 調整即可
   ```
   `KEYCLOAK_AUDIENCE` 只有在 Keycloak 加了 audience mapper 時才設。
4. 重啟三個服務。登入頁變成「使用公司帳號登入（Keycloak）」；第一次登入會自動在 `users` 建立帳號（同名的本地帳號會被接管）。切換期間要保留本地登入的話前端設 `AUTH_LOCAL_FALLBACK=1`。
5. 沒有公司 Keycloak 也能先測整條流程：`backend/.venv/bin/python scripts/fake_keycloak.py` 跑一個模擬 realm（`http://127.0.0.1:8089/realms/qr`，client `qr-ai-lab` / `dev-secret`，帳號 superadmin / admin / user / alice），前後端照上面設定指向它，再 `cd frontend && npm run screenshots:keycloak` 看截圖。

角色與權限的完整表在 `docs/ARCHITECTURE.md` §2.3；UI 只負責隱藏按鈕，真正的判斷在 backend 的 `require_perm`。

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

環境變數檔案的完整清單與每個變數的意義見 `docs/ENVIRONMENT.md`。

## 7. WSL 與 Ubuntu：完整的 dev / prod 啟動

### 7.1 開發（WSL2 或 Ubuntu 桌機；本地帳號、SQLite、內嵌排程器、不需要 Docker）

```bash
# 一次性
sudo apt install -y python3.12 python3.12-venv nodejs npm git     # Node ≥ 20.9（建議 nvm install 22）；uv：curl -LsSf https://astral.sh/uv/install.sh | sh
git clone <repo> && cd qr-ai-lab
cd trainer && uv sync && cd ..                      # trainer venv（CPU 家族）；要 GPU / 深度學習：uv sync --extra dl
cd backend && cp .env.example .env && uv sync && cd ..   # .env 預設 AUTH_MODE=local、SQLite、SCHEDULER_EMBEDDED=true
cd frontend && cp .env.local.example .env.local && npm ci && cd ..   # AUTH_MODE=local、BACKEND_URL=http://localhost:8000
# 每天
cd backend && uv run uvicorn app.main:app --reload   # 終端 1：API + 內嵌排程器 + 使用率取樣（http://localhost:8000/docs）
cd frontend && npm run dev                           # 終端 2：http://localhost:3000，superadmin / admin / user
```

- WSL2 專屬：`/etc/wsl.conf` 加 `[boot]\nsystemd=true` 後 `wsl --shutdown`，排程器才能用 systemd cgroup（否則自動退到 subprocess + affinity + watchdog，功能一樣，只是記憶體上限靠 watchdog）；GPU 要 Windows 端的 NVIDIA driver（WSL 內不要另裝 driver），`nvidia-smi` 在 WSL 看得到就能用 `--extra dl` 的 CUDA torch。
- 要測「兩個程序 + Redis + MariaDB」的正式拓樸：`docker compose -f infra/docker-compose.yml --env-file infra/.env up -d`，backend `.env` 改 `DATABASE_URL=mariadb+asyncmy://…`、`REDIS_URL=redis://localhost:6379/0`、`SCHEDULER_EMBEDDED=false`，`uv run alembic upgrade head && uv run python -m app.cli seed`，再開第三個終端 `uv run python -m app.scheduler`。
- 要測 Keycloak：照 §5 第 5 點用假 Keycloak，或直接填公司的 realm。

### 7.2 正式（Ubuntu GPU 伺服器；Keycloak、MariaDB + Redis in Docker、三個 systemd 服務、nginx）

```bash
sudo git clone <內部 git> /opt/qr-ai-lab && cd /opt/qr-ai-lab
cp infra/.env.example infra/.env                      # DOCKER_REGISTRY=公司 image 鏡像、DB 密碼
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d      # 只有 mariadb、redis
PIP_INDEX_URL=https://<pypi 鏡像>/simple NPM_REGISTRY=https://<npm 鏡像> ./infra/install.sh   # 第一次：建 qrlab 使用者、venv、build、複製兩個 env 範本後停下
sudo nano /etc/qr-ai-lab/qrlab.env      # DATABASE_URL、REDIS_URL、AUTH_MODE=keycloak、KEYCLOAK_*、SUPERADMIN_USERNAMES、AUTH_SECRET、JOB_TOKEN_SECRET、DATASET_SECRET_KEY、MODEL_ZOO_*、GPU_RESET_COMMAND
sudo nano /etc/qr-ai-lab/frontend.env   # AUTH_MODE=keycloak、AUTH_SECRET、AUTH_URL、AUTH_KEYCLOAK_ID / SECRET / ISSUER
./infra/install.sh                      # 第二次：alembic upgrade head、seed、啟動 qrlab-backend / qrlab-scheduler / qrlab-frontend
sudo cp infra/nginx/qr-ai-lab.conf /etc/nginx/sites-available/qr-ai-lab && sudo ln -s ../sites-available/qr-ai-lab /etc/nginx/sites-enabled/ && sudo nginx -s reload
```

- 之後更新：`git pull && ./infra/install.sh --update`（重 sync venv、重建前端、migration、重啟三個服務；執行中的任務不受影響）。
- 上線檢查：Dashboard「任務執行方式」是 systemd 且記憶體 / CPU 都是 cgroup；GPU 卡片列出所有卡；資源池勾選要開放的 GPU；用 `SUPERADMIN_USERNAMES` 的帳號登入一次，再到 **使用者** 頁把其他人設成 admin。
- dev 與 prod 的實質差異只有：帳號來源（本地 / Keycloak）、DB（SQLite / MariaDB）、排程器是否獨立程序（內嵌 / 獨立 + Redis）、runner（看 systemd 是否可用）。任務本身、權限判斷、資料不留存政策在兩邊完全相同。

## 8. 常見問題

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
