# 系統架構

本文件描述 QR AI Lab 的元件、資料流與關鍵決策。改架構先改這裡，再改程式。

## 1. 總覽

```
 Browser ──OIDC redirect──► Keycloak（公司既有，內網）
    │
    │ HTTPS
    ▼
 nginx :443（主機原生）
    ├─ /            ──► frontend  Next.js 16  :3000   systemd: qrlab-frontend
    │                      │  server-side fetch, Authorization: Bearer <token>（httpOnly cookie）
    └─ /api/v1/*    ──► backend   FastAPI     :8000   systemd: qrlab-backend  ◄──────────────┐
                           │                                                                 │ /internal/*（per-job token）
            ┌──────────────┼──────────────┬──────────────┐                                   │
            ▼              ▼              ▼              ▼                                   │
        MariaDB :3306   Redis :6379   DATA_ROOT/      scheduler（python -m app.scheduler）  systemd: qrlab-scheduler
        (docker compose) (docker compose) 主機目錄        │ systemd-run --scope（cgroup：MemoryMax / CPUQuota / AllowedCPUs）
                           ▲ events        ▲ 讀寫同一目錄   ▼
                           └───────────────┴──── Job = 主機子程序 trainer/.venv/bin/python -m trainer run
                                                      │  CUDA_VISIBLE_DEVICES、HF_HUB_OFFLINE=1 …
                                                      ▼ 只有 Job 對內網抓資料
                                           使用者的 MinIO / S3 或 HTTP(S) URL（內網）
```

| 元件 | 技術 | 責任 |
|---|---|---|
| frontend | Next.js 16（Server Components / Actions、Route Handler 代理） | UI、登入、把 token 以 httpOnly cookie 保存並在伺服器端轉送給 backend、SSE / 上傳 / 下載代理 |
| backend | FastAPI、SQLAlchemy async、Alembic | REST API、授權、業務邏輯、一次性上傳接收、前處理預覽、log 讀取、SSE、catalog / SOP、模型庫管理 |
| scheduler | 同 backend 套件的獨立 process（或 `SCHEDULER_EMBEDDED=true` 跑在 backend 內） | 佇列（`queue_rank`）、總資源池與專案配額檢查、GPU / CPU 核心分配、以主機子程序啟動 / 監看 / 強制中斷 / 回收 Job、tail log 檔並推到事件 bus |
| trainer | Python 套件，裝在主機的 `trainer/.venv`（torch CUDA wheel、ultralytics、transformers…） | 從使用者的 MinIO / URL 或上傳檔讀資料、訓練 / AutoML / 推論、回報 metrics、把產物寫到 Job 輸出目錄、把 log 寫到 Job 的 log 檔 |
| MariaDB | 11.x（docker compose，image 來自公司鏡像） | 所有業務資料（見 `docs/DATABASE.md`） |
| Redis | 7.x（docker compose） | Job 事件與 log 的即時 stream；backend 與 scheduler 分開跑時必要，內嵌模式不需要 |
| DATA_ROOT | 主機目錄（例 `/srv/qr-ai-lab/data`） | 產物、log、暫存上傳、Job 執行期間的輸入副本、模型庫 `model_zoo/` |
| Keycloak | 內網既有 | 身分、密碼、realm role（`admin` / `user`） |

單機部署；v1 不做多節點、不做 Kubernetes、不架自己的物件儲存。**Job 不跑在容器裡**：所有任務都是同一個主機 venv 的子程序，資源限制交給 cgroups（systemd）或排程器的 watchdog；Docker 只用來跑 MariaDB 與 Redis。伺服器不連外網：套件來自公司的 PyPI / npm / image 鏡像，預訓練權重由管理員經「模型庫」頁帶進來。

## 2. 認證與授權

