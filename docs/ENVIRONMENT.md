# 環境變數與設定檔總覽

專案有 **五個** 會放環境變數的檔案（加上測試用的固定值）。公司私有的值只放在這些檔案，`.gitignore` 排除所有 `.env*`（只提交 `*.example`）。

| 檔案 | 誰讀 | 範本 | 用途 |
|---|---|---|---|
| `backend/.env` | 開發機的 backend 與排程器（`uv run uvicorn …`、`python -m app.scheduler`）；由 `app/core/config.py`（pydantic-settings）載入 | `backend/.env.example` | 開發：SQLite、本地帳號、內嵌排程器 |
| `frontend/.env.local` | 開發機的 Next.js（`npm run dev` / `npm run start`）；只在伺服器端讀，不會進瀏覽器 | `frontend/.env.local.example` | `BACKEND_URL`、`AUTH_MODE`、Keycloak client（prod 才需要） |
| `infra/.env` | `docker compose -f infra/docker-compose.yml --env-file infra/.env`（只跑 MariaDB / Redis） | `infra/.env.example` | image 鏡像、DB 名稱 / 帳號 / 密碼、port |
| `/etc/qr-ai-lab/qrlab.env` | 正式機的 `qrlab-backend.service` 與 `qrlab-scheduler.service`（systemd `EnvironmentFile`）；`install.sh` 的 migration / seed 也會 source 它 | `infra/systemd/qrlab.env.example` | 正式：MariaDB、Redis、Keycloak、secrets、模型庫、GPU、使用率取樣 |
| `/etc/qr-ai-lab/frontend.env` | 正式機的 `qrlab-frontend.service` | `infra/systemd/frontend.env.example` | 正式：`AUTH_MODE=keycloak`、Auth.js secret / URL / Keycloak client |

其他會設定環境變數但**不是檔案**的地方：

- `backend/tests/conftest.py`：測試用固定值（SQLite 暫存、假 secret、`JOB_RUNNER=subprocess`），不要拿來當範本。
- 排程器啟動每個任務子程序時注入的 `JOB_*`、`DATA_SOURCE_*`、`CUDA_VISIBLE_DEVICES`、`*_NUM_THREADS`、離線旗標（`app/scheduler/runner.py` 的 `job_env` / `thread_env`），由程式產生，不用手動設定。
- `infra/systemd/*.service` 內的少數固定值（`NODE_ENV=production`、`NEXT_TELEMETRY_DISABLED=1`）。
- e2e 截圖腳本讀的 `CHROMIUM_PATH`、`BASE_URL`、`API_URL`、`DATA_DIR`、`ZOO_DIR`、`PHASES`、`START_N`、`OUT_DIR`（只在跑 `npm run screenshots*` 時用）。

## backend / scheduler（`backend/.env` 或 `/etc/qr-ai-lab/qrlab.env`）

完整定義在 `backend/app/core/config.py`；名稱不分大小寫，逗號分隔的清單直接寫 `a,b,c`。

