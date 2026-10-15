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
    └─ /api/v1/*    ──► backend   FastAPI     :8000  ◄──────────────────────────────┐
                           │                                                        │
            ┌──────────────┼──────────────┬──────────────┐                          │ /internal/*（per-job token）
            ▼              ▼              ▼              ▼                          │
        MariaDB :3306   Redis :6379   MinIO :9000    scheduler（python -m app.scheduler）
                           ▲              ▲              │ docker run --gpus --cpus --memory
                           │ log/events   │ presigned    ▼
                           └──────────────┴──────── trainer container（qr-ai-lab/trainer image）
```

| 元件 | 技術 | 責任 |
|---|---|---|
| frontend | Next.js 16、Auth.js（Keycloak provider） | UI、登入流程、把 access token 轉送給 backend、SSE 訂閱 |
| backend | FastAPI、SQLAlchemy async、Alembic | REST API、授權、業務邏輯、presigned URL、SSE、catalog / SOP 提供 |
| scheduler | 同 backend 套件的獨立 process | 佇列輪詢、配額與節點容量檢查、GPU 分配、啟動 / 監看 / 回收訓練與推論容器 |
| trainer | Python 套件 + CUDA image | 載入資料集、訓練 / AutoML / 推論、回報 metrics 與 log、上傳產物 |
| MariaDB | 11.x | 所有業務資料（見 `docs/DATABASE.md`） |
| Redis | 7.x | job 事件與 log stream（`XADD`）、scheduler 鎖、短期快取 |
| MinIO | 最新穩定版 | 專案產物空間、暫存資料集、推論輸出；單一 bucket `qr-ai-lab` 以 prefix 分隔 |
| Keycloak | 外部 | 身分、密碼、realm role（`admin` / `user`） |

單機部署；v1 不做多節點、不做 Kubernetes。所有元件以 docker compose 管理，trainer image 單獨 build。

## 2. 認證與授權

### 2.1 登入流程
1. 使用者在 frontend 點登入 → Auth.js 導向 Keycloak（Authorization Code + PKCE）。
2. Keycloak 回呼 `/api/auth/callback/keycloak`；Auth.js 以 JWT session 保存 `access_token`、`refresh_token`、`expires_at`、`roles`（從 ID token / access token 的 `realm_access.roles` 取）。
3. `src/proxy.ts` 對 `(app)` 路由檢查 session，未登入導向 `/login`。
4. Server Component / Server Action 透過 `@/lib/api`（`server-only`）呼叫 backend，自動帶 `Authorization: Bearer <access_token>`；access token 到期前 60 秒用 refresh token 向 Keycloak token endpoint 換新（Auth.js `jwt` callback）。
5. 瀏覽器端只有 SSE 需要直接連 backend：由 Route Handler `/api/stream/jobs/[id]` 代理（server 端帶 token），或 backend 接受短期 SSE ticket（`POST /jobs/{id}/events/ticket`）。v1 用代理。

### 2.2 backend 驗證
- `core/security.py`：PyJWT + `PyJWKClient`（JWKS 快取 1 小時），驗 `iss`、`aud`（或 `azp`）、`exp`。
- `get_current_user`：以 `sub` upsert `users`（同步 `email`、`preferred_username`、display name、`role` = realm role 含 `admin` ? admin : user、`last_login_at`）。
- `require_admin`、`require_project_role(min_role)`：以 `project_members` 判斷；admin 隱含所有專案的 owner 權限。

### 2.3 權限矩陣

| 動作 | admin | owner | maintainer | member | viewer |
|---|---|---|---|---|---|
| 審批申請、調配額、改系統角色 | ✓ | | | | |
| 封存專案、改專案設定 | ✓ | ✓ | | | |
| 管理成員 | ✓ | ✓ | ✓ | | |
| 建立 / 刪除資料集、建立 / 取消 job、設預設模型 | ✓ | ✓ | ✓ | ✓ | |
| 讀取專案、下載產物、看 log | ✓ | ✓ | ✓ | ✓ | ✓ |
| 討論區開單、回覆自己的單 | 所有登入者 | | | | |

## 3. 討論區與專案申請

- 討論區是全域的 issue 列表（`issues`），類型 `project_request | question | bug | feature`。
- `project_request` 單帶結構化 `request_payload`（data_type、task_type、資料量級、requested gpu / cpu / memory / storage、預計成員 email）。
- 狀態機：`open → in_review → approved | rejected`；`question / bug / feature`：`open → closed`。
- 核准（`POST /issues/{id}/approve`，admin）在一個交易內：建立 `projects`（slug、配額）、加 owner 與成員（已存在的 users 才加入；其餘留在 payload 待其登入後由 owner 邀請）、建立 MinIO prefix、issue 標 `approved` 並寫 system comment、寫 `audit_logs`。
- 退回需填理由（system comment）。申請人可編輯後重新送審（`rejected → open`）。

## 4. 資料集來源

| source_type | 使用者提供 | 儲存 | 生命週期 |
|---|---|---|---|
| `transient` | 瀏覽器上傳檔案（multipart，上限由 `MAX_UPLOAD_MB` 控制） | backend 串流寫入 MinIO `tmp/datasets/{dataset_id}/`，不落本機磁碟 | `expires_at = now + 24h`；job 結束（任何狀態）後 scheduler 刪除；清理任務每小時掃過期 |
| `minio` | endpoint、bucket、prefix、access key、secret key | 只存連線資訊；憑證 Fernet 加密到 `credentials_enc` | 跟專案 |
| `url` | http(s) URL、可選 headers（例如 token） | 只存 URL；headers 加密 | 跟專案 |

- `POST /projects/{slug}/datasets/{id}/validate` 由 backend 以使用者憑證做輕量檢查（列出前幾個物件 / HEAD 請求 / 讀 CSV 表頭）並回填 `spec`（欄位、列數估計、類別）。
- trainer 容器拿到的是解密後的連線資訊（環境變數，只存在容器內），用 `trainer/data/*` 的 loader 依 `format` 讀取；transient 以 scheduler 簽發的 presigned GET 讀取。
- 憑證永遠不回傳給前端，API 只回 `has_credentials: true`。

## 5. Train Job 生命週期

### 5.1 狀態機

```
queued ──(scheduler 選中並分配資源)──► scheduled ──(容器啟動)──► running ──► succeeded
   │                                        │                        ├──► failed
   └──(使用者取消)──► cancelled ◄───────────┴──(取消 / 逾時 docker stop)┘
```

- 建立：`POST /projects/{slug}/jobs` 驗證 dataset、catalog（family 與 task 相容）、資源請求 ≤ 專案配額 → 寫 row（`queued`）→ 202。
- 每次狀態變更：更新 `train_jobs`、`XADD job:{id}:events`、寫 `audit_logs`（取消 / 失敗）。
- 逾時：`config.timeout_minutes`（預設 240，上限由專案配額或 admin 設定）。

### 5.2 Scheduler 迴圈（每 3 秒）

```
1. reconcile：對所有 scheduled/running job 檢查容器狀態
   - 容器結束：exit 0 且 trainer 已回報 succeeded → succeeded；否則 failed（error_message 取容器 log 最後 50 行）
   - 超過 timeout → docker stop → failed(timeout)
   - 使用者要求取消 → docker stop → cancelled
   - 任何結束狀態：釋放 GPU 配置、刪除 transient dataset、歸檔 log 到 MinIO、更新 storage_used_bytes
2. capacity = 節點總資源（pynvml GPU 數與記憶體、psutil CPU / memory）− 執行中 job 的配置
3. 取候選：SELECT ... FROM train_jobs WHERE status='queued' ORDER BY priority DESC, created_at ASC FOR UPDATE SKIP LOCKED LIMIT 20
4. 對每個候選：
   - 專案層檢查：running_jobs < max_concurrent_jobs；running_gpu + requested_gpu ≤ gpu_limit（cpu / memory 同）；storage_used < storage_quota
   - 節點層檢查：requested 資源 ≤ capacity
   - 通過 → 選 GPU（記憶體最空的 index 優先）→ 建立 per-job token → docker run → 狀態 scheduled → running
   - 同一 tick 每個專案最多啟動一個 job（公平性）
```

- Docker 參數：`image=qr-ai-lab/trainer:<tag>`、`device_requests=[DeviceRequest(device_ids=[...], capabilities=[["gpu"]])]`（GPU=0 時不掛）、`nano_cpus=int(cpu*1e9)`、`mem_limit=f"{memory_mb}m"`、`memswap_limit` 同值（禁 swap）、`network=qr-ai-lab_internal`、`labels={"qr-ai-lab.job_id": id}`、`environment={JOB_ID, JOB_TOKEN, BACKEND_URL, DATASET_*, CUDA_VISIBLE_DEVICES, TORCH_*}`。
- scheduler 單一實例（compose 只起一個）；以 Redis `SET scheduler:lock NX EX 10` 心跳保證不重複。
- scheduler 重啟後靠 reconcile 由容器 label 找回執行中的 job。

### 5.3 Trainer 容器協定

| 步驟 | 介面 |
|---|---|
| 取 spec | `GET /internal/jobs/{id}/spec` → data_type、task_type、mode、family、config、dataset 連線、資源限制 |
| 回報狀態 / 進度 | `POST /internal/jobs/{id}/status` `{status, progress, stage, message}` |
| 回報 metrics | `POST /internal/jobs/{id}/metrics` `{epoch?, trial?, metrics{}}`（AutoML 每 trial 一筆，寫入 leaderboard） |
| log | stdout / stderr → scheduler 用 `container.logs(stream=True)` 轉寫 Redis `job:{id}:events`（type=log）；不要求 trainer 自己送 |
| 上傳產物 | `POST /internal/jobs/{id}/artifacts` `{name, kind, size_bytes, metadata}` → 回 presigned PUT；上傳後 `POST .../artifacts/{aid}/complete` → backend `stat_object` 核對大小、更新配額 |
| 結束 | exit 0 = 成功（已先回報 succeeded）；非 0 = 失敗 |

per-job token：HS256，payload `{sub: job_id, kind: "train" | "infer", exp: now + timeout}`，`/internal/*` 驗證 token 的 `sub` 等於路徑 id。

## 6. AutoML（`mode = auto`）

1. backend 依 `(data_type, task_type, dataset.spec.row_count / image_count)` 從 `model_catalog.yaml` 選候選 family（見 `docs/MODEL_CATALOG.md` §5），寫入 `config.search = {candidates, max_trials, time_budget_minutes, metric, direction}`。
2. trainer 建一個 Optuna study：trial 先抽 family（categorical）再抽該 family 的搜尋空間；`MedianPruner`；超過時間或 trial 數即停。
3. 每個 trial 結束回報 `{trial, family, params, metrics, duration_s}`；backend 累積到 `train_jobs.metrics.leaderboard`。
4. 結束時以最佳 trial 的參數用完整訓練集重訓一次，匯出為 artifact（`metadata.automl = {best_trial, params}`）並建議設為預設模型。
5. 單容器循序執行，資源配置與手動 job 相同；候選含 GPU 家族時 job 必須申請 GPU。

## 7. 推論

- v1：批次推論。`POST /projects/{slug}/inference` 建立 `inference_jobs`（`queued`），scheduler 以 `mode=infer` 啟動同一個 trainer image（`trainer infer --job-id`），載入 artifact，讀輸入（inline JSON、transient 上傳、MinIO、URL），輸出：小結果（≤ 1 MB）寫 `result` JSON，大結果上傳 `inference/{slug}/{job_id}/output.*` 並回 presigned 下載。
- 推論 job 預設 GPU=0、CPU 1、Memory 2 GB；vision / text 家族可申請 GPU。
- v2 候選：常駐推論服務（模型暖載、同步 API）。先不做。

## 8. 儲存配置（MinIO）

```
qr-ai-lab/
├─ projects/{slug}/jobs/{job_id}/model/…        kind=model / weights
├─ projects/{slug}/jobs/{job_id}/preprocessor/…
├─ projects/{slug}/jobs/{job_id}/report/…       混淆矩陣、曲線圖、leaderboard.json
├─ projects/{slug}/jobs/{job_id}/logs/train.log  job 結束後由 scheduler 歸檔
├─ inference/{slug}/{inference_job_id}/…
└─ tmp/datasets/{dataset_id}/…                   lifecycle rule：1 天過期
```

- 配額：`projects.storage_used_bytes` 只在 backend `complete` 與刪除產物時更新；scheduler 啟動 job 前檢查 `used < quota`，trainer 上傳前 backend 再檢查 `used + size_bytes ≤ quota`，超過回 `STORAGE_QUOTA_EXCEEDED`。
- 刪除 artifact：刪 MinIO 物件 → 刪 row → 扣用量；有 inference_jobs 引用時（RESTRICT）需先刪推論紀錄。
- MinIO 根憑證只有 backend 與 scheduler 持有；trainer 只拿 presigned URL；使用者自帶 MinIO 的憑證只在 trainer 容器環境變數出現。

## 9. 即時事件

- Redis stream `job:{id}:events`（`MAXLEN ~ 10000`）：`{type: status | progress | metric | log, ts, data}`。
- `GET /api/v1/jobs/{id}/events`（SSE，`text/event-stream`）：先送最近 200 筆，再 `XREAD BLOCK`；支援 `Last-Event-ID` = stream id 續傳；job 結束後送 `event: end` 關閉。
- 前端 `LogViewer` / job 詳情頁訂閱；列表頁用 TanStack Query 每 10 秒 refetch，不開 SSE。
- 推論 job 同樣機制（`inference:{id}:events`）。

## 10. API 清單（v1，前綴 `/api/v1`）

```
GET    /me                                   目前使用者（含 role、所屬專案摘要）
GET    /users                                admin；分頁、搜尋
PATCH  /users/{id}                           admin；role、is_active
GET    /catalog                              data types、tasks、families、搜尋空間、SOP 章節
GET    /issues  POST /issues                 列表（type、status、mine、q）/ 開單
GET    /issues/{id}  PATCH /issues/{id}      詳情 / 作者或 admin 編輯
POST   /issues/{id}/comments
POST   /issues/{id}/approve                  admin；body: slug、quota、members → 建立專案
POST   /issues/{id}/reject                   admin；body: reason
POST   /issues/{id}/close
GET    /projects  GET /projects/{slug}  PATCH /projects/{slug}  POST /projects/{slug}/archive
PATCH  /projects/{slug}/quota                admin
GET    /projects/{slug}/members  POST …  PATCH …/{user_id}  DELETE …/{user_id}
GET    /projects/{slug}/datasets  POST …  DELETE …/{id}
POST   /projects/{slug}/datasets/upload      multipart → transient
POST   /projects/{slug}/datasets/{id}/validate
GET    /projects/{slug}/jobs  POST …          建立訓練（202）
GET    /jobs/{id}  POST /jobs/{id}/cancel  GET /jobs/{id}/events(SSE)  GET /jobs/{id}/logs(歸檔)
GET    /projects/{slug}/artifacts  PATCH /artifacts/{id}(is_default)  GET /artifacts/{id}/download  DELETE /artifacts/{id}
GET    /projects/{slug}/inference  POST …     建立推論（202）
GET    /inference/{id}  GET /inference/{id}/events  GET /inference/{id}/download
GET    /admin/overview                        待審數、執行中數、節點摘要
GET    /admin/node                            每張 GPU 使用率 / 記憶體、CPU、memory、disk
GET    /admin/queue  PATCH /admin/jobs/{id}   priority、cancel
GET    /admin/audit
GET    /internal/jobs/{id}/spec  POST …/status  POST …/metrics  POST …/artifacts  POST …/artifacts/{aid}/complete
GET    /healthz  GET /readyz
```

## 11. 部署（公司 Ubuntu GPU 伺服器）

- 前置：Ubuntu 22.04 / 24.04、NVIDIA driver、Docker Engine + Compose plugin、NVIDIA Container Toolkit（`nvidia-ctk runtime configure`）。
- `infra/docker-compose.yml` services：`nginx`、`frontend`、`backend`、`scheduler`（掛 `/var/run/docker.sock`，只有它需要）、`mariadb`（volume）、`redis`、`minio`（volume）。trainer image 以 `docker build -f infra/trainer/Dockerfile trainer` 單獨建置並打 tag，scheduler 用 `TRAINER_IMAGE` 指定。
- 網路：`qr-ai-lab_internal`（bridge）；只有 nginx 對外。Keycloak 在外部，以 `KEYCLOAK_ISSUER` 指向。
- 環境變數（`infra/.env.example`）：
  - 共用：`APP_ENV`、`PUBLIC_URL`
  - frontend：`AUTH_SECRET`、`AUTH_KEYCLOAK_ID`、`AUTH_KEYCLOAK_SECRET`、`AUTH_KEYCLOAK_ISSUER`、`BACKEND_URL`
  - backend / scheduler：`DATABASE_URL`（`mariadb+asyncmy://…`）、`REDIS_URL`、`MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MINIO_BUCKET`、`KEYCLOAK_ISSUER`、`KEYCLOAK_AUDIENCE`、`DATASET_SECRET_KEY`（Fernet）、`JOB_TOKEN_SECRET`、`TRAINER_IMAGE`、`NODE_GPU_RESERVE`、`MAX_UPLOAD_MB`
- 備份：MariaDB 每日 `mariadb-dump` 到 MinIO `backups/`；MinIO volume 由主機備份。
- 日誌：所有服務 stdout JSON；主機以 `docker compose logs` 或 Loki（未來）。
- 更新流程：`git pull` → `docker compose build frontend backend scheduler` → `docker compose run --rm backend uv run alembic upgrade head` → `docker compose up -d`。

## 12. 安全性注意事項

- scheduler 持有 docker socket 等同主機 root：只跑受信任的 trainer image，容器以非 root 使用者執行、`--cap-drop ALL`、`no-new-privileges`、唯讀 rootfs + tmpfs。
- 使用者資料集憑證：加密儲存、不入 log、不回前端；trainer 容器網路可外連（要讀使用者的 MinIO / URL），但不能連 MariaDB / Redis（compose 網路分段：trainer 只在 `qr-ai-lab_jobs` 網路，透過 nginx 內部 host 打 backend）。
- 所有狀態變更寫 `audit_logs`；admin 操作需在 UI 二次確認。
- 上傳限制：大小（`MAX_UPLOAD_MB`）、副檔名白名單、CSV 以串流解析避免記憶體爆掉。
- 速率限制：登入後的 API 以 user 為鍵（slowapi），`/internal/*` 以 job 為鍵。

## 13. v1 範圍與未來

- v1：單節點、批次推論、AutoML 單容器循序、SSE 代理、繁體中文 UI。
- 未來候選：多節點（改用 Ray 或 K8s Jobs）、常駐推論服務、實驗比較頁、資料集版本、通知（email / Teams）、i18n。