### 2.0 過渡期：本地帳號（Keycloak 尚未接上，目前的預設）
- backend `AUTH_MODE=local`：`POST /api/v1/auth/login {username, password}` 驗 `users.password_hash`（argon2），回 HS256 access token（`AUTH_SECRET`，預設 12 小時）；`GET /api/v1/me` 取目前使用者。
- 啟動（dev / test）自動建立兩個帳號：`admin / $SEED_ADMIN_PASSWORD`（預設 `admin1234`，系統角色 admin）與 `user / $SEED_USER_PASSWORD`（預設 `user1234`）。正式環境用 `uv run python -m app.cli seed` / `create-user` / `set-password`。
- `users.auth_provider = local | keycloak`；切到 Keycloak 只要設 `AUTH_MODE=keycloak` + `KEYCLOAK_ISSUER` / `KEYCLOAK_AUDIENCE`，`get_current_user` 改驗 Keycloak JWT 並 upsert，業務表不變。
- 前端（已實作）：登入頁的 Server Action `loginAction` 打 `/auth/login`，把 access token 放在 httpOnly cookie `qr_token`（與 `expires_in` 同步到期）；`src/proxy.ts` 只看 cookie 有無：未登入導向 `/login?next=`、已登入離開 `/login`。所有讀取走 `src/lib/api`（`server-only` fetch，帶 `Authorization`，snake_case → camelCase 在 `mappers.ts`），寫入走 `src/lib/actions.ts`（Server Actions，回傳 `{ok, data | error}` 並 `revalidatePath`）；401 / 403 由 `getCurrentUser` 清 cookie 並導向 `/login?reason=expired`。瀏覽器需要直接串流 / 傳檔的三件事由 Route Handler 代理（token 不出伺服器）：`POST /api/upload/[slug]`（multipart → backend uploads）、`GET /api/stream/jobs/[id]`（SSE 轉發，含 `Last-Event-ID`）、`GET /api/download/[...path]`（白名單：artifacts / job logs / job output）。

### 2.1 登入流程（Keycloak，目標狀態）
1. 使用者在 frontend 點登入 → Auth.js 導向 Keycloak（Authorization Code + PKCE）。
2. Keycloak 回呼 `/api/auth/callback/keycloak`；Auth.js 以 JWT session 保存 `access_token`、`refresh_token`、`expires_at`、`roles`（從 token 的 `realm_access.roles` 取）。
3. `src/proxy.ts` 對 `(app)` 路由檢查 session，未登入導向 `/login`。
4. Server Component / Server Action 透過 `@/lib/api`（`server-only`）呼叫 backend，自動帶 `Authorization: Bearer <access_token>`；到期前 60 秒用 refresh token 向 Keycloak 換新（Auth.js `jwt` callback）。
5. 瀏覽器端只有 SSE 需要直接連 backend：由 Route Handler `/api/stream/jobs/[id]` 代理（server 端帶 token）。

### 2.2 backend 驗證
- `core/security.py`：PyJWT + `PyJWKClient`（JWKS 快取 1 小時），驗 `iss`、`aud`（或 `azp`）、`exp`。
- `get_current_user`：以 `sub` upsert `users`（同步 `email`、`preferred_username`、display name、`role` = realm role 含 `admin` ? admin : user、`last_login_at`）。
- `require_admin`、`require_project_role(min_role)`：以 `project_members` 判斷；admin 隱含所有專案的 owner 權限。

### 2.3 權限矩陣

| 動作 | admin | owner | maintainer | member | viewer |
|---|---|---|---|---|---|
| 審核專案申請、調配額、改系統角色 | ✓ | | | | |
| 設定總資源池、重排佇列、強制中斷任何 Job、看所有 Job log | ✓ | | | | |
| 封存專案、改專案設定 | ✓ | ✓ | | | |
| 管理成員 | ✓ | ✓ | ✓ | | |
| 新增 / 刪除資料來源、建立 / 取消本專案的 Job、設預設模型 | ✓ | ✓ | ✓ | ✓ | |
| 讀取專案、下載產物、看本專案 Job 的 log | ✓ | ✓ | ✓ | ✓ | ✓ |
| 提出專案申請、在討論區開單與回覆 | 所有登入者 | | | | |

## 3. 討論區

- 全域、獨立於專案申請的問題單區：`issues.type = question | bug | feature`，`status = open | closed`。
- 任何登入者可開單、在自己或他人的單下留言；admin 可回覆、指派、關閉（需填 `resolution_note`）、重開。
- 可選擇關聯既有專案（`project_id`），方便針對某專案提問。
- 留言存在多型 `comments` 表（`target_type = issue`）；狀態變更以 `kind = system` 的留言呈現在時間軸。

## 4. 專案申請與審批

