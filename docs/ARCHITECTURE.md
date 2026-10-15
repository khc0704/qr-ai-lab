# 系統架構

本文件描述 QR AI Lab 的元件、資料流與關鍵決策。改架構先改這裡，再改程式。

## 1. 總覽

```
 Browser ──OIDC redirect──► Keycloak（公司既有，外部）
    │
    │ HTTPS
    ▼
 nginx :80/:443
    ├─ /            ──► frontend  Next.js 16  :3000
    │                      │  server-side fetch, Authorization: Bearer <access_token>
    └─ /api/v1/*    ──► backend   FastAPI     :8000  ◄──────────────────────────┐
                           │                                                    │ /internal/*（per-job token）
            ┌──────────────┼──────────────┬──────────────┐                      │
            ▼              ▼              ▼              ▼                      │
        MariaDB :3306   Redis :6379   DATA_ROOT/      scheduler（python -m app.scheduler）
                           ▲          (本機磁碟 volume)  │ docker run --gpus --cpus --memory
                           │ events/log  ▲  bind mount   ▼
                           └─────────────┴──────── Job 容器（qr-ai-lab/trainer image）
                                                          │
                                                          ▼ 只有 Job 容器對外抓資料
                                               使用者的 MinIO / S3 或 HTTP(S) URL（外部）
```

| 元件 | 技術 | 責任 |
|---|---|---|
| frontend | Next.js 16、Auth.js（Keycloak provider） | UI、登入流程、把 access token 轉送給 backend、SSE 訂閱 |
| backend | FastAPI、SQLAlchemy async、Alembic | REST API、授權、業務邏輯、一次性上傳接收、log 讀取、SSE、catalog / SOP 提供 |
| scheduler | 同 backend 套件的獨立 process | 佇列（`queue_rank`）、總資源池與專案配額檢查、GPU 分配、啟動 / 監看 / 強制中斷 / 回收 Job 容器、寫 log 檔 |
| trainer | Python 套件 + CUDA image | 從使用者的 MinIO / URL 或上傳檔讀資料、訓練 / AutoML / 推論、回報 metrics、把產物寫到掛載的輸出目錄 |
| MariaDB | 11.x | 所有業務資料（見 `docs/DATABASE.md`） |
| Redis | 7.x | Job 事件與 log 的即時 stream（`XADD`）、scheduler 鎖 |
| DATA_ROOT | 主機目錄（例 `/srv/qr-ai-lab/data`） | 產物、log、暫存上傳、Job 執行期間的輸入副本；backend 與 scheduler 以 volume 共享 |
| Keycloak | 外部 | 身分、密碼、realm role（`admin` / `user`） |

單機部署；v1 不做多節點、不做 Kubernetes、不架自己的物件儲存。所有元件以 docker compose 管理，trainer image 單獨 build。

## 2. 認證與授權

### 2.0 過渡期：本地帳號（Keycloak 尚未接上，目前的預設）
- backend `AUTH_MODE=local`：`POST /api/v1/auth/login {username, password}` 驗 `users.password_hash`（argon2），回 HS256 access token（`AUTH_SECRET`，預設 12 小時）；`GET /api/v1/me` 取目前使用者。
- 啟動（dev / test）自動建立兩個帳號：`admin / $SEED_ADMIN_PASSWORD`（預設 `admin1234`，系統角色 admin）與 `user / $SEED_USER_PASSWORD`（預設 `user1234`）。正式環境用 `uv run python -m app.cli seed` / `create-user` / `set-password`。
- `users.auth_provider = local | keycloak`；切到 Keycloak 只要設 `AUTH_MODE=keycloak` + `KEYCLOAK_ISSUER` / `KEYCLOAK_AUDIENCE`，`get_current_user` 改驗 Keycloak JWT 並 upsert，業務表不變。
- 前端目前仍是假資料；接 backend 時登入頁改打 `/auth/login` 並把 token 放在 httpOnly cookie（server-only 的 `src/lib/api` 帶 `Authorization`）。

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
1. reconcile：對所有 scheduled / running Job 檢查容器
   - 容器結束：exit 0 且 trainer 已回報 succeeded → succeeded；否則 failed（error_message 取 log 最後 50 行）
   - 超過 timeout → docker stop → failed(timeout)
   - cancel_requested_at 有值 → docker stop → cancelled
   - 任何終態：釋放 GPU、刪 DATA_ROOT/jobs/{id}/input、把 log stream 收尾並 fsync log 檔、重算專案 storage_used_bytes
