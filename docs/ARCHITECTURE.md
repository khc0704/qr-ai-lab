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
        MariaDB :3307   Redis :6380   DATA_ROOT/      scheduler（python -m app.scheduler）  systemd: qrlab-scheduler
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
| Keycloak | 內網既有 | 身分與密碼（只提供身分；系統角色與專案成員都在本服務的資料表） |

單機部署；v1 不做多節點、不做 Kubernetes、不架自己的物件儲存。**Job 不跑在容器裡**：所有任務都是同一個主機 venv 的子程序，資源限制交給 cgroups（systemd）或排程器的 watchdog；Docker 只用來跑 MariaDB 與 Redis。伺服器不連外網：套件來自公司的 PyPI / npm / image 鏡像，預訓練權重由管理員經「模型庫」頁帶進來。

## 2. 認證與授權

### 2.0 兩種模式（`AUTH_MODE`，前後端要一致）
- **local（開發 / 過渡期）**：backend `POST /api/v1/auth/login {username, password}` 驗 `users.password_hash`（argon2），回 HS256 access token（`AUTH_SECRET`，預設 12 小時）。前端 Server Action `loginAction` 把 token 放在 httpOnly cookie `qr_token`。dev / test 啟動自動建立三個帳號：`superadmin / $SEED_SUPERADMIN_PASSWORD`（預設 `superadmin1234`）、`admin / $SEED_ADMIN_PASSWORD`（`admin1234`）、`user / $SEED_USER_PASSWORD`（`user1234`）；正式環境用 `.venv/bin/python -m app.cli seed | create-user | set-password | set-role`。
- **keycloak（正式）**：前端用 Auth.js（next-auth v5，`frontend/src/auth.ts`）的 Keycloak provider 登入，backend 只驗 Keycloak 發的 access token。`POST /auth/login` 回 401 `LOCAL_LOGIN_DISABLED`；`GET /auth/config` 告訴前端目前模式。
- **token 更新（keycloak）**：只有 `src/proxy.ts`（Auth.js 的 middleware 形式）會用 refresh token 換新 access token 並把輪替後的 session cookie 寫回瀏覽器；它把目前的 access token 放進 `x-qr-access-token` request header，RSC / Server Action / Route Handler 的 `getToken()` 只讀 header 或解開 cookie，絕不自行刷新（RSC 寫不了 cookie）。同一次頁面載入的多個請求帶著同一個 cookie 時，刷新會以 refresh token 為鍵去重並快取一分鐘，所以 Keycloak 開啟「Revoke Refresh Token」（單次使用）也不會把使用者登出。
- **上傳不經 proxy**：三個 multipart 上傳 Route Handler（`/api/upload/[slug]`、`/api/tools/upload`、`/api/admin/model-zoo/[id]/upload`）刻意不在 `src/proxy.ts` 的 matcher 裡：Next.js 會把經過 proxy 的請求 body 緩衝起來給 proxy 讀，上限 `experimental.proxyClientMaxBodySize`（10 MB），超過就靜默截斷。不經 proxy 的 body 直接串流進 Route Handler；`getToken()` 退而解開 session cookie（不刷新），token 已過期時回 401 `SESSION_EXPIRED` 請使用者重新整理頁面（proxy 會在那時刷新）。
- 兩種模式下 `GET /api/v1/me` 都回使用者 + `permissions`（後端算好的權限名稱清單）+ `auth_mode`；所有讀取走 `src/lib/api`（`server-only` fetch，`getToken()` 依模式從 cookie 或 Auth.js session 取 token），寫入走 `src/lib/actions.ts`；瀏覽器需要直接串流 / 傳檔的事由 Route Handler 代理（`/api/upload/[slug]`、`/api/stream/jobs/[id]`、`/api/download/[...path]`、`/api/admin/model-zoo/[id]/upload`、`/api/tools/upload`；工具任務的結果走 `/api/download/jobs/[id]/download`），token 不出伺服器。