- 獨立的「專案申請」區：`project_requests` 表，結構化欄位（題目、目的、資料類型、任務、資料量級、資料描述、需求 GPU / CPU / Memory / Storage、建議 slug、預計成員 email）。
- 狀態機：`submitted → in_review → approved | rejected`；`rejected → submitted`（申請人修改後重送）；申請人可 `withdrawn`。
- 審核過程的往返用 `comments`（`target_type = project_request`）；admin 要求補件時留言並維持 `in_review`。
- 核准（`POST /project-requests/{id}/approve`，admin）在一個交易內：建立 `projects`（slug、配額，可修改申請值）、加 owner 與已存在的成員（其餘留在 `members` 待其登入後由 owner 邀請）、建立 `DATA_ROOT/projects/{slug}/`、申請標 `approved` 並寫 system comment、寫 `audit_logs`。
- 退回需填 `review_note`。

## 5. 資料來源與一次性上傳（不留存政策）

本服務不保存使用者的資料集。資料只以兩種形式短暫存在，Job 結束（任何終態）後由 scheduler 刪除：

| 形式 | 來源 | 存放 | 生命週期 |
|---|---|---|---|
| 一次性上傳 | 建立 Job 精靈中的 multipart 上傳（上限 `UPLOAD_MAX_MB`） | `DATA_ROOT/uploads/{upload_id}/` → 建立 Job 時搬到 `DATA_ROOT/jobs/{job_id}/input/` | 未綁定 Job 的上傳 `UPLOAD_TTL_MINUTES`（預設 60）後清除；Job 結束即刪 `input/` |
| 資料來源（`data_sources`） | 使用者自己的 MinIO / S3 相容（endpoint、bucket、object path、access key、secret key）或 HTTP(S) URL（可帶 headers） | DB 只存連線參考 + Fernet 加密憑證；Job 容器啟動時由 trainer 自己下載到 `/job/input` | 參考跟著專案；下載的副本 Job 結束即刪 |

- 上傳流程：`POST /projects/{slug}/uploads`（multipart，串流寫檔，不進記憶體）→ 回 `upload_id` 與偵測到的 `spec`（表頭、列數估計、影像數、類別）→ `POST /projects/{slug}/jobs` 帶 `input.upload_id`。
- `POST /projects/{slug}/data-sources/{id}/check` 由 backend 以使用者憑證做輕量連線檢查（list 前幾個物件 / HEAD）並記錄 `last_check_ok`；不下載內容。
- 憑證永遠不回前端（API 只回 `has_credentials: true`）、不進 log；只在 scheduler 組裝 Job 容器的環境變數時解密。
- Job 容器以 `--read-only` rootfs 執行，只有 `/job/input`、`/job/output`、`/tmp` 可寫。

## 6. Job 生命週期（訓練與推論統一為 `jobs`）

### 6.1 狀態機

```
queued ──(scheduler 依 queue_rank 選中並分配資源)──► scheduled ──(容器啟動)──► running ──► succeeded
   │                                                     │                         ├──► failed
   └──(使用者取消)──► cancelled ◄────────────────────────┴──(取消 / admin 強制中斷 / 逾時 → docker stop)┘
```

- 建立：`POST /projects/{slug}/jobs` 驗證 input（upload 或 data_source）、catalog（family 與 task 相容）、資源請求 ≤ 專案配額 → 寫 row（`queued`，`queue_rank = max + 1000`）→ 202。
- 每次狀態變更：更新 `jobs`、`XADD job:{id}:events`、寫 log 檔一行 `[system]`、取消 / 中斷 / 失敗再寫 `audit_logs`。
- 逾時：`timeout_minutes`（預設取 `system_settings.job_defaults`，上限由專案配額）。

### 6.2 佇列順序與管理員控制

- 全域單一佇列：`status = queued` 的 Job 依 `queue_rank ASC, created_at ASC`，訓練與推論同一條。
- 新 Job 排在最後（`max(queue_rank) + 1000`）。admin 重排：`PUT /admin/queue/order {job_ids: [...]}` 依傳入順序以 1000 為步進重新編號；也提供 `POST /admin/queue/{id}/move {position: top | up | down | bottom}`。
- 一般使用者只能取消自己專案的 Job，不能改順序。
- 強制中斷：`POST /admin/jobs/{id}/stop {reason}` → 設 `cancel_requested_at`、`cancel_requested_by_id`、`cancel_reason` → scheduler `docker stop`（10 秒寬限後 kill）→ `cancelled`；理由顯示在 Job 詳情與 log 末行，並寫 `audit_logs`。
- 總資源池：`system_settings.resource_pool = {gpu_indices: [0,1], cpu_cores: 24, memory_mb: 98304, max_running_jobs: 4, allow_backfill: true}`。scheduler 的容量 = 資源池 − 執行中 Job 的配置；專案配額只是各專案的上限，合計不得超過池。admin 在 Dashboard 編輯，旁邊顯示 pynvml / psutil 的實體數值；超過實體會被 clamp 並警告。改動只影響之後的啟動。