2. pool = system_settings.resource_pool；capacity = pool − Σ(scheduled/running 的配置)
3. 候選：SELECT ... FROM jobs WHERE status='queued' ORDER BY queue_rank, created_at FOR UPDATE SKIP LOCKED LIMIT 20
4. 依序對每個候選：
   - 專案層：running_jobs < max_concurrent_jobs；running_gpu + requested_gpu ≤ gpu_limit（cpu / memory 同）；storage_used < storage_quota
   - 池層：requested ≤ capacity 且 running_total < max_running_jobs
   - 通過 → 選 GPU（池內記憶體最空的 index）→ 建 per-job token → 準備目錄 → docker run → scheduled → running
   - 不通過且 allow_backfill = false → 停止本輪（嚴格依序）；true → 跳過繼續看下一個
   - 同一 tick 每個專案最多啟動一個 Job
```

- Docker 參數：`image=TRAINER_IMAGE`、`device_requests=[DeviceRequest(device_ids=[...], capabilities=[["gpu"]])]`（GPU=0 時不掛）、`nano_cpus=int(cpu*1e9)`、`mem_limit=f"{memory_mb}m"`、`memswap_limit` 同值、`read_only=True`、`tmpfs={"/tmp": "size=2g"}`、`cap_drop=["ALL"]`、`security_opt=["no-new-privileges"]`、`user="1000:1000"`、`network="qr-ai-lab_jobs"`、`labels={"qr-ai-lab.job_id": id}`、`volumes={f"{DATA_ROOT_HOST}/jobs/{id}/input": {"bind": "/job/input", "mode": "ro"}, f"{DATA_ROOT_HOST}/projects/{slug}/jobs/{id}": {"bind": "/job/output", "mode": "rw"}}`、`environment={JOB_ID, JOB_KIND, JOB_TOKEN, BACKEND_URL, CUDA_VISIBLE_DEVICES, DATA_SOURCE_*（解密後）}`。
- `DATA_ROOT_HOST` 是主機路徑：scheduler 自己跑在容器裡時，交給 docker 的 bind mount 必須用主機路徑，不是 scheduler 容器內的 `/data`。
- scheduler 單一實例；以 Redis `SET scheduler:lock NX EX 10` 心跳保證不重複。重啟後靠 reconcile 由容器 label 找回執行中的 Job。

### 6.4 Trainer 容器協定

| 步驟 | 介面 |
|---|---|
| 取 spec | `GET /internal/jobs/{id}/spec` → kind、data_type、task_type、mode、family、config、input（kind、format、spec；data_source 的連線資訊由環境變數提供）、artifact 路徑（推論）、資源限制 |
| 準備資料 | upload：`/job/input` 已就緒；data_source：trainer 用 `minio` SDK / `httpx` 下載到 `/job/input`（stage = `fetching`，進度回報） |
| 回報狀態 / 進度 | `POST /internal/jobs/{id}/status` `{status, progress, stage, message}` |
| 回報 metrics | `POST /internal/jobs/{id}/metrics` `{epoch?, trial?, metrics{}}`（AutoML 每 trial 一筆） |
| log | stdout / stderr 即可；scheduler 以 `container.logs(stream=True)` 同時寫 log 檔與 Redis stream |
| 產物 | 寫到 `/job/output/{model|preprocessor|report|metrics}/...`，再 `POST /internal/jobs/{id}/artifacts` `{name, kind, path, framework, metadata}`；backend `stat` 檔案取大小、登記 `artifacts`、檢查配額（超過 → 刪檔並回 `STORAGE_QUOTA_EXCEEDED`） |
| 推論輸出 | 小結果 `POST /internal/jobs/{id}/result`（≤ 1 MB JSON）；大結果寫 `/job/output/output.*` 並回報路徑 |
| 結束 | exit 0 = 成功（已先回報 succeeded）；非 0 = 失敗；143 = 收到 SIGTERM（取消 / 強制中斷 / 逾時） |

per-job token：HS256，payload `{sub: job_id, kind, exp: now + timeout}`，`/internal/*` 驗證 token 的 `sub` 等於路徑 id。

補充（trainer 實作，`trainer/trainer/runtime.py`）：
- spec 另帶 `families`（候選家族的 `defaults` / `search_space` / `inference_modes`）與 `zoo_weights`（權重 id → 模型庫檔名），trainer 不讀 yaml、不連網。
- 模型庫：scheduler 以唯讀掛載 `MODEL_ZOO_ROOT` 到 `/job/zoo`，並設 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`YOLO_OFFLINE=1`；缺權重時 trainer 以清楚訊息失敗（見 `docs/MODEL_CATALOG.md` §9）。
- `/job/input` 對 upload Job 是唯讀；data_source Job 可寫（trainer 下載到那裡）。zip 解壓與暫存寫到 `/job/output/_work`，trainer 結束時自刪，scheduler 在 Job 終態再保險刪一次。
- 推論：`config.mode` 選推論模式（`predict | score | embed | retrieve | detect | segment | measure | extend`），輸出 `output/predictions.csv` + `.jsonl` + `summary.json`，並以 `kind=report` 登記；`result.preview` 存前 20 列。
- 產物 `path` 可以是目錄（例如 `model/`）；`GET /artifacts/{id}/download` 會即時打包成 zip。
- 執行環境：`JOB_RUNNER=docker`（伺服器）或 `subprocess`（開發機直接以 `trainer/.venv` 跑 `python -m trainer run`，無隔離）。

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
- 前端 `LogViewer` / Job 詳情頁訂閱；列表頁與管理員佇列用 TanStack Query 每 5–10 秒 refetch。

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

## 13. 部署（公司 Ubuntu GPU 伺服器）

- 前置：Ubuntu 22.04 / 24.04、NVIDIA driver、Docker Engine + Compose plugin、NVIDIA Container Toolkit（`nvidia-ctk runtime configure`）。
- `infra/docker-compose.yml` services：`nginx`、`frontend`、`backend`、`scheduler`（掛 `/var/run/docker.sock`，只有它需要）、`mariadb`（volume）、`redis`。`backend` 與 `scheduler` 都掛 `${DATA_ROOT_HOST}:/data`。trainer image 以 `docker build -f infra/trainer/Dockerfile trainer` 單獨建置並打 tag，scheduler 用 `TRAINER_IMAGE` 指定。
- 網路：`qr-ai-lab_internal`（frontend、backend、scheduler、mariadb、redis）；`qr-ai-lab_jobs`（Job 容器 + backend，可對外抓資料，看不到 mariadb / redis）。只有 nginx 對外。Keycloak 在外部，以 `KEYCLOAK_ISSUER` 指向。
- 環境變數（`infra/.env.example`）：
  - 共用：`APP_ENV`、`PUBLIC_URL`
  - frontend：`AUTH_SECRET`、`AUTH_KEYCLOAK_ID`、`AUTH_KEYCLOAK_SECRET`、`AUTH_KEYCLOAK_ISSUER`、`BACKEND_URL`
  - backend / scheduler：`DATABASE_URL`（`mariadb+asyncmy://…`）、`REDIS_URL`、`DATA_ROOT`（容器內 `/data`）、`DATA_ROOT_HOST`（主機路徑，scheduler 用於 bind mount）、`MODEL_ZOO_ROOT`、`AUTH_MODE`（`local` 過渡 / `keycloak`）、`AUTH_SECRET`、`SEED_ADMIN_PASSWORD`、`SEED_USER_PASSWORD`、`KEYCLOAK_ISSUER`、`KEYCLOAK_AUDIENCE`、`DATASET_SECRET_KEY`（Fernet）、`JOB_TOKEN_SECRET`、`JOB_RUNNER`、`TRAINER_IMAGE`、`JOB_NETWORK`、`INTERNAL_BACKEND_URL`、`SCHEDULER_INTERVAL_S`、`UPLOAD_MAX_MB`、`UPLOAD_TTL_MINUTES`、`LOG_MAX_MB`、`DEFAULT_JOB_TIMEOUT_MINUTES`
- compose：`backend` 與 `scheduler` 在 profile `app`（`docker compose --profile app up -d`），image 由 `infra/backend/Dockerfile` 建置；frontend / nginx 待前端接上 backend 後加入。
- 更新流程：`git pull` → `docker compose --profile app build backend scheduler` → `docker compose --profile app run --rm backend alembic upgrade head` → `docker compose --profile app up -d`。
- 模型庫：在有網路的機器 `python3 scripts/fetch_model_zoo.py --dest model_zoo`，複製到 `${DATA_ROOT_HOST}/model_zoo`。
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