### 2.1 Keycloak 登入流程（已實作）
1. `/login` 的「使用公司帳號登入」按鈕在瀏覽器端呼叫 Auth.js `signIn("keycloak")`（`next-auth/react`：取 csrf → `POST /api/auth/signin/keycloak`）→ 以 Authorization Code + PKCE + state 導到 realm 的登入頁（`AUTH_KEYCLOAK_ISSUER` 的 `.well-known/openid-configuration`）；PKCE / state cookie 因此和回呼在同一個 origin。
2. 回呼 `${AUTH_URL}/api/auth/callback/keycloak`（Route Handler `src/app/api/auth/[...nextauth]/route.ts`；local 模式時回 404）。Auth.js 驗 id_token（JWKS）後在 **加密的 session cookie（jwt strategy）** 內保存 `access_token`、`refresh_token`、`id_token`、`expires_at`；`AUTH_SESSION_MAX_AGE` 決定 cookie 壽命（預設 12 小時）。
3. `src/proxy.ts` 只看 cookie 有無（`qr_token` 或 `authjs.session-token*`）：未登入導向 `/login?next=`；帶 `?reason=` / `?error=` 的 `/login` 不會被彈回首頁（避免 session 失效時的迴圈）。
4. 每次 Server Component / Server Action 呼叫 backend 前 `getToken()` 執行 `auth()`：access token 到期前 30 秒用 refresh token 向 `<issuer>/protocol/openid-connect/token` 換新（`jwt` callback）；換不到就標 `error=RefreshTokenError` → `getOptionalUser` 回 null → 導向 `/login?reason=expired`。
5. 登出：`logoutAction` 先 `signOut`（清 cookie），再把瀏覽器導到 `<issuer>/protocol/openid-connect/logout?id_token_hint=…&post_logout_redirect_uri=$AUTH_URL/login` 結束 SSO。
6. Keycloak client 需要：confidential client、Standard flow、Valid redirect URI `$AUTH_URL/api/auth/callback/keycloak`、Valid post logout redirect URI `$AUTH_URL/login`；role 用 realm role 或 client role 都可（見 2.2）。所有值放在 `/etc/qr-ai-lab/frontend.env`（前端）與 `/etc/qr-ai-lab/qrlab.env`（backend），不進 git。

### 2.2 backend 驗證與角色對應
- `core/security.py`：PyJWT + `PyJWKClient`（`<KEYCLOAK_ISSUER>/protocol/openid-connect/certs`，快取 1 小時），驗簽章、`iss`、`exp`；`KEYCLOAK_AUDIENCE` 有設才驗 `aud`（Keycloak 要加 audience mapper）。
- `services/users.upsert_keycloak_user`：以 `sub` 找 `users`；找不到時若有同名（`preferred_username`）的本地帳號就接管它（`auth_provider=keycloak`、清掉密碼），否則新建。每次登入同步 email / display name / `last_login_at`。
- 系統角色：**Keycloak 只提供身分**（`sub`、`preferred_username`、email、姓名），不決定角色。`users.role` 只在 `/admin/users`（`users.manage`）設定，第一次登入一律是 `user`。superadmin **只有一位**，由 `SUPERADMIN_USERNAME`（本地帳號名稱 / Keycloak `preferred_username`）指定：該帳號登入或服務啟動（`services/users.ensure_single_superadmin`）時即為 superadmin，其他任何仍帶 superadmin 的列會被降為 admin；UI / CLI 最多只能指派到 admin（`PATCH /users/{id}` 給 `superadmin` 回 400 `SUPERADMIN_FIXED`，該帳號也不能被降級或停用）。`KEYCLOAK_ROLE_MAP` 預設空（不覆蓋），留作未來的 opt-in：設了 `<keycloak role>:<系統角色>` 才會以 token 的 realm role / `resource_access[KEYCLOAK_CLIENT_ID].roles` 覆蓋 `users.role`（最多對應到 admin；沒帶對應 role 時維持 UI 設定）。
- `require_admin`（admin 以上）、`require_perm("<perm>")`（見 2.3）、`project_access(min_role)`：以 `project_members` 判斷；admin 以上隱含所有專案的 owner 權限（可看、可管成員），但配額 / 刪除仍看系統權限。

### 2.3 權限矩陣（`backend/app/core/permissions.py`；前端 `can(user, perm)` 只負責隱藏 UI）