### 6.3 Scheduler 迴圈（每 3 秒）

```
1. reconcile：對所有 scheduled / running Job 檢查子程序
   - 程序結束：trainer 已回報 succeeded（且 exit 0 或重啟後接回而不知 exit code）→ succeeded；否則 failed（error_message 取 log 末尾）
   - 超過 timeout → SIGTERM 整個 process group / systemctl stop scope，10 秒後 SIGKILL → failed(timeout)
   - cancel_requested_at 有值 → 同上 → cancelled
   - watchdog（runner 無法由 cgroup 強制時）：process tree 的 PSS 連續兩次超過申請記憶體的 105% → 停止 → failed(memory limit)；log 檔超過 LOG_MAX_MB → 停止
   - 排程器重啟：以 jobs.container_id 存的 handle（pid + create_time，或 systemd unit 名）找回程序並重新 tail log；找不到才標 failed
   - 任何終態：釋放 GPU / CPU 核心、刪 DATA_ROOT/jobs/{id}/input、重算專案 storage_used_bytes
2. pool = system_settings.resource_pool；capacity = pool − Σ(scheduled/running 的配置)；pool 的 CPU 核心 = 排程器看得到的最低 N 個邏輯 CPU
3. 候選：SELECT ... FROM jobs WHERE status='queued' ORDER BY queue_rank, created_at LIMIT 50
4. 依序對每個候選：
   - 專案層：running_jobs < max_concurrent_jobs；running_gpu + requested_gpu ≤ gpu_limit（cpu / memory 同）；storage_used < storage_quota
   - 池層：requested ≤ capacity 且 running_total < max_running_jobs
   - GPU 預檢：pynvml 看分到的 GPU 顯存使用率 > GPU_BUSY_THRESHOLD（別的程序在用）→ 這輪先等，log 說明
   - 通過 → 分配 GPU 與 CPU 核心 → 建 per-job token → 準備目錄 → 啟動 → scheduled → running
   - 不通過且 allow_backfill = false → 停止本輪（嚴格依序）；true → 跳過繼續看下一個
   - 同一 tick 每個專案最多啟動一個 Job
```

- Runner（`app/scheduler/runner.py`，`JOB_RUNNER=auto | systemd | subprocess`）：
  - `systemd`：`systemd-run --user --scope --unit=qrlab-job-{id} -p MemoryMax={mb}M -p MemorySwapMax=0 -p CPUQuota={cpu×100}% -p AllowedCPUs={cores} -p RuntimeMaxSec={timeout} -- <trainer venv python> -m trainer run`。整棵 process tree 在同一個 cgroup，核心強制記憶體 / CPU 時間 / 核心集合；`systemctl --user stop` 殺掉所有子程序；排程器重啟不影響任務。需要 `loginctl enable-linger qrlab` 與 user slice 委派 `cpu memory pids cpuset`（啟動時偵測，缺的由 watchdog 補）。
  - `subprocess`：`start_new_session` 自成 process group、`psutil.cpu_affinity` 釘在分到的核心、`OMP/MKL/TORCH_NUM_THREADS` = 申請核數；記憶體靠 watchdog。開發機、WSL、沒有 systemd user manager 的環境用這個。
  - `auto`（預設）：啟動時試跑 `systemd-run --user --scope -- /bin/true`，成功用 systemd，否則 subprocess；管理員 Dashboard 的「任務執行方式」會顯示實際用的 runner 與各項限制是 cgroup 還是 watchdog。
