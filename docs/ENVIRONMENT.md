# 環境變數與設定檔總覽

專案有 **五個** 會放環境變數的檔案（加上測試用的固定值）。公司私有的值只放在這些檔案，`.gitignore` 排除所有 `.env*`（只提交 `*.example`）。

兩條規則：

- **註解一律獨立成行。** systemd 的 `EnvironmentFile` 與 docker compose 都會把 `KEY=value   # 說明` 後面的 `# 說明` 當成值的一部分（型別欄位直接讓服務起不來、網址對不上）。`backend/tests/test_infra_contracts.py` 與 `install-02/03` 腳本都會檢查。
- **`APP_ENV=prod` 啟動時會檢查設定**：`AUTH_SECRET` / `JOB_TOKEN_SECRET` 不得是預設值或少於 32 字元、`DATASET_SECRET_KEY` 必須是合法的 Fernet 金鑰、keycloak 模式要有 `KEYCLOAK_ISSUER` 與 `KEYCLOAK_CLIENT_ID`（或 `KEYCLOAK_AUDIENCE`）、local 模式的 seed 密碼不得是預設、排程器獨立執行時要有 `REDIS_URL`、資料庫要是 MariaDB。不符合就拒絕啟動並列出原因。

| 檔案 | 誰讀 | 範本 | 用途 |
|---|---|---|---|
| `backend/.env` | 開發機的 backend 與排程器（`.venv/bin/uvicorn …`、`python -m app.scheduler`）；由 `app/core/config.py`（pydantic-settings）載入 | `backend/.env.example` | 開發：SQLite、本地帳號、內嵌排程器 |
| `frontend/.env.local` | 開發機的 Next.js（`npm run dev` / `npm run start`）；只在伺服器端讀，不會進瀏覽器 | `frontend/.env.local.example` | `BACKEND_URL`、`AUTH_MODE`、Keycloak client（prod 才需要） |
| `infra/.env` | `docker compose -f infra/docker-compose.yml --env-file infra/.env`（只跑 MariaDB / Redis） | `infra/.env.example` | image 鏡像、DB 名稱 / 帳號 / 密碼、port |
| `/etc/qr-ai-lab/qrlab.env` | 正式機的 `qrlab-backend.service` 與 `qrlab-scheduler.service`（systemd `EnvironmentFile`）；`install-02-backend.sh` 的 migration / seed 也會 source 它 | `infra/systemd/qrlab.env.example` | 正式：MariaDB、Redis、Keycloak、secrets、模型庫、GPU、使用率取樣 |
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
| `CORS_ORIGINS` | `http://localhost:3000` | 逗號分隔；正式 `https://qrit.tsmc.com` |
| `ROOT_PATH` | （空） | nginx 去掉後才轉給 backend 的對外前綴（正式 `/ai-lab-api`），讓 `/docs` 與 OpenAPI 的 servers 正確；開發留空 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./dev.db` | 正式：`mariadb+asyncmy://qr:<pw>@127.0.0.1:3307/qr_ai_lab` |
| `REDIS_URL` | （空） | backend 與排程器分開跑時必設（prod 啟動檢查）；空 = 單程序記憶體事件 bus。任務結束後其事件串流保留 7 天 |
| `DATA_ROOT` | `./data` | 產物、log、暫存輸入、`tools/`、`model_zoo/` |
| `MODEL_ZOO_ROOT` | `DATA_ROOT/model_zoo` | 預訓練權重 |
| `MODEL_ZOO_IMPORT_ROOT` | （空） | 管理員可從此資料夾匯入權重（NAS / USB） |
| `MODEL_ZOO_ALLOWED_HOSTS` | （空 = 任何） | 可下載權重的內網主機白名單 |
| `MODEL_ZOO_MAX_MB` | `20480` | 單一權重上限 |
| `AUTH_MODE` | `local` | `local` 本地帳號；`keycloak` 公司 SSO（前端要一致） |
| `AUTH_SECRET` | `dev-secret-change-me` | local 模式簽 token；dev 下也是 `DATASET_SECRET_KEY` 未設時的 Fernet 退路；prod 拒絕預設值與 < 32 字元（`openssl rand -hex 32`） |
| `ACCESS_TOKEN_MINUTES` | `720` | local token 壽命 |
| `KEYCLOAK_ISSUER` | （空） | `https://sso/realms/<realm>`，必須和 token 的 `iss` 一致 |
| `KEYCLOAK_AUDIENCE` | （空） | 設了才驗 `aud`（Keycloak 要加 audience mapper） |
| `KEYCLOAK_CLIENT_ID` | （空） | 讀 `resource_access[<client>].roles`；沒設 `KEYCLOAK_AUDIENCE` 時 token 的 `azp`（或 `aud`）必須是這個 client，別的 client 的 token 不收 |
| `KEYCLOAK_ROLE_MAP` | `superadmin:superadmin,admin:admin` | `<Keycloak role>:<系統角色>`；token 沒帶對應 role 時維持 UI 設的角色。第一次登入若接管同名的本地帳號，角色會重設為 `user`（名字相同不代表權限相同） |
| `SUPERADMIN_USERNAMES` | （空） | 登入即為 superadmin 的帳號（引導第一位） |
| `SEED_SUPERADMIN_PASSWORD` / `SEED_ADMIN_PASSWORD` / `SEED_USER_PASSWORD` | `superadmin1234` / `admin1234` / `user1234` | 只在 `AUTH_MODE=local` 時建立本地帳號（keycloak 模式不建立任何本地帳號）；prod 拒絕預設密碼 |
| `DATASET_SECRET_KEY` | （空） | Fernet key，加密使用者資料來源憑證；prod 必設且啟動時驗證格式 |
| `JOB_TOKEN_SECRET` | `dev-job-secret-change-me` | 任務子程序呼叫 `/internal/*` 的 token |
| `JOB_RUNNER` | `auto` | `auto` / `systemd` / `subprocess` |
| `SYSTEMD_USER` | `true` | `systemd-run --user`（需要 `loginctl enable-linger`） |
| `TRAINER_DIR` / `TRAINER_PYTHON` | `../trainer` / `<TRAINER_DIR>/.venv/bin/python` | 任務用的 venv |
| `SCHEDULER_EMBEDDED` | `false` | `true` = 排程器跑在 backend 程序內（開發、小型部署，不需 Redis） |
| `MEMORY_WATCHDOG` | `true` | cgroup 不可用時由排程器監看記憶體 |
| `GPU_BUSY_THRESHOLD` | `0.10` | 獨占型任務：顯存已用超過此比例的 GPU 不排 |
| `GPU_RESERVE_MB` | `512` | 依顯存共用時每張保留給驅動 / context |
| `GPU_WARMUP_S` | `120` | 在驅動程式看見任務的程序之前，整個申請量都算「尚未分配」；之後的這段時間內保留「申請 − 實測」，再之後只看實測 |
| `GPU_RESET_COMMAND` | （空） | superadmin「重置裝置」執行的指令，如 `sudo -n nvidia-smi --gpu-reset -i {index}` |
| `USAGE_SAMPLE_INTERVAL_S` / `USAGE_RETENTION_DAYS` | `30` / `90` | 使用率歷史 |
| `INTERNAL_BACKEND_URL` | `http://localhost:8000` | 任務子程序回呼 backend 的位址 |
| `SCHEDULER_INTERVAL_S` | `3` | |
| `UPLOAD_MAX_MB` / `UPLOAD_TTL_MINUTES` | `2048` / `60` | 工具上傳直接用；專案的一次性上傳以 `job_defaults` 第一次建立時的值為準（之後在後台調） |
| `PREVIEW_TIMEOUT_S` | `30` | 前處理抽樣預覽（即時）上限 |
| `LOG_MAX_MB` | `50` | 任務 log 超過時**就地截斷**只留最後 1/4（任務不會被中止） |
| `DEFAULT_JOB_TIMEOUT_MINUTES` | `240` | 只在 `system_settings.job_defaults` 第一次建立時使用；之後請在管理員後台調整（上限 14 天） |