| 權限名稱 | superadmin | admin | user | 說明 |
|---|---|---|---|---|
| `admin.view`、`audit.view`、`usage.view`、`users.view` | ✓ | ✓ | | 進管理區：Dashboard、佇列、稽核、使用率歷史、使用者列表（唯讀） |
| `requests.review` | ✓ | ✓ | | 開始審核 / 核准 / 退回專案申請 |
| `jobs.control` | ✓ | ✓ | | 強制中斷、重新執行、刪除任何任務、重排佇列 |
| `issues.moderate` | ✓ | ✓ | | 關閉 / 重開 / 指派 / 刪除討論串 |
| `pool.manage` | ✓ | | | 總資源池、Job 預設值（admin 看到的是唯讀表單） |
| `quota.manage` | ✓ | | | 專案配額 |
| `projects.delete` | ✓ | | | 刪除專案（任務、產物、資料來源、資料夾） |
| `users.manage` | ✓ | | | 改系統角色（最多到 admin）、停用帳號（superadmin 只有一位，由 `SUPERADMIN_USERNAME` 固定：不能指派、降級或停用） |
| `model_zoo.manage` | ✓ | | | 上傳 / 匯入 / 移除預訓練權重 |
| `gpu.reset` | ✓ | | | 強制釋放 GPU 顯存 |

專案內角色不變：

| 動作 | admin 以上 | owner | maintainer | member | viewer |
|---|---|---|---|---|---|
| 封存專案、改專案設定 | ✓ | ✓ | | | |
| 管理成員 | ✓ | ✓ | ✓ | | |
| 新增 / 刪除資料來源、建立 / 取消本專案的 Job、設預設模型 | ✓ | ✓ | ✓ | ✓ | |
| 讀取專案、下載產物、看本專案 Job 的 log | ✓ | ✓ | ✓ | ✓ | ✓ |
| 提出專案申請、在討論區開單與回覆、使用資料前處理服務 | 所有登入者 | | | | |

## 3. 討論區

- 全域、獨立於專案申請的問題單區：`issues.type = question | bug | feature`，`status = open | closed`。
- 任何登入者可開單、在自己或他人的單下留言；admin 可回覆、指派、關閉（需填 `resolution_note`）、重開。
- 可選擇關聯既有專案（`project_id`），方便針對某專案提問。
- 留言存在多型 `comments` 表（`target_type = issue`）；狀態變更以 `kind = system` 的留言呈現在時間軸。

## 4. 專案申請與審批

- 申請與專案是同一件事：`POST /projects` 送出申請時就建立 `projects` 列（`status = pending`，slug 由建議值或題目產生並確保唯一，申請人成為 owner），申請內容（目的、資料量級、資料描述、需求 GPU / CPU / Memory / Storage、預計成員 email）放在 `project_requests` 表並以 `projects.request_id` 連結，專案頁以「申請」分頁顯示。核准前只有這個分頁；核准後其他分頁才開放，申請分頁留作紀錄。
- 專案狀態機：`pending → in_review → active`（核准）或 `rejected`（退回；申請人修改 `PATCH /projects/{slug}/application` 後回到 `pending`）；`pending | in_review | rejected` 可 `POST …/withdraw`（刪除這個專案）；`active → completed`（結束：不再接受新任務，產物與 log 保留，owner / admin 可 `reopen`）；`active | completed → archived`。`project_requests.status` 只是歷史鏡像。
- 審核過程的往返用 `comments`（`target_type = project_request`，`GET/POST /projects/{slug}/application/comments`）；admin 要求補件時留言並維持 `in_review`。
- 核准（`POST /projects/{slug}/approve`，`requests.review`）在一個交易內：設定配額（可修改申請值）與名稱、加入申請列出且已登入過的成員（其餘待 owner 之後邀請）、建立 `DATA_ROOT/projects/{slug}/`、`status = active`、寫 system comment 與 `audit_logs`。退回需填 `review_note`。
- 只有 `active` 的專案能建資料來源、上傳、建立任務、管成員（`project_access(..., active=True)` → 409 `PROJECT_NOT_ACTIVE`）；`pending` 的專案對非成員回 404。管理員在專案「設定」分頁調整配額（`PATCH /projects/{slug}/quota`，`quota.manage`）；沒有獨立的審核頁或配額頁，待審清單就是 `GET /projects?status=pending`。

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
- 前處理：`input.spec.preprocess` 的步驟由共用套件 `libs/preprocess`（`qrlab_preprocess`）定義；backend 用它做上傳抽樣預覽與驗證，trainer 在訓練時 fit 並把狀態存成 `model/preprocess.json` + 產物 metadata，推論時 replay。步驟執行中可用 `ctx.warn()` 留下使用者看得懂的警告（例如「文字數字轉成數值」把類別欄整欄變成缺值）；`Pipeline` 以 `step_warnings` / `report()` 逐步驟保存，預覽回傳 `step_details` 與 `warnings`，整檔前處理寫進 `summary.json`。類別欄的編碼是 `tabular.encode`（label / onehot / ordinal，類別清單為 fitted state）。

