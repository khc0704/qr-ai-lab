# 從零啟動（本地開發 SOP）

從 `git pull` 到前端、基礎服務、後端全部跑起來。前端已實際串接 backend（登入、申請、任務、即時 log 都打真的 API），所以要看完整 UI 需要先把後端跑起來（§4.1 用 SQLite 與內建帳號即可，不需要 MariaDB）。

## 0. 前置需求

| 工具 | 版本 | 檢查指令 | 備註 |
|---|---|---|---|
| Git | 任意 | `git --version` | |
| Node.js | ≥ 20.9，建議 22 LTS | `node --version` | Next.js 16 要求；用 [nvm](https://github.com/nvm-sh/nvm) 或 [fnm](https://github.com/Schniz/fnm) 管理 |
| npm | ≥ 10 | `npm --version` | 隨 Node 安裝；本專案用 npm，不用 pnpm / yarn |
| Python | 3.12（≥ 3.12） | `python3.12 --version` | backend、trainer、`scripts/*.py`；伺服器要有 `python3.12-venv` |
| pip | 隨 Python | `python3.12 -m pip --version` | 全專案只用 venv + pip（`requirements*.txt`），沒有 uv / poetry；公司 proxy 設在 `/etc/pip.conf` |
| Docker Engine + Compose v2 | 最新 | `docker compose version` | 只跑 MariaDB、Redis（本地開發可不用，見 §4.1） |
| NVIDIA driver | 配合 GPU | `nvidia-smi` | 只有 GPU 伺服器需要；只要 driver，CUDA 函式庫隨 torch wheel 來，沒有容器、不需要 NVIDIA Container Toolkit |
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

- 資料存在**主機目錄**（bind mount，不是 docker volume）：`infra/.env` 的 `MARIADB_DATA_DIR` / `REDIS_DATA_DIR`，預設 `infra/data/mariadb`、`infra/data/redis`（已在 `.gitignore`；相對路徑以 `infra/` 為基準，正式環境建議寫絕對路徑如 `/srv/qr-ai-lab/mariadb`）。備份就是備份這兩個目錄。
- 停止：`docker compose -f infra/docker-compose.yml down`（資料留在目錄裡）；要清掉資料就刪那個目錄。舊版用的 named volume（`qr-ai-lab_mariadb-data`）：`install-01-docker.sh` 會在目錄還是空的時候自動把內容複製過來，之後再自行 `docker volume rm`。
- 第一次啟動會執行 `infra/mariadb/init/01_create.sql`（字集與測試用資料庫）。

## 4. 後端（FastAPI）+ 排程器

### 4.1 最快的路：SQLite + 內建帳號（不需要第 3 節）

```bash
cd backend
cp .env.example .env                  # AUTH_SECRET / JOB_TOKEN_SECRET 改掉即可；其餘預設可用
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # 建立 .venv 並安裝依賴（含 pytest / ruff）
.venv/bin/uvicorn app.main:app --reload  # http://localhost:8000/docs
```

pip 會讀 `/etc/pip.conf`（或 `~/.config/pip/pip.conf`）的公司 PyPI proxy；有網路的機器直接連 PyPI。

- `APP_ENV=dev` 時啟動會自動建表（SQLite `backend/dev.db`）並建立三個帳號：`superadmin / superadmin1234`（什麼都能改：資源池、配額、刪專案、模型庫、使用者角色、GPU 重置）、`admin / admin1234`（日常營運：審核、中斷 / 重啟 / 重排任務、討論區）、`user / user1234`（沒有管理操作）。密碼由 `SEED_*_PASSWORD` 改；角色可在 **管理 → 使用者** 調整或 `.venv/bin/python -m app.cli set-role --username alice --role admin`。
- `.env.example` 預設 `SCHEDULER_EMBEDDED=true`：排程器迴圈跑在這個程序裡，不用 Redis、不用第二個終端，任務頁的即時 log 照常。要測兩個程序的正式拓樸再照 §4.2 分開跑。
- 登入拿 token，之後所有 API 帶 `Authorization: Bearer <token>`：

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin1234"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/api/v1/me -H "Authorization: Bearer $TOKEN"
curl -s localhost:8000/api/v1/catalog -H "Authorization: Bearer $TOKEN" | head -c 400
curl -s localhost:8000/api/v1/admin/model-zoo -H "Authorization: Bearer $TOKEN"
```

- 流程：`user` 送出專案申請（`POST /projects`，專案立刻以 `pending` 建立）→ `admin` 核准（`POST /projects/{slug}/approve`，給配額）→ 專案內上傳檔案（`POST /projects/{slug}/uploads`）→ 建 Job（`POST /projects/{slug}/jobs`，回 202）→ 排程器執行 → `GET /jobs/{id}`、`/logs`、`/events`（SSE）、`/artifacts`。`/docs` 有完整清單。

### 4.2 排程器與任務執行方式（沒有容器）

```bash
cd trainer && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-torch.txt && .venv/bin/pip install -r requirements-dev.txt && cd ../backend   # 第一次：建立 trainer 的 venv（torch 先裝，依驅動選 index）（CPU 家族：sklearn / XGBoost / Optuna）
# 分開跑（正式拓樸）：backend 與排程器各一個程序，兩邊都設 REDIS_URL 讓即時事件互通
REDIS_URL=redis://localhost:6380/0 SCHEDULER_EMBEDDED=false .venv/bin/uvicorn app.main:app --reload
REDIS_URL=redis://localhost:6380/0 .venv/bin/python -m app.scheduler
```

- 每個任務 = `trainer/.venv/bin/python -m trainer run` 的主機子程序，環境變數帶 `JOB_*`、`CUDA_VISIBLE_DEVICES` 與離線旗標（`HF_HUB_OFFLINE=1`、`YOLO_OFFLINE=1`…）。
- `JOB_RUNNER=auto`（預設）：啟動時試跑 `systemd-run --user --scope`，成功就用 **systemd**（cgroup 強制 MemoryMax / CPUQuota / AllowedCPUs，`systemctl stop` 殺整棵程序樹，排程器重啟後靠 unit 名接回）；失敗就用 **subprocess**（process group、`cpu_affinity` 釘核心、執行緒數上限，記憶體由排程器每 3 秒的 watchdog 監看，超過申請量就停止並寫明原因）。管理員 Dashboard 的「任務執行方式」會顯示實際偵測結果。
- systemd 模式的前提：跑排程器的使用者 `loginctl enable-linger`，而且 user slice 有委派 `cpu memory pids cpuset`（`cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.subtree_control`）。WSL2 要在 `/etc/wsl.conf` 開 `systemd=true`。
- CPU 限制對原生函式庫也有效：runner 把 `OMP / MKL / OPENBLAS / NUMEXPR / TBB / NUMBA / LOKY_MAX_CPU_COUNT / TORCH_NUM_THREADS…` 全設成申請的核數，trainer 啟動時再用 threadpoolctl + torch 夾一次並把實際 affinity / 執行緒數印進任務 log（搜 `limits:`）。所以 sklearn 的 TSNE / HistGradientBoosting、numpy BLAS、torch 都只會用到分到的核心，不會把 88 核全吃掉。
- GPU：`CUDA_VISIBLE_DEVICES` 指定。任務可填「每張 GPU 需要的顯存」→ 多個任務依 pynvml 的剩餘顯存共用一張（資源池的「依顯存共用 GPU」開關；子程序以 `set_per_process_memory_fraction` 自限）；沒填就要整張空卡（`GPU_BUSY_THRESHOLD`）。Dashboard 的 GPU 卡片顯示顯存 / 保留量 / 任務，superadmin 可「重置」（中斷本系統任務 → kill 所有程序 → `GPU_RESET_COMMAND`）。backend venv 請裝 `--extra gpu`（nvidia-ml-py）。
- 深度學習家族：torch / torchvision 在 `trainer/requirements-torch.txt`，**先**裝它再裝 `requirements*.txt`（ultralytics / transformers 等）。index 寫在檔案裡（`--index-url https://download.pytorch.org/whl/cu126`，對應 CUDA 12.x 驅動），命令列不用、也不要再加 `--index-url`（requirements 檔裡的 index 會蓋過命令列的）；沒 GPU 用 `requirements-torch-cpu.txt`；13.x 驅動把檔案裡的 index 改成 `cu130`。主機能用的版本是 torch 2.9.x 與 ultralytics 8.1.x，所以 YOLO 家族是 **YOLOv8**（權重 `yolov8n/s/m[-seg|-cls].pt`；YOLO11 要 ultralytics 8.3 以上，這裡沒有）；trainer 在匯入 ultralytics 前設 `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`，因為 8.1 載入 checkpoint 沒帶 `weights_only`，torch ≥ 2.6 預設會拒絕。torch wheel 自帶 CUDA 函式庫（`nvidia-*` 套件是 torch 的依賴，不用也不該寫進 requirements），主機的 CUDA toolkit 不會被用到，只看驅動版本；伺服器上由 `install-02-backend.sh` 以 pip 從 `trainer/requirements.txt` 安裝（含 dl）；開發機只想裝 CPU torch 見 §7。

### 4.3 模型庫（預訓練權重；伺服器不連外）

- 管理員登入後到 **管理 → 模型庫**（`/admin/model-zoo`）：每個權重都可以用三種方式帶進來，匯入時比對目錄登記的 sha256、記進 `MODEL_ZOO_ROOT/manifest.json` 與稽核紀錄：
  1. 瀏覽器上傳（單檔權重如 YOLO `.pt`、TabPFN `.ckpt` 直接傳；Hugging Face snapshot 類型（DINOv2 / DINOv3、BERT、Qwen3 Embedding）傳整個資料夾的 zip）。
  2. 伺服器路徑：先把檔案放到 `MODEL_ZOO_IMPORT_ROOT`（NAS、USB 掛載點），頁面填相對路徑。
  3. 內網 URL：公司鏡像 / 檔案伺服器，主機要在 `MODEL_ZOO_ALLOWED_HOSTS`。
- **權重來源以 Hugging Face Hub 為主**（清單與授權在 `docs/MODEL_CATALOG.md` §9；YOLO 的 -seg / -cls 從 GitHub release）。有網路的機器先 `pip install huggingface_hub pyyaml`，再用 `python3 scripts/fetch_model_zoo.py --dest ./model_zoo` 把全部抓好（`--only dinov2-small yolov8n` 可挑、`--skip dinov3-vits16 dinov3-vitb16` 可略過；DINOv3 是 gated 模型：先在 Hugging Face 的模型頁接受授權，`export HF_TOKEN=hf_…` 再執行；失敗的檔會列在結尾，重跑只補缺的），整個資料夾放到傳輸資料夾再逐一匯入，或直接複製到 `MODEL_ZOO_ROOT`（manifest 相容）。
- 權重缺少時：精靈的模型卡片會標「缺權重」，建立任務會被拒絕（`WEIGHTS_MISSING`）；AutoML 會自動跳過缺權重的候選（例如沒匯入 TabPFN 權重時表格 AutoML 就不試它）。sklearn / XGBoost / CatBoost / PLS / 影像品質 / 光譜 MAE 家族不需要權重。
- 命令列檢查：`cd backend && .venv/bin/python -m app.cli model-zoo --verify`。

### 4.4 MariaDB（正式環境）

```bash
# backend/.env：DATABASE_URL=mariadb+asyncmy://qr:<密碼>@localhost:3307/qr_ai_lab、REDIS_URL=redis://localhost:6380/0、APP_ENV=prod
.venv/bin/alembic upgrade head           # 建表（需要第 3 節的 MariaDB）
.venv/bin/python -m app.cli seed         # local 模式建立 superadmin / admin / user（密碼取自 SEED_*；keycloak 模式不建）
.venv/bin/python -m app.cli create-user --username alice --password '…' --email alice@example.com --role user
```

`APP_ENV=prod` 不會自動建表；Redis 讓 SSE 事件在多個 backend 程序間共享（未設定時用單程序記憶體 bus）。

### 4.5 測試與檢查

```bash
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest          # 含排程器（假 runner）與端到端（真的 trainer 子程序）
cd trainer && .venv/bin/ruff check . && .venv/bin/pytest                                          # 模型家族、registry 與 yaml 對照、runtime
cd libs/preprocess && ../../trainer/.venv/bin/python -m pytest                            # 共用前處理套件（backend 與 trainer 都以 path dependency 安裝）
QR_TEST_ZOO=/path/to/zoo .venv/bin/pytest tests/test_yolo_cpu.py                              # trainer：YOLO 從 yolov8n.pt 微調（CPU）
.venv/bin/python -m trainer check                                                              # 這個環境能跑哪些家族
```

### 4.6 正式安裝（Ubuntu GPU 伺服器，不連外、有 PyPI / npm / image proxy）

正式環境的網址是 `https://qrit.tsmc.com/ai-lab`（前端）與 `https://qrit.tsmc.com/ai-lab-api`（API 文件 / 腳本用），同一台 nginx 上還有別的服務，所以安裝分成四個獨立的腳本，每一步都可以單獨重跑；nginx 的設定由你自己加進現有的 `server` 區塊（範本在 `infra/nginx/`）。完整的逐步說明在 §7.2。

| 步驟 | 腳本 | 做什麼 |
|---|---|---|
| 0 | `sudo ./infra/install-00-base.sh` | 建 `qrlab` 使用者（`enable-linger`）、`/srv/qr-ai-lab/{data,transfer}`、把 checkout 交給 qrlab、從範本產生 `/etc/qr-ai-lab/qrlab.env` 與 `frontend.env` 後停下讓你編輯 |
| 1 | `./infra/install-01-docker.sh` | `infra/.env`（第一次會從範本產生後停下）→ `docker compose up -d` MariaDB（主機 port **3307**）與 Redis（**6380**），等 healthy，印出要填進 `qrlab.env` 的 `DATABASE_URL` / `REDIS_URL` |
| 2 | `sudo ./infra/install-02-backend.sh [--update]` | 檢查 env 檔（行尾註解、預設 secret）→ `backend/.venv`、`trainer/.venv`（pip，走 `/etc/pip.conf` 的 proxy）→ `alembic upgrade head`（第一次再 `app.cli seed`）→ `qrlab-backend.service`、`qrlab-scheduler.service` → 等 `/healthz` |
| 3 | `sudo ./infra/install-03-frontend.sh [--update]` | `npm ci`（走 `/etc/npmrc`）→ `next build`（把 `frontend.env` 的 `NEXT_PUBLIC_BASE_PATH=/ai-lab` 編進去）→ `qrlab-frontend.service` → 等 `/ai-lab/login` 回 200 |

之後 `git pull` 後只要 `sudo ./infra/install-02-backend.sh --update` 與 `sudo ./infra/install-03-frontend.sh --update`（各自先停自己的服務再重建；執行中的任務不受影響）。改了 pyproject 的依賴要先在開發機跑 `scripts/pin_requirements.sh` 並提交 `requirements*.txt`。

### 4.7 使用率歷史與資料前處理服務

- **管理 → 使用率歷史**（`/admin/usage`）：排程器每 30 秒（`USAGE_SAMPLE_INTERVAL_S`）寫一筆 `resource_samples`；頁面可切 1h / 6h / 24h / 7d / 30d，分母可切「專案配額 / 資源池 / 系統總量」；下方表格是各專案在該區間的時間加權配置（相對分母的百分比）與實測 CPU / 記憶體。保留 `USAGE_RETENTION_DAYS`（預設 90 天）。
- **資料前處理**（`/tools/preprocess`，所有登入者）：不需要專案；選資料類型 → 上傳 → 挑步驟 → 抽樣預覽（即時，只取樣）→ 「建立前處理任務」。整檔處理是公共工具池裡的任務（全域佇列、工具池配額、每人同時上限、即時 log），完成後在 `/tools/jobs/{id}` 下載 zip（`processed.*`、`pipeline.json`、`summary.json`）；下載一次就刪，沒下載的在「工具池」的保留時間（預設 24 小時）後刪。
- **資料分析**（`/tools/analyze`）：表格資料探勘（相關性、VIF 共線性、對目標的解釋力、建議）與影像品質分析（zip 子資料夾 = 機台 / 條件；最會飄的 IQA 指標、embedding 相似度與散佈、離群影像）。同樣是任務，報告在任務頁。
- 工具池：所有人的工具任務共用一個系統專案（slug `tools`，第一次用工具時自動建立，不列在專案列表），配額與「每人同時任務數」由 Dashboard 的「工具池」設定。各專案的配額在專案的「設定」分頁（superadmin）。

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
   - 角色：不需要在 Keycloak 設任何 role（Keycloak 只提供身分）。所有人登入後都是 `user`，由 superadmin 在 `/admin/users` 指派 admin；superadmin 只有一位，由 backend 的 `SUPERADMIN_USERNAME` 指定。
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
   SUPERADMIN_USERNAME=<你的帳號>                         # 唯一的 superadmin（preferred_username）；其他人在 UI 指派 admin / user
   ```
   `KEYCLOAK_AUDIENCE` 只有在 Keycloak 加了 audience mapper 時才設。
4. 重啟三個服務。登入頁變成「使用公司帳號登入（Keycloak）」；第一次登入會自動在 `users` 建立帳號（同名的本地帳號會被接管）。切換期間要保留本地登入的話前端設 `AUTH_LOCAL_FALLBACK=1`。
5. 沒有公司 Keycloak 也能先測整條流程：`backend/.venv/bin/python scripts/fake_keycloak.py` 跑一個模擬 realm（`http://127.0.0.1:8089/realms/qr`，client `qr-ai-lab` / `dev-secret`，帳號 superadmin / admin / user / alice），前後端照上面設定指向它，再 `cd frontend && npm run screenshots:keycloak` 看截圖。

角色與權限的完整表在 `docs/ARCHITECTURE.md` §2.3；UI 只負責隱藏按鈕，真正的判斷在 backend 的 `require_perm`。

## 6. 推薦的日常流程

```bash
git pull
cd frontend && npm ci && npm run dev          # 終端 1：前端（BACKEND_URL 預設 http://localhost:8000）
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/uvicorn app.main:app --reload   # 終端 2：後端（SQLite + 內嵌排程器，任務直接用 trainer/.venv 跑）
# 要測正式拓樸（分開的排程器 + Redis）才需要終端 3：REDIS_URL=… .venv/bin/python -m app.scheduler
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d   # 需要 MariaDB / Redis 時（開發機通常不用）
# 改完 UI
cd frontend && npm run lint && npm run typecheck && python3 ../scripts/design_lint.py src
# 改完後端 / trainer
cd backend && .venv/bin/ruff check . && .venv/bin/pytest
cd trainer && .venv/bin/ruff check . && .venv/bin/pytest
```

環境變數檔案的完整清單與每個變數的意義見 `docs/ENVIRONMENT.md`。

## 7. WSL 與 Ubuntu：完整的 dev / prod 啟動

### 7.1 開發（WSL2 或 Ubuntu 桌機；本地帳號、SQLite、內嵌排程器、不需要 Docker）

```bash
# 一次性
sudo apt install -y python3.12 python3.12-venv nodejs npm git     # Node ≥ 20.9（建議 nvm install 22）
git clone <repo> && cd qr-ai-lab
cd trainer && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-torch.txt && .venv/bin/pip install -r requirements-dev.txt && cd ..   # trainer venv：torch 先（index 在檔案裡；沒 GPU 改用 requirements-torch-cpu.txt），再其餘
cd backend && cp .env.example .env && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && cd ..   # .env 預設 AUTH_MODE=local、SQLite、SCHEDULER_EMBEDDED=true
cd frontend && cp .env.local.example .env.local && npm ci && cd ..   # AUTH_MODE=local、BACKEND_URL=http://localhost:8000
# 每天
cd backend && .venv/bin/uvicorn app.main:app --reload   # 終端 1：API + 內嵌排程器 + 使用率取樣（http://localhost:8000/docs）
cd frontend && npm run dev                           # 終端 2：http://localhost:3000，superadmin / admin / user
```

- **從別台機器瀏覽 `npm run dev`**（不是在開發機自己的瀏覽器）：Next.js 16 的 dev server 只把自己的資源（`/_next/*`：HMR websocket、dev overlay）給 localhost，別的來源會被 403 擋掉，而 Turbopack 的 client 在接不上 HMR 時**不會 hydrate**：頁面看得到但什麼都按不了、下拉選單沒有選項、表單沒反應。解法：`frontend/.env.local` 設 `NEXT_DEV_ALLOWED_ORIGINS=<那台機器用來連你的位址，例 192.168.1.20 或 devbox.local>`（逗號分隔，可用 `*.corp` 萬用字元），並用 `npm run dev -- -H 0.0.0.0` 讓它聽所有介面；或直接 `npm run dev -- -H 192.168.1.20`（`-H` 指定的主機名會自動被允許）。經 nginx 轉發也一樣要設（dev server 看到的 Origin 仍是那台機器的位址）。正式 build（`npm run build && npm run start`）沒有這個限制。
- WSL2 專屬：`/etc/wsl.conf` 加 `[boot]\nsystemd=true` 後 `wsl --shutdown`，排程器才能用 systemd cgroup（否則自動退到 subprocess + affinity + watchdog，功能一樣，只是記憶體上限靠 watchdog）；GPU 要 Windows 端的 NVIDIA driver（WSL 內不要另裝 driver），`nvidia-smi` 在 WSL 看得到就能用 cu126 的 torch。
- 要測「兩個程序 + Redis + MariaDB」的正式拓樸：`docker compose -f infra/docker-compose.yml --env-file infra/.env up -d`，backend `.env` 改 `DATABASE_URL=mariadb+asyncmy://…`、`REDIS_URL=redis://localhost:6380/0`、`SCHEDULER_EMBEDDED=false`，`.venv/bin/alembic upgrade head && .venv/bin/python -m app.cli seed`，再開第三個終端 `.venv/bin/python -m app.scheduler`。
- 要測 Keycloak：照 §5 第 5 點用假 Keycloak，或直接填公司的 realm；完整的四個終端寫在 7.1a。

**WSL2 + Windows 的 Docker Desktop（MariaDB / Redis 跑在 Docker Desktop，其餘都在 WSL 內）**

- Docker Desktop → Settings → Resources → **WSL integration** 勾選你的 Ubuntu distro。之後 WSL 裡直接有 `docker` / `docker compose`，**不要**在 WSL 內再 `apt install docker.io`，`install-01-docker.sh` 與 §3 的指令照用。
- repo 放在 WSL 自己的檔案系統（`~/qr-ai-lab`），不要放 `/mnt/c/...`：compose 會把 `infra/mariadb/init` 綁定掛載進容器，NTFS 上的執行位元與換行會讓 `01_init.sh` 跑不起來，而且 I/O 慢很多。
- 容器 port 綁在 `127.0.0.1:3307` / `127.0.0.1:6380`；有 WSL integration 的 distro 用 `localhost:3307` 就連得到，backend `.env` 寫 `DATABASE_URL=mariadb+asyncmy://qr:<密碼>@localhost:3307/qr_ai_lab`、`REDIS_URL=redis://localhost:6380/0`。
- Docker Desktop 必須先在 Windows 端開著（WSL 的 `systemctl` 管不到它）；開機自動啟動在 Docker Desktop 的 General 設定，容器本身是 `restart: unless-stopped`，Desktop 一起來就會回來。
- 公司 image mirror / proxy：設在 Docker Desktop → Settings → Docker Engine（`registry-mirrors`）或 Resources → Proxies，不是 WSL 的 `/etc/docker/daemon.json`；`infra/.env` 的 `DOCKER_REGISTRY` 仍可用來指定完整的 mirror 前綴。
- 資料在 bind mount 的主機目錄（預設 `infra/data/*`，在 WSL 的檔案系統裡；`MARIADB_DATA_DIR` 可改成絕對路徑）。不要把它指到 `/mnt/c/...`：MariaDB 在 NTFS 上的檔案鎖與權限會出問題。
- 開 `systemd=true` 之後 Docker Desktop 的 WSL integration 照常運作，排程器就能用 systemd cgroup；GPU 走 Windows 端的 NVIDIA driver，Docker 完全不碰 GPU。

### 7.1a 開發模式 + MariaDB + Redis +（假或真的）Keycloak（WSL2 或 Ubuntu 都一樣）

7.1 是最快的路（SQLite、內嵌排程器、本地帳號）。要在**不裝 systemd 服務**的情況下測正式拓樸（MariaDB、Redis、獨立排程器程序、Keycloak 登入；nginx 可選，見本節最後），開四個終端。開發環境沒有任何固定路徑或固定帳號：repo 放哪裡都可以（下面的 `cd backend` 都是相對 repo 根目錄）、全部用**你自己的帳號**跑（`systemd-run --user` 用的是你登入後的 user manager，不需要 linger）、`DATA_ROOT` 預設是 `backend/./data`、`TRAINER_DIR` 預設 `../trainer`，都不用改。§7.3 的 `/opt/qr-ai-lab`、`qrlab` 使用者、`/etc/qr-ai-lab/*.env` 只屬於正式環境的 systemd 服務。

```bash
# 0. 一次性：MariaDB + Redis（Docker；WSL2 用 Docker Desktop 的 WSL integration）
./infra/install-01-docker.sh && nano infra/.env && ./infra/install-01-docker.sh     # 或 docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
# backend/.env 改成：
#   DATABASE_URL=mariadb+asyncmy://qr:<MARIADB_PASSWORD>@localhost:3307/qr_ai_lab
#   REDIS_URL=redis://localhost:6380/0
#   SCHEDULER_EMBEDDED=false
#   AUTH_MODE=keycloak   KEYCLOAK_ISSUER=http://127.0.0.1:8089/realms/qr   KEYCLOAK_CLIENT_ID=qr-ai-lab   SUPERADMIN_USERNAME=superadmin
#   （真的 Keycloak：KEYCLOAK_ISSUER=https://<sso>/realms/<realm>、KEYCLOAK_CLIENT_ID=<client id>、SUPERADMIN_USERNAME=<你的帳號>）
# frontend/.env.local 改成：
#   AUTH_MODE=keycloak   AUTH_URL=http://localhost:3000   AUTH_SECRET=<openssl rand -base64 32>
#   AUTH_KEYCLOAK_ID=qr-ai-lab   AUTH_KEYCLOAK_SECRET=dev-secret   AUTH_KEYCLOAK_ISSUER=http://127.0.0.1:8089/realms/qr
#   （真的 Keycloak：三個 AUTH_KEYCLOAK_* 填公司的 client；redirect URI 要登記 http://localhost:3000/api/auth/callback/keycloak）
cd backend && .venv/bin/alembic upgrade head && cd ..          # MariaDB 建表（keycloak 模式不 seed 本地帳號）

# 1. 假 Keycloak（真的 Keycloak 就跳過這個終端）
backend/.venv/bin/python scripts/fake_keycloak.py --port 8089 --realm qr --client qr-ai-lab --secret dev-secret
# 2. API（沒有內嵌排程器）
cd backend && .venv/bin/uvicorn app.main:app --reload
# 3. 排程器（獨立程序，事件走 Redis）
cd backend && .venv/bin/python -m app.scheduler
# 4. 前端
cd frontend && npm run dev
```

開 `http://localhost:3000/login` → 「使用公司帳號登入（Keycloak）」→ 假 Keycloak 的登入頁（帳號 `superadmin` / `admin` / `user` / `alice`，密碼隨便）→ 回首頁。檢查點：Dashboard 顯示排程器來自 Redis（不是 embedded）、`docker compose -f infra/docker-compose.yml --env-file infra/.env exec mariadb mariadb -uqr -p qr_ai_lab -e "select username, role from users"` 看得到登入後自動建立的帳號、`/admin/users` 能把 `user` 指派為管理員。

角色怎麼決定（兩種模式都一樣）：Keycloak **只提供身分**（`preferred_username`、email、姓名），角色存在我們的 `users.role`。第一次登入一律是 `user`；`SUPERADMIN_USERNAME` 指定的那個帳號登入時自動成為唯一的 superadmin；其他人要變成 admin 只能由 superadmin 在 `/admin/users` 指派（或 `python -m app.cli set-role`）。`KEYCLOAK_ROLE_MAP` 預設空，所以 token 裡的 realm / client role 完全不影響角色（假 Keycloak 的 `admin` 帳號登入後也是 `user`）；只有刻意設了 `KEYCLOAK_ROLE_MAP=qr-admin:admin` 之類的對應才會用 token 的 role 覆蓋，而且最多到 admin。

切回本地帳號：兩邊 `AUTH_MODE=local`，backend `.venv/bin/python -m app.cli seed` 建 superadmin / admin / user。

**只想要 MariaDB + Redis、暫時不碰 Keycloak**：完全可以，認證、資料庫、事件匯流排三件事互不相干。`AUTH_MODE` 兩邊都留 `local`，`backend/.env` 只改 `DATABASE_URL`、`REDIS_URL`、`SCHEDULER_EMBEDDED=false`，`alembic upgrade head` 之後跑一次 `.venv/bin/python -m app.cli seed`（SQLite 模式啟動時會自動建表 + seed，MariaDB 不會；seed 可重複執行），再開三個終端（API、`python -m app.scheduler`、`npm run dev`）。之後換 Keycloak 只改兩邊的 `AUTH_MODE` 與 Keycloak 變數，資料庫內容全部保留。

**可選：加上 nginx 路徑前綴（`http://localhost/ai-lab`）**，和正式環境一樣的 URL 結構；服務仍是上面四個終端，只是前端改用 `/ai-lab` 的 basePath、後端改用 `/ai-lab-api` 的 ROOT_PATH。dev 用的 site 檔是一個完整、自給自足的檔案（`infra/nginx/qr-ai-lab-dev.conf`，含 Turbopack HMR 的 websocket 設定；正式環境才用 `qr-ai-lab.conf` + snippets）：

```bash
sudo apt install -y nginx
sudo cp infra/nginx/qr-ai-lab-dev-http.conf /etc/nginx/conf.d/                 # http {} 層的 Upgrade 對應（HMR / SSE）
sudo cp infra/nginx/qr-ai-lab-dev.conf /etc/nginx/sites-available/qr-ai-lab-dev
sudo ln -sf /etc/nginx/sites-available/qr-ai-lab-dev /etc/nginx/sites-enabled/qr-ai-lab-dev
sudo rm -f /etc/nginx/sites-enabled/default                                      # 它也占 80
sudo nginx -t && sudo systemctl reload nginx
# 三個設定跟著前綴走（改完重啟對應的終端）：
#   backend/.env         ROOT_PATH=/ai-lab-api   CORS_ORIGINS=http://localhost
#   frontend/.env.local  AUTH_URL=http://localhost/ai-lab   COOKIE_SECURE=0
#   前端啟動改成：cd frontend && NEXT_PUBLIC_BASE_PATH=/ai-lab npm run dev   （basePath 是啟動時決定的；之後 npm run build 也要帶同一個值）
#   假 Keycloak 接受任何 redirect_uri，不用改；真的 Keycloak 要登記 http://localhost/ai-lab/api/auth/callback/keycloak
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/ai-lab/login      # 200
curl -s http://localhost/ai-lab-api/healthz                                 # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/ai-lab-api/docs   # 200（Swagger；ROOT_PATH 正確才載得進來）
```

瀏覽器開 `http://localhost/ai-lab/login`；WSL2 的 80 port 會自動轉到 Windows 的 localhost。`http://localhost/` 會導到 `/ai-lab/`。

### 7.1b 開發（原生 Ubuntu 桌機 / 筆電；與 7.1 相同，只有 Docker 與 systemd 的來源不同）

```bash
# 一次性
sudo apt install -y python3.12 python3.12-venv git nginx-light            # nginx 只有要模擬正式路徑前綴時才需要
# Node ≥ 20.9：curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash && nvm install 22
# Docker Engine + compose plugin（官方 apt repo 或公司鏡像），然後 sudo usermod -aG docker $USER 並重新登入
# NVIDIA driver（apt 的 nvidia-driver-5xx 或官方安裝檔）；只要 driver，不要裝 CUDA toolkit、不要 NVIDIA Container Toolkit
loginctl enable-linger $USER     # 排程器以你的帳號跑時，任務 scope 要有常駐的 user manager
cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.subtree_control   # 要看到 cpu memory pids cpuset
```

`subtree_control` 少了 `cpuset`（Ubuntu 22.04 的 systemd 249 預設只委派 `pids memory`）時加一個 drop-in，否則排程器自動退到 subprocess + affinity：

```ini
# /etc/systemd/system/user@.service.d/delegate.conf
[Service]
Delegate=cpu cpuset io memory pids
```

`sudo systemctl daemon-reload && sudo systemctl restart user@$(id -u).service`（會踢掉目前的登入階段，重新登入即可）。之後的 clone、venv、`.env`、每天啟動與正式拓樸測試都和 7.1 一樣；Docker 的差別只有 compose 直接在本機 Docker Engine 跑，`docker compose … up -d` 之後用 `localhost:3307` / `6380` 連。

### 7.1c 在 WSL2 模擬正式環境（四個 install 腳本、systemd 服務、nginx 前綴、假 Keycloak）

目的：在上伺服器前把 7.2 的整條流程跑一遍。差異只有三點：MariaDB / Redis 由 Docker Desktop 提供、Keycloak 用 `scripts/fake_keycloak.py`、網址是 `http://localhost/ai-lab`（沒有 TLS，所以 `COOKIE_SECURE=0`）。

```bash
# 前提：7.1 的 Windows 端設定（Docker Desktop WSL integration、/etc/wsl.conf systemd=true、NVIDIA driver）
sudo apt install -y nginx-light python3.12 python3.12-venv
sudo ln -sf "$(which node)" /usr/local/bin/node      # 腳本與 qrlab 使用者要找得到系統層級的 node（nvm 的 node 只有你看得到）
sudo git clone ~/qr-ai-lab /opt/qr-ai-lab && cd /opt/qr-ai-lab   # 另外 clone 一份：install-00 會把整個 checkout chown 給 qrlab
sudo git -C /opt/qr-ai-lab checkout <分支>

# 步驟 0
sudo ./infra/install-00-base.sh
sudo nano /etc/qr-ai-lab/qrlab.env
#   APP_ENV=prod   DATABASE_URL=mariadb+asyncmy://qr:<密碼>@127.0.0.1:3307/qr_ai_lab   REDIS_URL=redis://127.0.0.1:6380/0
#   ROOT_PATH=/ai-lab-api   CORS_ORIGINS=http://localhost
#   AUTH_MODE=keycloak   KEYCLOAK_ISSUER=http://127.0.0.1:8089/realms/qr   KEYCLOAK_CLIENT_ID=qr-ai-lab   SUPERADMIN_USERNAME=superadmin
#   AUTH_SECRET / JOB_TOKEN_SECRET = openssl rand -hex 32   DATASET_SECRET_KEY = python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
sudo nano /etc/qr-ai-lab/frontend.env
#   NEXT_PUBLIC_BASE_PATH=/ai-lab   AUTH_URL=http://localhost/ai-lab   AUTH_MODE=keycloak   COOKIE_SECURE=0
#   AUTH_SECRET = openssl rand -base64 32   AUTH_KEYCLOAK_ID=qr-ai-lab   AUTH_KEYCLOAK_SECRET=dev-secret   AUTH_KEYCLOAK_ISSUER=http://127.0.0.1:8089/realms/qr

# 步驟 1：Docker Desktop（以你自己的帳號跑，不用 sudo）
./infra/install-01-docker.sh && nano infra/.env && ./infra/install-01-docker.sh

# 假 Keycloak（另一個終端一直開著；用 /opt 那份的 venv 要等步驟 2 建好，先用 ~/qr-ai-lab 的）
~/qr-ai-lab/backend/.venv/bin/python ~/qr-ai-lab/scripts/fake_keycloak.py --port 8089 --realm qr --client qr-ai-lab --secret dev-secret

# 步驟 2、3
sudo ./infra/install-02-backend.sh          # 有網路就用預設的 download.pytorch.org cu126；內網再設 TORCH_INDEX_URL
curl -s http://127.0.0.1:8000/healthz
sudo ./infra/install-03-frontend.sh

# 步驟 4：nginx（WSL 內的 nginx，listen 80）
sudo cp infra/nginx/qr-ai-lab-proxy.conf /etc/nginx/snippets/
#   limit_req_zone 那行 → /etc/nginx/conf.d/qrlab-zone.conf
#   location 區塊（含 large_client_header_buffers）→ /etc/nginx/sites-available/default 的 server { listen 80; } 裡
sudo nginx -t && sudo systemctl reload nginx
```

從 Windows 瀏覽器開 `http://localhost/ai-lab/login`（WSL 的 80 / 8089 會自動轉到 Windows 的 localhost）→ 假 Keycloak 登入頁（帳號 `superadmin`，任意密碼）→ 回首頁；`http://localhost/ai-lab-api/docs` 打得開；`systemctl status qrlab-backend qrlab-scheduler qrlab-frontend`；Dashboard「任務執行方式」應顯示 systemd。之後每次改完 code：`sudo git -C /opt/qr-ai-lab pull && sudo ./infra/install-02-backend.sh --update && sudo ./infra/install-03-frontend.sh --update`。關掉：`sudo systemctl stop qrlab-frontend qrlab-backend qrlab-scheduler`、`docker compose -f infra/docker-compose.yml --env-file infra/.env down`。

### 7.2 正式（Ubuntu GPU 伺服器；Keycloak、MariaDB + Redis in Docker、三個 systemd 服務、nginx 路徑前綴）

**前提（一次性）**

- `/etc/pip.conf` 指向公司的 PyPI proxy（Nexus）、`/etc/npmrc` 指向 npm proxy：

  ```ini
  # /etc/pip.conf
  [global]
  index-url = https://nexus.example.com/repository/pypi-proxy/simple
  trusted-host = nexus.example.com
  ```

  ```ini
  # /etc/npmrc
  registry=https://nexus.example.com/repository/npm-proxy/
  ```

- `python3.12` + `python3.12-venv`、系統層級的 node ≥ 20.9（`/usr/local/bin/node`，`qrlab` 使用者執行得到；不要用某個使用者的 nvm）、Docker Engine + compose plugin（公司 image mirror 設在 `infra/.env` 的 `DOCKER_REGISTRY`）、NVIDIA driver（只要 driver）、nginx 已在跑並有 `qrit.tsmc.com` 的憑證。
- Keycloak 管理員建一個 confidential client（`qr-ai-lab`），redirect URI = `https://qrit.tsmc.com/ai-lab/api/auth/callback/keycloak`，post-logout redirect URI = `https://qrit.tsmc.com/ai-lab/login`。

**步驟 0：主機準備**

```bash
sudo git clone <內部 git> /opt/qr-ai-lab && cd /opt/qr-ai-lab
sudo ./infra/install-00-base.sh
```

產生 `/etc/qr-ai-lab/qrlab.env` 與 `/etc/qr-ai-lab/frontend.env`（root:qrlab 640）。編輯它們，註解只能獨立成行：

```bash
sudo nano /etc/qr-ai-lab/qrlab.env
#   DATABASE_URL=mariadb+asyncmy://qr:<密碼>@127.0.0.1:3307/qr_ai_lab   REDIS_URL=redis://127.0.0.1:6380/0
#   CORS_ORIGINS=https://qrit.tsmc.com   ROOT_PATH=/ai-lab-api
#   AUTH_MODE=keycloak   KEYCLOAK_ISSUER=https://sso…/realms/<realm>   KEYCLOAK_CLIENT_ID=qr-ai-lab   SUPERADMIN_USERNAME=<你的帳號>
#   AUTH_SECRET / JOB_TOKEN_SECRET（openssl rand -hex 32）   DATASET_SECRET_KEY（Fernet）   MODEL_ZOO_* 
sudo nano /etc/qr-ai-lab/frontend.env
#   NEXT_PUBLIC_BASE_PATH=/ai-lab   AUTH_URL=https://qrit.tsmc.com/ai-lab   AUTH_MODE=keycloak
#   AUTH_SECRET（openssl rand -base64 32）   AUTH_KEYCLOAK_ID / AUTH_KEYCLOAK_SECRET / AUTH_KEYCLOAK_ISSUER
```

**步驟 1：MariaDB + Redis（docker）**

```bash
./infra/install-01-docker.sh        # 第一次：產生 infra/.env 後停下
nano infra/.env                      # MARIADB_ROOT_PASSWORD、MARIADB_PASSWORD、DOCKER_REGISTRY；port 預設 3307 / 6380（3306 / 6379 已被占用）
./infra/install-01-docker.sh        # 啟動並等 healthy；把印出的 DATABASE_URL / REDIS_URL 填進 qrlab.env
```

**步驟 2：backend + scheduler + trainer**

```bash
sudo ./infra/install-02-backend.sh
# 會檢查 env 檔 → 建兩個 venv（pip；trainer 先裝 requirements-torch.txt 的 torch，index 預設是檔案裡的 cu126；內網設 TORCH_INDEX_URL 換成 Nexus 代理的 download.pytorch.org）
# → alembic upgrade head + seed → 裝 qrlab-backend / qrlab-scheduler 並等 /healthz
# TORCH_INDEX_URL=https://nexus.example.com/repository/pytorch-cu126/ sudo -E ./infra/install-02-backend.sh   # 內網範例
curl -s http://127.0.0.1:8000/healthz          # {"status":"ok"}
journalctl -u qrlab-backend -n 30 --no-pager   # APP_ENV=prod 的設定檢查沒過會在這裡列出缺什麼
```

**步驟 3：frontend**

```bash
sudo ./infra/install-03-frontend.sh
# npm ci → next build（NEXT_PUBLIC_BASE_PATH=/ai-lab 編進去）→ qrlab-frontend → 等 http://127.0.0.1:3000/ai-lab/login 回 200
```

**步驟 4：nginx（自己加到現有的 server 區塊）**

```bash
sudo cp infra/nginx/qr-ai-lab-proxy.conf /etc/nginx/snippets/
# 把 infra/nginx/qr-ai-lab.conf 裡的 limit_req_zone 放進 http {}，location 區塊放進 server { server_name qrit.tsmc.com; } 
sudo nginx -t && sudo systemctl reload nginx
```

對應關係：`/ai-lab/…` 原樣轉給 `127.0.0.1:3000`（Next.js 用 basePath 自己處理前綴）；`/ai-lab-api/…` 去掉前綴轉給 `127.0.0.1:8000`（backend 以 `ROOT_PATH=/ai-lab-api` 產生正確的 `/ai-lab-api/docs`）；`/ai-lab/api/upload|tools/upload|admin/model-zoo` 放大 body 上限，`/ai-lab/api/stream` 關掉 buffering。

**上線檢查**

- `https://qrit.tsmc.com/ai-lab/login` → Keycloak → 回首頁；`https://qrit.tsmc.com/ai-lab-api/docs` 打得開。`curl -sI https://qrit.tsmc.com/ai-lab` 要是 307 到 `/ai-lab/login`（或登入後 200），不能是 301 到 `/ai-lab/`：nginx 不可以把 `/ai-lab` 轉成 `/ai-lab/`，Next.js 會再轉回來而形成無限重導向（範本已改成把 `/ai-lab` 原樣交給 Next.js）。
- 以 `SUPERADMIN_USERNAME` 的帳號登入，Dashboard「任務執行方式」是 systemd 且記憶體 / CPU 都是 cgroup；資源池勾選要開放的 GPU；模型庫把權重帶進來。
- dev 與 prod 的實質差異只有：帳號來源（本地 / Keycloak）、DB（SQLite / MariaDB）、排程器是否獨立程序（內嵌 / 獨立 + Redis）、runner（看 systemd 是否可用）、路徑前綴（無 / `/ai-lab`）。任務本身、權限判斷、資料不留存政策在兩邊完全一樣。

### 7.3 手動逐步安裝（不用 install 腳本；Ubuntu 伺服器 / 桌機，WSL2 也適用）

`infra/install-0x.sh` 做的事全部攤開在這裡，每一步都能自己執行、自己檢查。整套系統只有五個東西：

| 元件 | 怎麼跑 | 連哪裡 |
|---|---|---|
| MariaDB 11、Redis 7 | docker compose（或 apt 原生套件） | 127.0.0.1:3307、127.0.0.1:6380 |
| backend API | `qrlab` 使用者的 systemd 服務：`backend/.venv/bin/uvicorn app.main:app` | 127.0.0.1:8000 |
| scheduler | `qrlab` 使用者的 systemd 服務：`backend/.venv/bin/python -m app.scheduler`（任務是它用 `systemd-run --user` 起的主機子程序，跑 `trainer/.venv`） | Redis、MariaDB、GPU |
| frontend | `qrlab` 使用者的 systemd 服務：`node node_modules/next/dist/bin/next start` | 127.0.0.1:3000 → BACKEND_URL |
| nginx | 主機原生 | `/ai-lab` → 3000、`/ai-lab-api` → 8000 |

Keycloak 是外部服務（公司的，或 `scripts/fake_keycloak.py`）。開發用的「終端直接跑」版本在步驟 6，和 systemd 版本用同一套 venv 與設定檔。

**步驟 0：主機準備（root）**

```bash
# 0.1 套件：python 3.12、git、curl、nginx（要模擬路徑前綴才需要）、Docker Engine + compose plugin（或原生 mariadb-server / redis-server）
sudo apt update && sudo apt install -y python3.12 python3.12-venv git curl nginx-light
# Docker：官方 apt repo 或公司鏡像；之後 sudo usermod -aG docker $USER 並重新登入
# Node >= 20.9 要「系統層級」安裝，qrlab 使用者執行得到（nvm 裝的只有你自己看得到）：
#   例：curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
#   或已用 nvm：sudo ln -sf "$(which node)" /usr/local/bin/node && sudo ln -sf "$(which npm)" /usr/local/bin/npm
node -v && sudo -u nobody /usr/local/bin/node -v     # 第二個指令要能印出版本，代表別的使用者也執行得到
# NVIDIA：只要 driver（nvidia-smi 看得到 GPU 即可），不要裝 CUDA toolkit；WSL2 用 Windows 端的 driver

# 0.2 服務使用者 qrlab：任務會以它的 systemd user manager 起 cgroup scope，所以要 linger
sudo useradd --system --create-home --shell /bin/bash qrlab
sudo loginctl enable-linger qrlab
sleep 2 && systemctl status user@$(id -u qrlab).service --no-pager | head -3     # 要是 active (running)
cat /sys/fs/cgroup/user.slice/user-$(id -u qrlab).slice/user@$(id -u qrlab).service/cgroup.subtree_control
#   要看到 cpu cpuset memory pids；少了 cpuset（Ubuntu 22.04 預設）就加 drop-in：
#   sudo mkdir -p /etc/systemd/system/user@.service.d && printf '[Service]\nDelegate=cpu cpuset io memory pids\n' | sudo tee /etc/systemd/system/user@.service.d/delegate.conf
#   sudo systemctl daemon-reload && sudo systemctl restart user@$(id -u qrlab).service

# 0.3 資料夾：DATA_ROOT（產物 / log / 模型庫）、權重傳輸夾、設定檔夾
sudo mkdir -p /srv/qr-ai-lab/data/model_zoo /srv/qr-ai-lab/transfer /etc/qr-ai-lab
sudo chown -R qrlab:qrlab /srv/qr-ai-lab

# 0.4 程式碼：放 /opt（WSL2 不要放 /mnt/c），整個交給 qrlab（venv、node_modules、.next 都寫在裡面）
sudo git clone <repo> /opt/qr-ai-lab && sudo git -C /opt/qr-ai-lab checkout <分支>
sudo chown -R qrlab:qrlab /opt/qr-ai-lab
```

**步驟 1：MariaDB + Redis**

方式 A（docker compose，建議）：

```bash
cd /opt/qr-ai-lab
sudo -u qrlab cp infra/.env.example infra/.env
sudo -u qrlab nano infra/.env
#   MARIADB_ROOT_PASSWORD、MARIADB_PASSWORD 換掉；DOCKER_REGISTRY 填公司鏡像（含結尾 /）或留空
#   port 預設 3307 / 6380（3306 / 6379 常被別的服務占用）
docker compose -f infra/docker-compose.yml --env-file infra/.env pull        # 內網先確認 image 拉得到
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
docker compose -f infra/docker-compose.yml --env-file infra/.env ps          # mariadb 要 healthy（第一次約 20–40 秒）
# 驗證
docker compose -f infra/docker-compose.yml --env-file infra/.env exec mariadb mariadb -uqr -p<MARIADB_PASSWORD> qr_ai_lab -e "select @@character_set_database"
#   → utf8mb4（infra/mariadb/init/01_init.sh 在第一次啟動時設定，並建好 qr_ai_lab_test 給測試用）
docker compose -f infra/docker-compose.yml --env-file infra/.env exec redis redis-cli ping     # PONG
```

方式 B（原生套件，不想用 Docker）：

```bash
sudo apt install -y mariadb-server redis-server
sudo mariadb <<'SQL'
CREATE DATABASE qr_ai_lab CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'qr'@'127.0.0.1' IDENTIFIED BY '<密碼>';
GRANT ALL PRIVILEGES ON qr_ai_lab.* TO 'qr'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
# redis 預設 bind 127.0.0.1:6379；原生的 port 是 3306 / 6379，步驟 2 的 DATABASE_URL / REDIS_URL 要跟著改
```

**步驟 2：兩個環境變數檔**

```bash
sudo cp /opt/qr-ai-lab/infra/systemd/qrlab.env.example    /etc/qr-ai-lab/qrlab.env
sudo cp /opt/qr-ai-lab/infra/systemd/frontend.env.example /etc/qr-ai-lab/frontend.env
sudo chown root:qrlab /etc/qr-ai-lab/*.env && sudo chmod 640 /etc/qr-ai-lab/*.env
# 產生 secret
openssl rand -hex 32          # AUTH_SECRET（qrlab.env）
openssl rand -hex 32          # JOB_TOKEN_SECRET
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # DATASET_SECRET_KEY（沒有 cryptography 就等步驟 4 用 backend/.venv/bin/python 跑）
openssl rand -base64 32       # AUTH_SECRET（frontend.env）
sudo nano /etc/qr-ai-lab/qrlab.env
sudo nano /etc/qr-ai-lab/frontend.env
```

`qrlab.env` 一定要改的：

| 變數 | 值 |
|---|---|
| `DATABASE_URL` | `mariadb+asyncmy://qr:<MARIADB_PASSWORD>@127.0.0.1:3307/qr_ai_lab` |
| `REDIS_URL` | `redis://127.0.0.1:6380/0` |
| `SCHEDULER_EMBEDDED` | `false`（排程器獨立程序；單機小部署可 `true`，那就不裝 qrlab-scheduler） |
| `CORS_ORIGINS` | 對外網址的 origin，例 `https://qrit.tsmc.com`；本機 nginx 測試 `http://localhost` |
| `ROOT_PATH` | `/ai-lab-api`（nginx 去掉的前綴；沒有 nginx 時留空） |
| `AUTH_MODE` | `keycloak` 或 `local` |
| `AUTH_SECRET`、`JOB_TOKEN_SECRET`、`DATASET_SECRET_KEY` | 上面產生的值（`APP_ENV=prod` 會拒絕預設值） |
| `KEYCLOAK_ISSUER`、`KEYCLOAK_CLIENT_ID` | 公司 realm（要和 token 的 `iss` 一字不差）；假 Keycloak 是 `http://127.0.0.1:8089/realms/qr`、`qr-ai-lab` |
| `SUPERADMIN_USERNAME` | 唯一的 superadmin（Keycloak 的 `preferred_username`；local 模式用 `superadmin`） |
| `SEED_*_PASSWORD` | 只有 `AUTH_MODE=local` 才需要（seed 建三個本地帳號） |
| `TRAINER_DIR` | `/opt/qr-ai-lab/trainer`（repo 不在 /opt 就改） |

`frontend.env` 一定要改的：`NEXT_PUBLIC_BASE_PATH`（`/ai-lab`，沒有 nginx 前綴就留空）、`BACKEND_URL=http://127.0.0.1:8000`、`AUTH_MODE`（和 qrlab.env 一致）、`AUTH_SECRET`、`AUTH_URL`（對外網址含前綴，例 `https://qrit.tsmc.com/ai-lab`；本機 `http://localhost/ai-lab`）、`AUTH_KEYCLOAK_ID / SECRET / ISSUER`；沒有 TLS 時加 `COOKIE_SECURE=0`。

規則：**註解只能獨立成行**。systemd 會把 `KEY=value # 說明` 的 `# 說明` 當成值。檢查（必須沒有輸出）：

```bash
grep -nE '^[A-Za-z_][A-Za-z0-9_]*=.*[[:space:]]#' /etc/qr-ai-lab/*.env
```

**步驟 3：Keycloak（真的或假的）**

真的：請 Keycloak 管理員建 confidential client `qr-ai-lab`（Standard flow、PKCE），Valid redirect URI = `<AUTH_URL>/api/auth/callback/keycloak`，Valid post logout redirect URI = `<AUTH_URL>/login`；不用在 Keycloak 設任何 role。把 client id / secret / issuer 填進兩個 env 檔。

假的（開發 / 預演；`backend/.venv` 建好後才能跑，見步驟 4）：

```bash
sudo -u qrlab -H /opt/qr-ai-lab/backend/.venv/bin/python /opt/qr-ai-lab/scripts/fake_keycloak.py --host 127.0.0.1 --port 8089 --realm qr --client qr-ai-lab --secret dev-secret
# 帳號 superadmin / admin / user / alice，密碼隨便。要常駐就寫一個 systemd 單元：
sudo tee /etc/systemd/system/qrlab-fake-keycloak.service >/dev/null <<'UNIT'
[Unit]
Description=Fake Keycloak for QR AI Lab (dev only)
After=network-online.target
[Service]
User=qrlab
ExecStart=/opt/qr-ai-lab/backend/.venv/bin/python /opt/qr-ai-lab/scripts/fake_keycloak.py --host 127.0.0.1 --port 8089 --realm qr --client qr-ai-lab --secret dev-secret
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now qrlab-fake-keycloak
curl -s http://127.0.0.1:8089/realms/qr/.well-known/openid-configuration | head -c 200
```

**步驟 4：backend venv 與 trainer venv（以 qrlab 執行）**

```bash
sudo -u qrlab -H bash          # 之後這一段都在 qrlab 的 shell 裡
cd /opt/qr-ai-lab/backend
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt            # pip 從 /etc/pip.conf 的公司 PyPI proxy 抓；或 PIP_INDEX_URL=https://nexus…/simple
cd /opt/qr-ai-lab/trainer
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
# torch 一定先裝：index 寫在檔案裡（cu126，wheel 自帶 CUDA 函式庫，只需主機 driver）
.venv/bin/pip install -r requirements-torch.txt
#   內網要走 Nexus 代理的 download.pytorch.org：複製一份把第一行 --index-url 換掉再裝
#   sed 's#^--index-url .*#--index-url https://nexus.example.com/repository/pytorch-cu126/#' requirements-torch.txt > /tmp/torch.txt && .venv/bin/pip install -r /tmp/torch.txt
#   沒有 GPU 的機器：.venv/bin/pip install -r requirements-torch-cpu.txt
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m trainer check                    # 每個模型家族 ok / 缺什麼套件；有 GPU 會列 cuda
exit
```

**步驟 5：資料庫 schema 與帳號**

```bash
sudo -u qrlab -H bash -c 'set -a; . /etc/qr-ai-lab/qrlab.env; set +a; cd /opt/qr-ai-lab/backend && .venv/bin/alembic upgrade head'
sudo -u qrlab -H bash -c 'set -a; . /etc/qr-ai-lab/qrlab.env; set +a; cd /opt/qr-ai-lab/backend && .venv/bin/alembic current'   # 要是最新的 revision (head)
# AUTH_MODE=local：建 superadmin / admin / user（密碼來自 SEED_*_PASSWORD）
sudo -u qrlab -H bash -c 'set -a; . /etc/qr-ai-lab/qrlab.env; set +a; cd /opt/qr-ai-lab/backend && .venv/bin/python -m app.cli seed'
# AUTH_MODE=keycloak：不用 seed。SUPERADMIN_USERNAME 的帳號第一次登入就是 superadmin，其他人登入後是 user，
# 之後在 /admin/users 指派 admin，或：
sudo -u qrlab -H bash -c 'set -a; . /etc/qr-ai-lab/qrlab.env; set +a; cd /opt/qr-ai-lab/backend && .venv/bin/python -m app.cli set-role --username <帳號> --role admin'
```

**步驟 6：先用終端跑一遍（不裝 systemd，開發模式就停在這一步）**

```bash
# 終端 1：API
sudo -u qrlab -H bash -c 'set -a; . /etc/qr-ai-lab/qrlab.env; set +a; cd /opt/qr-ai-lab/backend && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000'
# 終端 2：排程器（SCHEDULER_EMBEDDED=false 時）
sudo -u qrlab -H bash -c 'set -a; . /etc/qr-ai-lab/qrlab.env; set +a; export XDG_RUNTIME_DIR=/run/user/$(id -u); cd /opt/qr-ai-lab/backend && exec .venv/bin/python -m app.scheduler'
#   log 第一行會說 runner=systemd 還是 subprocess：systemd 代表 cgroup 生效；subprocess 多半是 user@ 沒起來或 XDG_RUNTIME_DIR 不對
curl -s http://127.0.0.1:8000/healthz      # {"status":"ok"}
curl -s http://127.0.0.1:8000/readyz       # 檢查 DB / Redis 連線
```

**步驟 7：backend 與 scheduler 的 systemd 單元**

範本在 `infra/systemd/`，裡面寫死 `/opt/qr-ai-lab` 與 uid `1001`；路徑不同或 uid 不同就改掉：

```bash
ROOT=/opt/qr-ai-lab                 # repo 放別處就改這裡
UID_NUM=$(id -u qrlab)
for u in qrlab-backend qrlab-scheduler; do
  sed -e "s#/opt/qr-ai-lab#$ROOT#g" \
      -e "s#/run/user/1001#/run/user/$UID_NUM#g" \
      -e "s#user@1001.service#user@$UID_NUM.service#g" \
      $ROOT/infra/systemd/$u.service | sudo tee /etc/systemd/system/$u.service >/dev/null
done
# 要注意的欄位（用 nano 看一次）：User/Group=qrlab、WorkingDirectory=…/backend、EnvironmentFile=/etc/qr-ai-lab/qrlab.env、
#   Environment=XDG_RUNTIME_DIR=/run/user/<uid>（scheduler 靠它找到 qrlab 的 user manager）、
#   backend 的 ReadWritePaths=/srv/qr-ai-lab（DATA_ROOT 不在這底下就加上去）、scheduler 的 KillMode=process（重啟排程器不殺任務）
sudo systemctl daemon-reload
sudo systemctl enable --now qrlab-backend
sudo systemctl enable --now qrlab-scheduler          # SCHEDULER_EMBEDDED=true 就跳過這行
systemctl status qrlab-backend qrlab-scheduler --no-pager
journalctl -u qrlab-backend -n 30 --no-pager         # APP_ENV=prod 的設定檢查沒過會在這裡列出缺什麼
journalctl -u qrlab-scheduler -n 30 --no-pager       # 要看到 runner=systemd
curl -s http://127.0.0.1:8000/healthz
```

**步驟 8：frontend**

```bash
sudo -u qrlab -H bash
cd /opt/qr-ai-lab/frontend
npm ci --no-audit --no-fund                          # registry 從 /etc/npmrc；或 npm_config_registry=https://nexus…/npm-proxy/
rm -rf .next
NEXT_PUBLIC_BASE_PATH=/ai-lab NEXT_TELEMETRY_DISABLED=1 npm run build     # 值要和 frontend.env 的 NEXT_PUBLIC_BASE_PATH 一樣：前綴是編進去的，改了就要重 build
# 先手動起一次確認
set -a; . /etc/qr-ai-lab/frontend.env; set +a; node node_modules/next/dist/bin/next start      # Ctrl+C 結束
exit
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/ai-lab/login      # 200
# systemd 單元：ExecStart 的 node 路徑換成 which node 的結果（必須是系統層級的 node）
ROOT=/opt/qr-ai-lab
sed -e "s#/opt/qr-ai-lab#$ROOT#g" -e "s#/usr/local/bin/node#$(which node)#g" \
    $ROOT/infra/systemd/qrlab-frontend.service | sudo tee /etc/systemd/system/qrlab-frontend.service >/dev/null
sudo systemctl daemon-reload && sudo systemctl enable --now qrlab-frontend
systemctl status qrlab-frontend --no-pager && journalctl -u qrlab-frontend -n 20 --no-pager
```

**步驟 9：nginx**

```bash
sudo cp /opt/qr-ai-lab/infra/nginx/qr-ai-lab-proxy.conf /etc/nginx/snippets/
# limit_req_zone 那一行要在 http {} 裡：
echo 'limit_req_zone $binary_remote_addr zone=qrlab_login:1m rate=10r/m;' | sudo tee /etc/nginx/conf.d/qrlab-zone.conf
# 把 infra/nginx/qr-ai-lab.conf 裡「inside server {}」以下的所有 location 區塊（含 large_client_header_buffers）貼進你的 server 區塊：
#   正式：server { listen 443 ssl; server_name qrit.tsmc.com; … }
#   本機 / WSL2 預演：/etc/nginx/sites-available/default 的 server { listen 80; … }（此時 frontend.env 要 COOKIE_SECURE=0，
#   AUTH_URL=http://localhost/ai-lab，qrlab.env 的 CORS_ORIGINS=http://localhost）
sudo nginx -t && sudo systemctl reload nginx
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/ai-lab/login        # 200
curl -s http://localhost/ai-lab-api/healthz                                    # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/ai-lab-api/docs      # 200（Swagger，ROOT_PATH 正確才會載入）
```

對應關係：`/ai-lab/…` 原樣轉給 3000（Next.js 自己處理 basePath）；`/ai-lab-api/…` 去掉前綴轉給 8000；上傳路徑放大 body 上限、SSE 關閉 buffering。瀏覽器只需要 `/ai-lab`，`/ai-lab-api` 給腳本和 OpenAPI。

**步驟 10：驗證**

1. `http(s)://<網址>/ai-lab/login` → Keycloak（或本地帳號）→ 回首頁；以 `SUPERADMIN_USERNAME` 登入，`/admin/users` 看得到自己是超級管理員。
2. Dashboard「任務執行方式」= `systemd`，記憶體 / CPU 都是 cgroup；GPU 卡片列出 `nvidia-smi` 看得到的卡；資源池勾選要開放的 GPU。
3. 模型庫（`/admin/model-zoo`）把權重帶進 `/srv/qr-ai-lab/data/model_zoo`（上傳、`MODEL_ZOO_IMPORT_ROOT` 匯入或內網 URL）；`sudo -u qrlab … python -m app.cli model-zoo` 列出狀態。
4. 申請一個專案 → 核准 → 上傳 CSV 訓練 `tabular.linear` → 任務頁有 log、產物；`systemd-cgls -u user-$(id -u qrlab).slice` 在任務執行中能看到 `qrlab-job-<id>.scope`。
5. `journalctl -u qrlab-scheduler -f` 看排程與任務結束後的輸入刪除紀錄；`ls /srv/qr-ai-lab/data/projects/<slug>/jobs/<id>/` 只剩產物、log、metrics。

**步驟 11：更新與日常操作**

```bash
# 更新程式碼（任務是 systemd scope，重啟 backend / scheduler 不會殺任務）
sudo git -C /opt/qr-ai-lab pull
sudo systemctl stop qrlab-scheduler qrlab-backend
sudo -u qrlab -H bash -c 'cd /opt/qr-ai-lab/backend && .venv/bin/pip install -r requirements.txt'
sudo -u qrlab -H bash -c 'cd /opt/qr-ai-lab/trainer && .venv/bin/pip install -r requirements.txt'      # torch 版本有變才重跑 requirements-torch.txt
sudo -u qrlab -H bash -c 'set -a; . /etc/qr-ai-lab/qrlab.env; set +a; cd /opt/qr-ai-lab/backend && .venv/bin/alembic upgrade head'
sudo systemctl start qrlab-backend qrlab-scheduler
sudo systemctl stop qrlab-frontend
sudo -u qrlab -H bash -c 'cd /opt/qr-ai-lab/frontend && npm ci --no-audit --no-fund && rm -rf .next && NEXT_PUBLIC_BASE_PATH=/ai-lab npm run build'
sudo systemctl start qrlab-frontend
# 日常
systemctl status qrlab-backend qrlab-scheduler qrlab-frontend
journalctl -u qrlab-scheduler -f
docker compose -f /opt/qr-ai-lab/infra/docker-compose.yml --env-file /opt/qr-ai-lab/infra/.env ps
# 備份：MariaDB dump + DATA_ROOT（產物、log、模型庫）
docker compose -f /opt/qr-ai-lab/infra/docker-compose.yml --env-file /opt/qr-ai-lab/infra/.env exec mariadb mariadb-dump -uroot -p<root 密碼> qr_ai_lab > qr_ai_lab-$(date +%F).sql
tar czf data-$(date +%F).tgz -C /srv/qr-ai-lab data
# 全部停掉
sudo systemctl stop qrlab-frontend qrlab-scheduler qrlab-backend
docker compose -f /opt/qr-ai-lab/infra/docker-compose.yml --env-file /opt/qr-ai-lab/infra/.env down     # 加 -v 才會刪資料
```

**手動安裝常見錯誤**

- 排程器 log 說 `runner=subprocess`：`loginctl enable-linger qrlab` 沒做、`user@<uid>.service` 沒起來、或單元檔的 `XDG_RUNTIME_DIR` / `user@…service` 的 uid 不是 qrlab 的。功能一樣（affinity + 記憶體 watchdog），只是沒有 cgroup 硬限制。
- backend 起不來、journal 列出「APP_ENV=prod 設定檢查失敗」：secret 還是預設值、`DATASET_SECRET_KEY` 空、`REDIS_URL` 空但 `SCHEDULER_EMBEDDED=false`。
- `qrlab.env` 的值後面有 `# 註解`：整段變成值（最常見的是 `DATABASE_URL`），用步驟 2 的 grep 檢查。
- `qrlab-frontend` 立刻退出：`ExecStart` 的 node 路徑 qrlab 執行不到（nvm），或 `.next` 是用不同的 `NEXT_PUBLIC_BASE_PATH` build 的。
- 登入後 Keycloak 回 `invalid redirect_uri`：client 的 redirect URI 要和 `AUTH_URL + /api/auth/callback/keycloak` 完全一樣（含 http/https 與前綴）。backend 回 401 `token issuer`：`KEYCLOAK_ISSUER` 和 token 的 `iss` 不一字不差（常見差在尾端斜線或 http/https）。
- 連不上 MariaDB：`docker compose … ps` 看 mariadb 是否 healthy；port 是 3307 不是 3306；原生安裝時使用者要是 `'qr'@'127.0.0.1'`。
- nginx 上傳 413：`client_max_body_size` 只貼到一個 location；上傳與模型庫的 location 要各自有 20g。

## 8. 常見問題

- **頁面有畫面但什麼都按不了、下拉沒有選項、表單沒反應（只有從別台機器連 dev server 時）**：Next.js 16 擋掉非 localhost 來源的 `/_next/*`（dev server 終端會印「Blocked cross-origin request to Next.js dev resource /_next/hmr from "<ip>"」），client 沒 hydrate。設 `NEXT_DEV_ALLOWED_ORIGINS=<ip 或主機名>` 後重啟 `npm run dev -- -H 0.0.0.0`（§7.1）。
- **`EADDRINUSE: 3000`**：有別的 dev server 在跑；`npm run dev -- -p 3001` 換 port，或關掉舊的。
- **Node 版本太舊**：Next.js 16 需要 ≥ 20.9；`nvm install 22 && nvm use 22`。
- **Turbopack 快取怪異**：`rm -rf frontend/.next` 後重跑。
- **`npm ci` 失敗提到 lock 不一致**：確認用的是 npm 10 以上，且沒有用 pnpm / yarn 動過 `node_modules`。
- **Playwright 找不到瀏覽器**：`cd frontend && npx playwright install chromium`；或設 `CHROMIUM_PATH=/path/to/chrome` 再跑 `npm run screenshots`。
- **登入後被導回 `/login?reason=expired`**：backend 沒啟動、`BACKEND_URL` 不對，或 token 已過期（`ACCESS_TOKEN_MINUTES`，預設 12 小時）。
- **任務頁看不到即時 log，重新整理才有**：backend 與排程器分開跑時沒有 `REDIS_URL`，事件只在各自記憶體裡；設 `REDIS_URL=redis://localhost:6380/0` 給兩邊，或用 `SCHEDULER_EMBEDDED=true` 讓排程器跑在 backend 內。
- **Dashboard 顯示 runner 是 subprocess 而不是 systemd**：`systemd-run --user --scope -p MemoryMax=64M -- /bin/true` 手動跑看錯誤；常見原因是沒有 `loginctl enable-linger`、`XDG_RUNTIME_DIR` 沒指到該使用者、或 WSL 沒開 systemd。subprocess 模式仍會釘核心並由 watchdog 管記憶體。
- **任務因「memory limit exceeded」失敗**：申請的記憶體不夠；在精靈的資源步驟調高，或請管理員調整專案配額。
- **開發機只想裝 CPU torch**：`cd trainer && .venv/bin/pip install -r requirements-torch-cpu.txt && .venv/bin/pip install -r requirements-dev.txt`。
- **上傳預覽逾時（`PREVIEW_TIMEOUT`）**：預覽在 API 程序內以執行緒計算，預設 30 秒（`PREVIEW_TIMEOUT_S`）；縮小取樣數或先用較小的檔案試步驟。
- **MariaDB 一直不 healthy**：第一次初始化要 20–40 秒；看 `docker compose -f infra/docker-compose.yml logs mariadb`。
- **Windows**：在 WSL2 內操作，MariaDB / Redis 交給 Docker Desktop 的 WSL integration（§7.1）；repo 放 WSL 檔案系統，避免 `/mnt/c` 的路徑、換行與執行位元問題。
- **dev overlay 跳出 Console Error「The children should not have changed if we pass in the same set.」，堆疊全部在 `chrome-extension://fmkadmapgofadopljbjfkapdkoienihi/build/installHook.js`**：這是 React Developer Tools 擴充套件自己的 bug（8.0.0 之前的版本遇到 Next 16 instant navigation 用來預載頁面的 `<Activity mode="hidden">` 子樹被顯示時會丟這個斷言；React DevTools 8.0.0 的 changelog「Fix crash when revealing stable, filtered `<Activity>` children (#35734)」就是修這個）。不是本專案的程式碼：把擴充套件更新到 8.0.0 以上（chrome://extensions → 開發人員模式 → 更新），或對 localhost 停用它。用 DevTools 8.0.0 的同一份 backend 注入頁面跑過整站互動（導覽、任務頁即時 log、推論、精靈、編輯器），沒有任何斷言；正式 build 沒有 dev overlay，使用者也不會看到。