- 每個 Job 的環境變數：`JOB_ID, JOB_KIND, JOB_TOKEN, BACKEND_URL, JOB_INPUT_DIR, JOB_OUTPUT_DIR, JOB_MODEL_DIR, MODEL_ZOO_ROOT, CUDA_VISIBLE_DEVICES, OMP_NUM_THREADS…, HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, YOLO_OFFLINE=1, WANDB_DISABLED, DATA_SOURCE_*（解密後）`。
- Job 的 stdout / stderr 直接寫到 `projects/{slug}/jobs/{id}/logs/job.log`（trainer 自己加時間戳與 `[LEVEL]`），排程器每 0.5 秒 tail 新行推到事件 bus；`[SYSTEM]` 行由排程器寫進同一個檔。
- scheduler 單一實例（systemd 服務）；內嵌模式時 backend 只能跑一個 worker。

### 6.4 Trainer 協定（主機子程序）

| 步驟 | 介面 |
|---|---|
| 取 spec | `GET /internal/jobs/{id}/spec` → kind、data_type、task_type、mode、family、config、input（kind、format、spec；data_source 的連線資訊由環境變數提供）、artifact 路徑（推論）、資源限制 |
| 準備資料 | upload：`JOB_INPUT_DIR` 已就緒；data_source：trainer 用 `minio` SDK / `httpx` 下載到 `JOB_INPUT_DIR`（stage = `fetching`，進度回報） |
| 回報狀態 / 進度 | `POST /internal/jobs/{id}/status` `{status, progress, stage, message}` |
| 回報 metrics | `POST /internal/jobs/{id}/metrics` `{epoch?, trial?, metrics{}}`（AutoML 每 trial 一筆） |
| log | stdout（`<iso>Z [LEVEL] text`）直接進 log 檔；scheduler tail 後推 SSE |
| 產物 | 寫到 `JOB_OUTPUT_DIR/{model|preprocessor|report|metrics}/...`，再 `POST /internal/jobs/{id}/artifacts` `{name, kind, path, framework, metadata}`；backend `stat` 檔案取大小、登記 `artifacts`、檢查配額（超過 → 刪檔並回 `STORAGE_QUOTA_EXCEEDED`） |
| 推論輸出 | 小結果 `POST /internal/jobs/{id}/result`（≤ 1 MB JSON）；大結果寫 `JOB_OUTPUT_DIR/output/*` 並回報路徑 |
| 結束 | exit 0 = 成功（已先回報 succeeded）；非 0 = 失敗；143 = 收到 SIGTERM（取消 / 強制中斷 / 逾時） |

per-job token：HS256，payload `{sub: job_id, kind, exp: now + timeout}`，`/internal/*` 驗證 token 的 `sub` 等於路徑 id。

補充（trainer 實作，`trainer/trainer/runtime.py`）：
- spec 另帶 `families`（候選家族的 `defaults` / `search_space` / `inference_modes`）與 `zoo_weights`（權重 id → 模型庫檔名），trainer 不讀 yaml、不連網。
- 模型庫：`MODEL_ZOO_ROOT` 直接是主機路徑，runner 設 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`YOLO_OFFLINE=1`；缺權重時 backend 在建立任務時就拒絕（`WEIGHTS_MISSING`，精靈顯示「缺權重」），trainer 端也會以清楚訊息失敗（見 `docs/MODEL_CATALOG.md` §9）。
- zip 解壓與暫存寫到 `JOB_OUTPUT_DIR/_work`，trainer 結束時自刪，scheduler 在 Job 終態再保險刪一次；`JOB_INPUT_DIR` 在 Job 終態整個刪除。
- 推論：`config.mode` 選推論模式（`predict | score | embed | retrieve | detect | segment | measure | extend`），輸出 `output/predictions.csv` + `.jsonl` + `summary.json`，並以 `kind=report` 登記；`result.preview` 存前 20 列。
- 產物 `path` 可以是目錄（例如 `model/`）；`GET /artifacts/{id}/download` 會即時打包成 zip。
- 隔離等級：任務與排程器是同一個 OS 使用者（`qrlab`），彼此可讀對方的產物目錄；使用者只提交資料與設定、不提交程式碼，因此先以 cgroup 限資源為主。要升級隔離時改用 system 層的 `systemd-run`（`DynamicUser=`、`ProtectSystem=strict`、`ReadWritePaths=`），介面不變。
- 前處理：`input.spec.preprocess` 的步驟由共用套件 `libs/preprocess`（`qrlab_preprocess`）定義；backend 用它做上傳抽樣預覽與驗證，trainer 在訓練時 fit 並把狀態存成 `model/preprocess.json` + 產物 metadata，推論時 replay。

## 7. Log