### 6.5 GPU 配置（依實測剩餘顯存共用）
- 任務可填 `requested_gpu_memory_mb`（精靈「每張 GPU 需要的顯存」，預設 8192）。排程器每個 tick 以 pynvml 讀每張資源池 GPU **實際已用的顯存**（所有程序），再用驅動程式的程序清單把顯存對應到本系統每個任務的程序樹（`services/gpu.measured_by_job`）。可用量 = `total − 實測已用 − 尚未分配 − GPU_RESERVE_MB`；「尚未分配」只計入啟動不到 `GPU_WARMUP_S`（預設 120 秒）且實測還沒達到申請量的任務（申請量 − 實測），避免兩個連續啟動的任務都看到「還很空」而擠在同一張卡；暖機期過後完全以實測為準。符合的卡用 best-fit（剩最少的先用）讓任務集中；沒填的任務要整張空卡（沒有任何任務、已用顯存 < `GPU_BUSY_THRESHOLD`）。資源池的 `gpu_share=false` 關閉共用，一律獨占。沒有 NVIDIA driver 時退化成按張數（共用任務平均分散）。
- Dashboard 的 GPU 卡片顯示驅動程式實測、每個任務「實測 / 申請」；使用率歷史每筆取樣記下各專案實測顯存（`gpu_mem_actual_mb`）。
- 保留規則：在驅動程式看見任務的程序（CUDA context）之前，整個申請量都算「尚未分配」（抓資料、解壓、前處理可能遠超暖機期）；之後 `GPU_WARMUP_S` 內保留「申請 − 實測」，再之後只看實測。沒有 pynvml 時退化為以申請量計數。佇列頭的 GPU 任務等超過 10 分鐘時，不再讓後面的 GPU 任務 backfill 插隊（避免多 GPU 任務永遠排不到）。
- 子程序拿到 `JOB_GPU_MEMORY_MB`，trainer `limits.py` 以 `torch.cuda.set_per_process_memory_fraction` 自限；Dashboard 的 GPU 卡片顯示驅動程式讀數、保留量、放在上面的任務與程序數。
- `POST /admin/gpus/{index}/reset`（superadmin）：`jobs` 強制中斷本系統放在那張卡的任務；`all` 再 SIGKILL 驅動程式看到的所有程序；`device` 再執行 `GPU_RESET_COMMAND`（如 `sudo -n nvidia-smi --gpu-reset -i {index}`）。都寫稽核紀錄。

### 6.6 資源限制如何真的生效
- 外層：systemd scope（`AllowedCPUs` / `CPUQuota` / `MemoryMax`）或 `sched_setaffinity` + 記憶體 watchdog。
- 子程序環境：`OMP / MKL / OPENBLAS / BLIS / VECLIB / NUMEXPR / TBB / NUMBA / RAYON / POLARS / LOKY_MAX_CPU_COUNT / TORCH_NUM_THREADS` 全部 = ceil(cpu)，`JOB_CPU_LIMIT`、`JOB_CPU_CORES`、`JOB_MEMORY_MB`、`JOB_GPU_MEMORY_MB`。
- 程序內：`trainer/limits.py` 在讀完 spec 後 `threadpoolctl.threadpool_limits(cpu)`（已載入的 BLAS / OpenMP）、`torch.set_num_threads(cpu)`、`set_num_interop_threads(1)`，並把實際 affinity、各執行緒池大小、torch threads 印進 job log（`limits: cpu=1 affinity=1 cores [3] threadpools[openmp/openmp=1, blas/openblas=1] torch_threads=1`）。sklearn 的 `n_jobs` 一律取 `ctx.cpu`。