| 變數 | 預設 | 說明 |
|---|---|---|
| `APP_ENV` | `dev` | `dev` / `test` 會自動建表與種子帳號；`prod` 只靠 Alembic |
| `LOG_LEVEL` | `INFO` | |
| `PUBLIC_URL` | `http://localhost:3000` | 前端對外網址（寫入通知 / 連結） |
| `CORS_ORIGINS` | `http://localhost:3000` | 逗號分隔 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./dev.db` | 正式：`mariadb+asyncmy://qr:<pw>@127.0.0.1:3306/qr_ai_lab` |
| `REDIS_URL` | （空） | backend 與排程器分開跑時必設；空 = 單程序記憶體事件 bus |
| `DATA_ROOT` | `./data` | 產物、log、暫存輸入、`tools/`、`model_zoo/` |
| `MODEL_ZOO_ROOT` | `DATA_ROOT/model_zoo` | 預訓練權重 |
| `MODEL_ZOO_IMPORT_ROOT` | （空） | 管理員可從此資料夾匯入權重（NAS / USB） |
| `MODEL_ZOO_ALLOWED_HOSTS` | （空 = 任何） | 可下載權重的內網主機白名單 |
| `MODEL_ZOO_MAX_MB` | `20480` | 單一權重上限 |
| `AUTH_MODE` | `local` | `local` 本地帳號；`keycloak` 公司 SSO（前端要一致） |
| `AUTH_SECRET` | `dev-secret-change-me` | local 模式簽 token；也是 `DATASET_SECRET_KEY` 未設時的 Fernet 退路 |
| `ACCESS_TOKEN_MINUTES` | `720` | local token 壽命 |
| `KEYCLOAK_ISSUER` | （空） | `https://sso/realms/<realm>`，必須和 token 的 `iss` 一致 |
| `KEYCLOAK_AUDIENCE` | （空） | 設了才驗 `aud` |
| `KEYCLOAK_CLIENT_ID` | （空） | 讀 `resource_access[<client>].roles` |
| `KEYCLOAK_ROLE_MAP` | `superadmin:superadmin,admin:admin` | `<Keycloak role>:<系統角色>`；token 沒帶對應 role 時維持 UI 設的角色 |
| `SUPERADMIN_USERNAMES` | （空） | 登入即為 superadmin 的帳號（引導第一位） |
| `SEED_SUPERADMIN_PASSWORD` / `SEED_ADMIN_PASSWORD` / `SEED_USER_PASSWORD` | `superadmin1234` / `admin1234` / `user1234` | 只在 local 模式 / `app.cli seed` 使用 |
| `DATASET_SECRET_KEY` | （空） | Fernet key，加密使用者資料來源憑證；正式必設 |
| `JOB_TOKEN_SECRET` | `dev-job-secret-change-me` | 任務子程序呼叫 `/internal/*` 的 token |
| `JOB_RUNNER` | `auto` | `auto` / `systemd` / `subprocess` |
| `SYSTEMD_USER` | `true` | `systemd-run --user`（需要 `loginctl enable-linger`） |
| `TRAINER_DIR` / `TRAINER_PYTHON` | `../trainer` / `<TRAINER_DIR>/.venv/bin/python` | 任務用的 venv |
| `SCHEDULER_EMBEDDED` | `false` | `true` = 排程器跑在 backend 程序內（開發、小型部署，不需 Redis） |
| `MEMORY_WATCHDOG` | `true` | cgroup 不可用時由排程器監看記憶體 |
| `GPU_BUSY_THRESHOLD` | `0.10` | 獨占型任務：顯存已用超過此比例的 GPU 不排 |
| `GPU_RESERVE_MB` | `512` | 依顯存共用時每張保留給驅動 / context |
| `GPU_WARMUP_S` | `120` | 剛啟動的任務在這段時間內以申請量計入「尚未分配」，之後以實測為準 |
| `GPU_RESET_COMMAND` | （空） | superadmin「重置裝置」執行的指令，如 `sudo -n nvidia-smi --gpu-reset -i {index}` |
| `USAGE_SAMPLE_INTERVAL_S` / `USAGE_RETENTION_DAYS` | `30` / `90` | 使用率歷史 |
| `INTERNAL_BACKEND_URL` | `http://localhost:8000` | 任務子程序回呼 backend 的位址 |
| `SCHEDULER_INTERVAL_S` | `3` | |
| `UPLOAD_MAX_MB` / `UPLOAD_TTL_MINUTES` | `2048` / `60` | 一次性上傳與工具上傳 |
| `PREVIEW_TIMEOUT_S` | `30` | 前處理抽樣預覽（即時）上限 |
| `TOOL_PROCESS_TIMEOUT_S` | `600` | 保留給同步工具用途；整檔前處理現在是任務，受任務逾時控制 |
| `LOG_MAX_MB` / `DEFAULT_JOB_TIMEOUT_MINUTES` | `50` / `240` | |

管理員在 UI 調的值（資源池、Job 預設、工具預設 = 個人工作區配額與結果保留時間）存在 `system_settings` 表，不是環境變數。

## frontend（`frontend/.env.local` 或 `/etc/qr-ai-lab/frontend.env`）

| 變數 | 預設 | 說明 |
|---|---|---|
| `BACKEND_URL` | `http://localhost:8000` | Next.js 伺服器端打 FastAPI 的位址（瀏覽器不直接連） |
| `AUTH_MODE` | `local` | 與 backend 一致 |
| `AUTH_SECRET` | （keycloak 必填） | 加密 Auth.js session cookie（`openssl rand -base64 32`） |
| `AUTH_URL` | （keycloak 必填） | 對外網址；Keycloak 的 redirect URI = `$AUTH_URL/api/auth/callback/keycloak` |
| `AUTH_KEYCLOAK_ID` / `AUTH_KEYCLOAK_SECRET` / `AUTH_KEYCLOAK_ISSUER` | | confidential client |
| `AUTH_SESSION_MAX_AGE` | `43200` | session cookie 秒數（access token 在裡面自動 refresh） |
| `AUTH_LOCAL_FALLBACK` | `0` | `1` = keycloak 模式的登入頁也顯示本地帳號表單（切換期） |
| `COOKIE_SECURE` | （未設 = production 時 Secure） | nginx 沒有 TLS 時設 `0` |
| `PUBLIC_URL` | `AUTH_URL` | 登出後導回的網址（通常不用設） |
| `PORT` / `HOSTNAME` | `3000` / `127.0.0.1` | systemd 啟動用 |

## infra（`infra/.env`，docker compose）

| 變數 | 說明 |
|---|---|
| `DOCKER_REGISTRY` | 公司 image 鏡像前綴（含結尾斜線）；空 = Docker Hub |
| `MARIADB_ROOT_PASSWORD` / `MARIADB_DATABASE` / `MARIADB_USER` / `MARIADB_PASSWORD` / `MARIADB_PORT` | MariaDB 容器；`DATABASE_URL` 要用同一組帳密 |
| `REDIS_PORT` | Redis 容器 |

## 安裝時的鏡像變數（只在執行 `infra/install.sh` 的 shell 裡）

`PIP_INDEX_URL`（或 `UV_INDEX_URL`）、`NPM_REGISTRY`：公司 PyPI / npm 鏡像；不會寫進任何檔案。