管理員在 UI 調的值（資源池、Job 預設、工具預設 = 個人工作區配額與結果保留時間）存在 `system_settings` 表，不是環境變數。

## frontend（`frontend/.env.local` 或 `/etc/qr-ai-lab/frontend.env`）

| 變數 | 預設 | 說明 |
|---|---|---|
| `BACKEND_URL` | `http://localhost:8000` | Next.js 伺服器端打 FastAPI 的位址（瀏覽器不直接連；不含 `/ai-lab-api` 前綴） |
| `NEXT_PUBLIC_BASE_PATH` | （空） | 網站的路徑前綴（正式 `/ai-lab`）；**build 與 `next start` 都要看到同一個值**（`next.config.ts` 在兩個時間點都讀它；systemd 的 EnvironmentFile 已涵蓋），改了要重跑 `install-03-frontend.sh`；`<Link>` / `redirect` 由 Next.js 自動加，手寫的 URL 走 `withBase()` |
| `AUTH_MODE` | `local` | 與 backend 一致 |
| `AUTH_SECRET` | （keycloak 必填） | 加密 Auth.js session cookie（`openssl rand -base64 32`） |
| `AUTH_URL` | （keycloak 必填） | 對外網址**含前綴**（`https://qrit.tsmc.com/ai-lab`）；Keycloak 的 redirect URI = `$AUTH_URL/api/auth/callback/keycloak` |
| `AUTH_KEYCLOAK_ID` / `AUTH_KEYCLOAK_SECRET` / `AUTH_KEYCLOAK_ISSUER` | | confidential client |
| `AUTH_SESSION_MAX_AGE` | `43200` | session cookie 秒數；access token 只由 `src/proxy.ts` 用 refresh token 更新並寫回 cookie（同一個 refresh token 的並行刷新會去重，Keycloak 的 refresh token 輪替也安全），RSC / Route Handler 只讀不刷新 |
| `AUTH_LOCAL_FALLBACK` | `0` | `1` = keycloak 模式的登入頁也顯示本地帳號表單（切換期） |
| `COOKIE_SECURE` | （未設 = production 時 Secure） | nginx 沒有 TLS 時設 `0` |
| `PUBLIC_URL` | `AUTH_URL` | 登出後導回的網址（通常不用設） |
| `PORT` / `HOSTNAME` | `3000` / `127.0.0.1` | `next start` 直接讀這兩個變數（systemd unit 不再傳參數） |