### 6.6b 工具任務（kind = preprocess | analysis）
- 「資料前處理」與「資料分析」服務不需要專案，但重活一律是任務：所有人的工具任務都在同一個 **工具池**（系統專案 `projects.kind = shared`，slug `tools`，第一次使用時自動建立，沒有成員，不出現在專案列表）排隊執行，配額來自管理員 Dashboard 的「工具池」設定（`system_settings.tool_pool`，儲存時同步到該專案的配額欄位），`max_jobs_per_user` 限制每人同時排隊 + 執行中的工具任務數（超過 → 409 `TOOL_JOB_LIMIT`）。工具任務只有建立者與管理員看得到（`/tools/jobs`、`/tools/jobs/{id}` 頁），不用專案的任務頁。舊版每人一個的個人工作區（`kind = personal`）由 migration 0007 封存。工具上傳（`DATA_ROOT/tools/<id>/`，無資料庫列）在建立任務時移進任務的 input（任務結束即刪）。
- `preprocess`：trainer 以 `qrlab_preprocess.process.run_full` 處理整個檔案，輸出 `output/preprocessed.zip`（processed.* + pipeline.json + summary.json）；`GET /jobs/{id}/download` 交付一次後刪除檔案並在 `result.downloaded_at` 記錄，沒下載的在「工具預設」的 `result_ttl_hours` 後由排程器清理。抽樣預覽（`POST /tools/uploads/{id}/preview`）仍是即時的，只讀取有限樣本。
- `analysis`：`config.analysis = tabular_profile | image_quality`（`trainer/analysis/`）。表格：欄位概況、Pearson 相關矩陣與高相關對、VIF、對目標的互資訊 / 相關性 / 隨機森林置換重要度與保留集分數、疑似洩漏、建議（補值、共線、離群、模型家族）。影像品質：以 zip 子資料夾為群組，每張影像 17 個 IQA 指標、各群組中位數 / IQR、每個指標的飄移比（群組中位數差 ÷ 群內 IQR）與 Kruskal–Wallis p 值、embedding（IQA 指標向量，或模型庫有 dinov2 且工作區有 GPU 時用 DINOv2）的 PCA 散佈、群組 centroid cosine 相似度、silhouette、偏離群組的影像、建議。報告寫到 `output/report.json` 並登記為 report 產物；`job.result` 放精簡版供任務頁繪圖。

### 6.7 使用率歷史
排程器每 `USAGE_SAMPLE_INTERVAL_S` 秒寫一筆 `resource_samples`：節點（CPU%、記憶體、每張 GPU 的使用率與顯存）、資源池（已配置的 GPU / CPU / 記憶體、執行中任務數、池總量）、各專案（配置量，以及用 psutil 量到任務程序樹的實際 CPU 核數與 PSS 記憶體）。`GET /admin/usage?range=` 分桶平均並算各專案的時間加權占用；保留 `USAGE_RETENTION_DAYS`。

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
GET    /users/lookup?q=                      所有登入者；挑選器自動完成（id、username、display_name、email；≥ 2 字、最多 10 筆）
GET    /catalog                              data types、tasks、families、搜尋空間、SOP 章節
GET    /issues  POST /issues                 討論區列表（type、status、mine、q）/ 開單
GET    /issues/{id}  PATCH /issues/{id}      詳情 / 作者或 admin 編輯
POST   /issues/{id}/comments  POST /issues/{id}/close  POST /issues/{id}/reopen
PATCH  /issues/{id}/comments/{comment_id}     作者或 admin 編輯留言（系統事件不可編輯；內文為 Markdown）
GET    /projects?status=&q=  POST /projects       我有權限的專案含申請中（admin：全部；status 逗號分隔，pending = pending,in_review）/ 送出申請（建立 pending 專案）
PATCH  /projects/{slug}/application          申請人修改（pending / rejected；rejected → pending）
GET    /projects/{slug}/application/comments  POST …/comments   審核往返
POST   /projects/{slug}/withdraw             申請人撤回（刪除 pending 專案）
POST   /projects/{slug}/review               requests.review；status → in_review
POST   /projects/{slug}/approve              requests.review；body: name?、quota、members?、review_note? → active
POST   /projects/{slug}/reject               requests.review；body: review_note
POST   /projects/{slug}/complete  POST …/reopen   owner / admin：結束 ↔ 重新開啟
GET    /projects/{slug}  PATCH /projects/{slug}  POST /projects/{slug}/archive  POST …/unarchive（owner；工具池不能封存）
PATCH  /projects/{slug}/quota                quota.manage（專案「設定」分頁）
POST   /projects/{slug}/members  PATCH …/{user_id}  DELETE …/{user_id}   （成員列表包含在 GET /projects/{slug}）
GET    /projects/{slug}/data-sources  POST …  PATCH …/{id}  DELETE …/{id}  POST …/{id}/check
POST   /projects/{slug}/uploads              multipart → upload_id + spec（一次性）
GET    /projects/{slug}/jobs  POST …          建立訓練或推論 Job（202）
GET    /jobs                                  最近任務（我參與的專案；admin：全部）
GET    /capacity                              總資源池 + 已配置量（任何登入者；給精靈與首頁）
POST   /projects/{slug}/uploads/{id}/preview  前處理抽樣預覽（steps、sample、spec）→ steps / before / after + step_details（每步驟 warnings）+ warnings；TABULAR / TEXT 另有 rows_in / rows_out、columns_in / columns_out（每欄 dtype、missing、unique、min / max / mean、top）；GET /catalog/preprocess?data_type=
GET    /jobs/{id}  POST /jobs/{id}/cancel     成員取消
GET    /jobs/{id}/events(SSE；`Last-Event-ID` 續讀)  GET /jobs/{id}/logs（回 `last_event_id`）  GET /jobs/{id}/logs/download  GET /jobs/{id}/download  GET /jobs/{id}/artifacts
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