- 每個 Job 一個檔：`DATA_ROOT/projects/{slug}/jobs/{job_id}/logs/job.log`（`jobs.log_path`），由 scheduler 寫入：容器 stdout / stderr 逐行加時間戳，加上 `[system]` 行（排程、啟動、取消、中斷理由、逾時、結束碼）。
- 即時：同一行同時 `XADD job:{id}:events {type: log}`；SSE 推到前端 `LogViewer`。
- 歷史：`GET /jobs/{id}/logs?offset=&limit=`（以行為單位分頁，預設最後 500 行）與 `GET /jobs/{id}/logs/download`。Job 結束後只走檔案。
- 權限：專案成員（含 viewer）看本專案 Job 的 log；admin 看全部，入口在管理員「佇列」頁的 Job 抽屜。
- 保留：跟著 Job；admin 可刪 Job（連 log 與產物一起，需確認）。超大 log 以 50 MB 為上限，超過後輪替為 `job.log.1`。
- scheduler 自身的 log 走 stdout（`docker compose logs scheduler`），v1 不做 UI。

## 8. AutoML（`mode = auto`）

1. backend 依 `(data_type, task_type, input.spec.row_count / image_count)` 從 `model_catalog.yaml` 選候選 family（見 `docs/MODEL_CATALOG.md` §5），寫入 `config.search = {candidates, max_trials, time_budget_minutes, metric, direction}`。
2. trainer 建一個 Optuna study：trial 先抽 family（categorical）再抽該 family 的搜尋空間；`MedianPruner`；超過時間或 trial 數即停。
3. 每個 trial 結束回報 `{trial, family, params, metrics, duration_s}`；backend 累積到 `jobs.metrics.leaderboard`。
4. 結束時最佳 trainer 執行 `finalize`（表格家族以全部資料重訓），匯出產物；`result.model_family` 回填 `jobs.model_family`，產物 `metadata.family` 記錄贏家；第一個模型自動成為專案預設模型。
5. 單容器循序執行，資源配置與手動 Job 相同；沒申請 GPU 時需要 GPU 的候選會被剔除（全部被剔除 → `GPU_REQUIRED`）。時間預算 = min(`time_budget_minutes`, Job timeout × 0.85)。

## 9. 推論

- v1：批次推論。`POST /projects/{slug}/jobs` 帶 `kind = inference`、`artifact_id`、`input`（inline JSON、一次性上傳、data_source）→ 同一條佇列、同一個 trainer image（`trainer infer`）。
- 輸出：小結果寫 `jobs.result`，大結果寫 `output_path`（`DATA_ROOT/projects/{slug}/jobs/{id}/output/`），`GET /jobs/{id}/download` 串流下載。
- 推論 Job 預設 GPU=0、CPU 1、Memory 2 GB；vision / text 家族可申請 GPU。
- 推論模式 `config.mode`（模型 metadata 的 `inference_modes` 第一個為預設）：`predict`、`score`、`embed`、`retrieve`、`detect`、`segment`、`measure`、`extend`；情境說明見 `docs/USE_CASES.md` §1。
- 產物目錄的模型（`/job/model/<file>`）由 scheduler 唯讀掛載該產物所在的 Job 輸出目錄。
- v2 候選：常駐推論服務（模型暖載、同步 API）。先不做。

## 10. 儲存配置（`DATA_ROOT`）

```
DATA_ROOT/
├─ projects/{slug}/
│  └─ jobs/{job_id}/
│     ├─ model/  preprocessor/  report/  metrics/   訓練產物（artifacts.path 相對於 DATA_ROOT）
│     ├─ output/                                     推論輸出
│     └─ logs/job.log                                 §7
│     ├─ _work/                                       trainer 暫存（zip 解壓等），Job 結束即刪
├─ jobs/{job_id}/input/                              Job 執行期間的輸入（上傳或下載副本），結束即刪
├─ uploads/{upload_id}/                              未綁定 Job 的一次性上傳，TTL 後清除
└─ model_zoo/                                        預訓練權重（MODEL_ZOO_ROOT；管理員放入，唯讀掛進 Job 容器）
```