## infra（`infra/.env`，docker compose）

| 變數 | 說明 |
|---|---|
| `DOCKER_REGISTRY` | 公司 image 鏡像前綴（含結尾斜線）；空 = Docker Hub |
| `MARIADB_ROOT_PASSWORD` / `MARIADB_DATABASE` / `MARIADB_USER` / `MARIADB_PASSWORD` / `MARIADB_PORT` | MariaDB 容器；主機 port 預設 **3307**（3306 已被占用）；`DATABASE_URL` 要用同一組帳密與 port |
| `REDIS_PORT` | Redis 容器；主機 port 預設 **6380** |

## 套件來源（伺服器不連外）

torch 另外處理：`trainer/requirements-torch.txt` 只釘 torch / torchvision 版本，安裝時用符合 **驅動** 的 index（CUDA 12.x 驅動 → `https://download.pytorch.org/whl/cu126`，13.x → `cu130`，無 GPU → `cpu`；`install-02-backend.sh` 讀 `TORCH_INDEX_URL`，內網指向 Nexus 代理的 download.pytorch.org）。torch wheel 自帶 CUDA 函式庫，`nvidia-*`、`triton` 是它的依賴會自動裝，不寫在 requirements 裡；主機裝的 CUDA toolkit 不會被用到。

全專案只用 pip（沒有 uv / poetry）：`infra/install-02-backend.sh` 以 `python3.12 -m venv` + `pip install -r requirements.txt` 安裝 backend 與 trainer；開發機用 `requirements-dev.txt`（多 pytest / ruff）。四個 `requirements*.txt` 由 `scripts/pin_requirements.sh` 依 `pyproject.toml` 的範圍釘出，CI 會比對。pip 從 `/etc/pip.conf` 讀公司的 PyPI proxy（Nexus）：

```ini
[global]
index-url = https://nexus.example.com/repository/pypi-proxy/simple
trusted-host = nexus.example.com
```

npm 從 `/etc/npmrc`（`registry=https://nexus.example.com/repository/npm-proxy/`）讀。只想在這一次安裝覆蓋時，可在執行 `install-02-backend.sh` / `install-03-frontend.sh` 的 shell 設 `PIP_INDEX_URL` / `NPM_REGISTRY`，不會寫進任何檔案。

開發機同樣是 venv + pip：`python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`，之後用 `.venv/bin/uvicorn`、`.venv/bin/pytest`、`.venv/bin/ruff`。

trainer 另外會讀 `MAX_DATALOADER_WORKERS`（DataLoader worker 上限，預設依 CPU 配額）與 `TRAINER_RETRY_SHORT_S` / `TRAINER_RETRY_LONG_S`（回呼 backend 的重試預算：進度 / 心跳預設 30 秒，最後的指標 / 產物登記 / 結果預設 600 秒，backend 短暫重啟時訓練不會因此失敗；可寫在 qrlab.env，排程器會傳給任務）；排程器另外替任務設 `YOLO_VERBOSE=false`、`TQDM_DISABLE=1`（log 一個 epoch 一行）；排程器只把 `PATH`、`HOME`、語系、proxy、`CUDA_*` / `NVIDIA_*` / `TORCH_*` / `HF_*` 等白名單變數傳給任務子程序，伺服器的 secret 不會出現在任務的環境裡。