### 12.1 這一輪新增的端點
- `GET /auth/config`（不需登入）、`GET /me`（含 `permissions`、`auth_mode`）
- `DELETE /projects/{slug}`（superadmin）、`DELETE /issues/{id}`（admin 以上）、`POST /admin/jobs/{id}/restart`（admin 以上，回 202 新任務）
- `PATCH /users/{id}`（superadmin；role `admin|user`、`is_active`；superadmin 本身由 `SUPERADMIN_USERNAME` 固定）
- `GET /users/lookup?q=`（所有登入者；≥ 2 字、不分大小寫比對帳號 / 顯示名稱 / email、只回啟用中帳號的 `id / username / display_name / email`、最多 10 筆，依 username 排序）；`POST /projects/{slug}/members` 接受 `user_id`（前端 `UserPicker` 自動完成）或原本的 `username_or_email`
- `POST /admin/gpus/{index}/reset`（superadmin）、`GET /admin/usage?range=1h|6h|24h|7d|30d`（admin 以上）
- `POST /tools/uploads`、`GET /tools/uploads/{id}`、`POST /tools/uploads/{id}/preview`（即時）、`POST /tools/uploads/{id}/process`（→ 202 preprocess 任務）、`POST /tools/uploads/{id}/analyze`（→ 202 analysis 任務）、`DELETE /tools/uploads/{id}`、`GET /tools/pool`（工具池配額與我目前的任務數）、`GET /tools/jobs`（只回自己的；所有登入者）；`GET/PUT /admin/settings/tool-pool`（superadmin；含 `max_jobs_per_user`）；`GET /jobs/{id}/download` 對前處理結果交付一次即刪
- 資源池多了 `gpu_share`；Job 多了 `requested_gpu_memory_mb`；`/admin/node` 的 GPU 多了 `job_ids`、`reserved_mb`、`processes`

## 13. 部署（公司 Ubuntu GPU 伺服器，不連外網）