- 配額：`projects.storage_used_bytes` = `projects/{slug}/` 的實際大小，於 Job 終態、產物登記、產物刪除時重算（`os.scandir` 遞迴，backend `storage/local.py`）。超過 `storage_quota_mb` 時新 Job 不會被排程（UI 顯示原因）。
- 下載：`GET /artifacts/{id}/download` 以 `FileResponse` 串流；大檔可改 nginx `X-Accel-Redirect`（`internal` location 指向 DATA_ROOT）。
- 清理任務（scheduler 每小時）：過期 uploads、孤兒 `jobs/{id}/input`、已刪 Job 的目錄。
- 介面：`backend/app/storage/base.py` 定義 `Storage`（`open_write`、`open_read`、`stat`、`delete`、`usage(prefix)`、`mount_spec(job)`），v1 只有 `LocalStorage`；未來自有 MinIO 時加 `ObjectStorage` 並改用 presigned URL 給 trainer。
- 備份：`DATA_ROOT` 由主機排程備份；MariaDB 每日 `mariadb-dump` 到 `DATA_ROOT/../backups/`。

## 11. 即時事件

- Redis stream `job:{id}:events`（`MAXLEN ~ 10000`）：`{type: status | progress | metric | log, ts, data}`。
- `GET /api/v1/jobs/{id}/events`（SSE）：先送最近 200 筆，再 `XREAD BLOCK`；支援 `Last-Event-ID` 續傳；Job 結束後送 `event: end` 關閉。
- 前端 Job 詳情頁的 `JobLive`（client component）用 `EventSource('/api/stream/jobs/{id}')` 訂閱：`log` 事件直接 append 到 `LogViewer`，`progress` 更新進度卡，`status` / `metric` / `end` 觸發節流的 `router.refresh()`，讓伺服器渲染的指標、leaderboard、產物跟上；Job 結束後不再開連線（log 由 `GET /jobs/{id}/logs` 一次讀完）。管理員佇列抽屜共用同一元件。列表頁為 RSC，重新整理即最新。

## 12. API 清單（v1，前綴 `/api/v1`）

```
GET    /me                                   目前使用者（含 role、所屬專案摘要）
GET    /users  PATCH /users/{id}             admin；role、is_active
GET    /catalog                              data types、tasks、families、搜尋空間、SOP 章節
GET    /issues  POST /issues                 討論區列表（type、status、mine、q）/ 開單
GET    /issues/{id}  PATCH /issues/{id}      詳情 / 作者或 admin 編輯
POST   /issues/{id}/comments  POST /issues/{id}/close  POST /issues/{id}/reopen
GET    /project-requests  POST /project-requests        我的申請（admin：全部）/ 送出申請
GET    /project-requests/{id}  PATCH /project-requests/{id}  詳情 / 申請人修改（submitted 或 rejected 時）
POST   /project-requests/{id}/comments
POST   /project-requests/{id}/withdraw
POST   /project-requests/{id}/review         admin；status → in_review
POST   /project-requests/{id}/approve        admin；body: slug、quota、members → 建立專案
POST   /project-requests/{id}/reject         admin；body: review_note
GET    /projects  GET /projects/{slug}  PATCH /projects/{slug}  POST /projects/{slug}/archive
PATCH  /projects/{slug}/quota                admin
GET    /projects/{slug}/members  POST …  PATCH …/{user_id}  DELETE …/{user_id}
GET    /projects/{slug}/data-sources  POST …  PATCH …/{id}  DELETE …/{id}  POST …/{id}/check
POST   /projects/{slug}/uploads              multipart → upload_id + spec（一次性）
GET    /projects/{slug}/jobs  POST …          建立訓練或推論 Job（202）
GET    /jobs                                  最近任務（我參與的專案；admin：全部）
GET    /capacity                              總資源池 + 已配置量（任何登入者；給精靈與首頁）
POST   /projects/{slug}/uploads/{id}/preview  前處理抽樣預覽（steps、sample、spec）；GET /catalog/preprocess?data_type=
GET    /jobs/{id}  POST /jobs/{id}/cancel     成員取消
GET    /jobs/{id}/events(SSE)  GET /jobs/{id}/logs  GET /jobs/{id}/logs/download  GET /jobs/{id}/download
GET    /projects/{slug}/artifacts  PATCH /artifacts/{id}(is_default)  GET /artifacts/{id}/download  DELETE /artifacts/{id}
GET    /admin/overview                        待審申請數、佇列長度、執行中數、池使用率
GET    /admin/node                            每張 GPU 使用率 / 記憶體、CPU、memory、disk（實體）
GET    /admin/settings/resource-pool  PUT …   總資源池
GET    /admin/queue                           queued + running 的統一列表（含專案、資源、等待時間）
PUT    /admin/queue/order  POST /admin/queue/{id}/move
POST   /admin/jobs/{id}/stop                  強制中斷（reason）
DELETE /admin/jobs/{id}                       刪除 Job 與其產物 / log
GET    /admin/audit
GET    /internal/jobs/{id}/spec  POST …/status  POST …/metrics  POST …/artifacts  POST …/result
GET    /healthz  GET /readyz
```