- 前置：Ubuntu 22.04 / 24.04、NVIDIA driver（只要 driver；CUDA 函式庫隨 torch wheel 來）、Docker Engine + Compose plugin（只跑 MariaDB / Redis）、Python 3.12 + `python3.12-venv`（pip 從 `requirements.txt` 安裝，走 `/etc/pip.conf` 的公司 PyPI proxy；全專案不用 uv）、系統層級的 Node ≥ 20.9、nginx。套件來源：公司的 PyPI 鏡像（`UV_INDEX_URL` / `PIP_INDEX_URL`）、npm 鏡像（`npm config set registry`）、image 鏡像（`infra/.env` 的 `DOCKER_REGISTRY`）。
- 程式放 `/opt/qr-ai-lab`（git checkout），資料放 `/srv/qr-ai-lab/data`（`DATA_ROOT`，含 `model_zoo/`），權重傳輸資料夾 `/srv/qr-ai-lab/transfer`（`MODEL_ZOO_IMPORT_ROOT`）。專用使用者 `qrlab`，`loginctl enable-linger qrlab`（任務的 systemd scope 跑在它的 user slice）。
- 安裝分四步：`infra/install-00-base.sh`（使用者、資料夾、env 範本）→ `install-01-docker.sh`（MariaDB 3307 / Redis 6380）→ `install-02-backend.sh`（兩個 venv、migration、backend + scheduler 服務）→ `install-03-frontend.sh`（`next build` 含 `NEXT_PUBLIC_BASE_PATH`、frontend 服務）；`--update` 各自重跑。
- nginx：網站在 `https://qrit.tsmc.com/ai-lab`（Next.js `basePath`），API 在 `https://qrit.tsmc.com/ai-lab-api`（nginx 去掉前綴，backend 以 `ROOT_PATH` 回報）；`infra/nginx/qr-ai-lab.conf` 是要貼進現有 server 區塊的 location 範本（上傳路徑 20 GB、SSE 不 buffering、登入限速、`large_client_header_buffers`），`snippets/qr-ai-lab-proxy.conf` 是共用的 `X-Forwarded-*` header。
- 任務執行：`JOB_RUNNER=auto`（systemd cgroup；Dashboard 會顯示實際偵測結果）。沒有任何容器，也不需要 NVIDIA Container Toolkit。
- 模型庫：管理員在 `/admin/model-zoo` 用三種方式之一把權重帶進來：瀏覽器上傳、伺服器路徑（`MODEL_ZOO_IMPORT_ROOT`）、內網 URL（`MODEL_ZOO_ALLOWED_HOSTS`）。有網路的機器可先用 `scripts/fetch_model_zoo.py` 抓好再整個資料夾放到傳輸資料夾。
- 更新流程：`git pull` → `sudo ./infra/install-02-backend.sh --update` + `sudo ./infra/install-03-frontend.sh --update`（各自停服務、重建、migration、再啟動；執行中的任務不受排程器重啟影響）。
- 磁碟：`DATA_ROOT` 放在大容量磁碟；admin Dashboard 顯示剩餘空間（目前只顯示，沒有自動停排）。

## 14. 安全性注意事項

- 任務是 `qrlab` 使用者的主機子程序（沒有容器、沒有 docker socket）：trainer venv 只裝公司 proxy 的套件；子程序的環境變數是白名單（`runner.ENV_PASSTHROUGH`：PATH / HOME / 語系 / proxy / `CUDA_*` …）加上自己的 token 與資料來源憑證，伺服器的 `DATABASE_URL`、`AUTH_SECRET`、`JOB_TOKEN_SECRET`、`DATASET_SECRET_KEY` 不會出現在 `/proc/<pid>/environ`；`/internal/*` 的路徑只能在該任務的輸出目錄內（`job_relpath`），任務結束（任何終態）後 token 不再能寫入；MinIO 物件名稱與 zip 成員名稱都經 `safe_join` 檢查，不能寫到任務目錄之外；`GPU_RESET_COMMAND` 若用 `sudo -n nvidia-smi --gpu-reset` 要在 sudoers 只開放這一條指令。
- Keycloak 的 client secret 與 `AUTH_SECRET` 只在 `/etc/qr-ai-lab/*.env`（root:qrlab 640）；session cookie 加密、httpOnly；access token 只在伺服器端轉給 backend。
- 使用者資料集憑證：加密儲存、不入 log、不回前端；只以環境變數進入該 Job 容器。
- 上傳：大小上限、副檔名白名單、串流寫檔、路徑由伺服器產生（不用使用者檔名當路徑）。
- 所有管理員操作與 Job 狀態變更寫 `audit_logs`；UI 二次確認。
- 速率限制：`POST /auth/login` 每個 (client, 帳號) 5 分鐘內最多 10 次失敗（429），nginx 另加每分鐘 10 次；`APP_ENV=prod` 啟動時檢查 secret / Fernet 金鑰 / Keycloak 設定 / Redis（`Settings._check_production`）；Keycloak 模式只接受 `azp`（或 `aud`）是本 client 的 token，接管同名本地帳號時角色重設為 `user`。

## 15. v1 範圍與未來

- v1：單節點、本機儲存、批次推論、AutoML 單容器循序、SSE 代理、繁體中文 UI。
- 未來候選：自有 MinIO（`ObjectStorage`）、多節點（Ray 或 K8s Jobs）、常駐推論服務、實驗比較頁、通知（email / Teams）、i18n。