## 13. 部署（公司 Ubuntu GPU 伺服器，不連外網）

- 前置：Ubuntu 22.04 / 24.04、NVIDIA driver（只要 driver；CUDA 函式庫隨 torch wheel 來）、Docker Engine + Compose plugin（只跑 MariaDB / Redis）、Python 3.12 + uv、Node ≥ 20.9、nginx。套件來源：公司的 PyPI 鏡像（`UV_INDEX_URL` / `PIP_INDEX_URL`）、npm 鏡像（`npm config set registry`）、image 鏡像（`infra/.env` 的 `DOCKER_REGISTRY`）。
- 程式放 `/opt/qr-ai-lab`（git checkout），資料放 `/srv/qr-ai-lab/data`（`DATA_ROOT`，含 `model_zoo/`），權重傳輸資料夾 `/srv/qr-ai-lab/transfer`（`MODEL_ZOO_IMPORT_ROOT`）。專用使用者 `qrlab`，`loginctl enable-linger qrlab`（任務的 systemd scope 跑在它的 user slice）。
- `infra/install.sh`：建 venv（backend `--extra gpu`、trainer `--extra dl`）、`next build`、`alembic upgrade head` + `app.cli seed`、安裝 `infra/systemd/qrlab-{backend,scheduler,frontend}.service` 並啟動；`--update` 在 `git pull` 後重跑。環境變數在 `/etc/qr-ai-lab/qrlab.env`（範本 `infra/systemd/qrlab.env.example`）。
- nginx：`infra/nginx/qr-ai-lab.conf`（TLS 用公司 CA；`/api/v1` 轉 8000、其餘轉 3000；關閉 buffering 讓 SSE 與上傳串流）。沒有 TLS 時前端要設 `COOKIE_SECURE=0`，否則登入 cookie 不會被瀏覽器保存。
- 任務執行：`JOB_RUNNER=auto`（systemd cgroup；Dashboard 會顯示實際偵測結果）。沒有任何容器，也不需要 NVIDIA Container Toolkit。
- 模型庫：管理員在 `/admin/model-zoo` 用三種方式之一把權重帶進來：瀏覽器上傳、伺服器路徑（`MODEL_ZOO_IMPORT_ROOT`）、內網 URL（`MODEL_ZOO_ALLOWED_HOSTS`）。有網路的機器可先用 `scripts/fetch_model_zoo.py` 抓好再整個資料夾放到傳輸資料夾。
- 更新流程：`git pull` → `./infra/install.sh --update`（重 sync venv、重建前端、migration、重啟三個服務；執行中的任務不受排程器重啟影響）。
- 磁碟：`DATA_ROOT` 放在大容量磁碟；admin Dashboard 顯示剩餘空間；低於 10% 時新 Job 不排程並告警。

## 14. 安全性注意事項

- scheduler 持有 docker socket 等同主機 root：只跑受信任的 trainer image；Job 容器非 root、`cap_drop ALL`、`no-new-privileges`、唯讀 rootfs、只掛自己的 input（ro）與 output（rw）。
- 使用者資料集憑證：加密儲存、不入 log、不回前端；只以環境變數進入該 Job 容器。
- 上傳：大小上限、副檔名白名單、串流寫檔、路徑由伺服器產生（不用使用者檔名當路徑）。
- 所有管理員操作與 Job 狀態變更寫 `audit_logs`；UI 二次確認。
- 速率限制：登入後的 API 以 user 為鍵（slowapi），`/internal/*` 以 job 為鍵。

## 15. v1 範圍與未來

- v1：單節點、本機儲存、批次推論、AutoML 單容器循序、SSE 代理、繁體中文 UI。
- 未來候選：自有 MinIO（`ObjectStorage`）、多節點（Ray 或 K8s Jobs）、常駐推論服務、實驗比較頁、通知（email / Teams）、i18n。
