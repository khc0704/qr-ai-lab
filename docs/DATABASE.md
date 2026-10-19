# 資料庫 Schema（MariaDB 11）

真相來源。改表時先改這裡，再改 `backend/app/models`，再產 Alembic 遷移（同一個 commit）。
通用規則見 `.claude/rules/database.md`：所有表有 `id BIGINT UNSIGNED AUTO_INCREMENT`、`created_at`、`updated_at DATETIME(6)`（關聯表與 `system_settings` 除外）；列舉存 `VARCHAR(32)`；時間 UTC；字集 utf8mb4。
本服務不存使用者資料集：`data_sources` 只存連線參考，`uploads` 只是暫存登記，檔案本體在 `DATA_ROOT` 且 Job 結束即刪。

## ER 概觀

```
users ──< project_requests ──(apply, 1:1)── projects ──< project_members >── users
  │                                              ├──< data_sources ──< jobs
  ├──< issues                                    ├──< uploads ──(claimed_by)── jobs
  ├──< comments (target_type: issue | project_request)
  ├──< audit_logs                                └──< jobs ──< artifacts ──(inference 引用)── jobs
system_settings（key / value，資源池等）
```

## users（Keycloak 使用者的本地鏡像）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| keycloak_sub | CHAR(36) NULL | Keycloak `sub`；`uq_users_keycloak_sub`；本地帳號為 NULL（Keycloak 第一次登入時同名本地帳號會被接管） |
| username | VARCHAR(100) NOT NULL | `preferred_username` / 本地帳號名 |
| email | VARCHAR(255) NOT NULL | `ix_users_email` |
| display_name | VARCHAR(100) NULL | |
| role | VARCHAR(32) NOT NULL DEFAULT 'user' | `superadmin \| admin \| user`；只在 UI（`/admin/users`）調整、最多到 admin；superadmin 只有一位，由 `SUPERADMIN_USERNAME` 固定（Keycloak 只提供身分，不覆蓋） |
| is_active | BOOL NOT NULL DEFAULT 1 | superadmin 可停用（停用者 API 全拒）；不能停用自己或 `SUPERADMIN_USERNAME` 的帳號 |
| auth_provider | VARCHAR(16) NOT NULL DEFAULT 'local' | `local \| keycloak` |
| password_hash | VARCHAR(255) NULL | argon2；只有 local |
| last_login_at | DATETIME(6) NULL | |
| created_at / updated_at | DATETIME(6) | |

## system_settings（管理員可調的全域設定）

| 欄位 | 型別 | 說明 |
|---|---|---|
| key | VARCHAR(64) PK | |
| value | JSON NOT NULL | |
| updated_by_id | BIGINT UNSIGNED NULL FK users | |
| updated_at | DATETIME(6) NOT NULL | |

固定 key：
- `resource_pool`：`{"gpu_indices": [0, 1], "cpu_cores": 24, "memory_mb": 98304, "max_running_jobs": 4, "allow_backfill": true, "gpu_share": true}`（`gpu_indices` 必須唯一且 ≥ 0），所有專案合計可用的總資源；scheduler 以此為容量上限。
- `job_defaults`：`{"timeout_minutes": 240, "upload_max_mb": 2048, "upload_ttl_minutes": 60, "log_max_mb": 50}`。
- `tool_pool`：工具池（`projects.kind = shared`）的配額、每人同時上限與結果保留時間 `{"gpu_limit": 0, "cpu_limit": 4, "memory_limit_mb": 8192, "storage_quota_mb": 4096, "max_concurrent_jobs": 2, "max_jobs_per_user": 2, "result_ttl_hours": 24}`；儲存時同步到工具池專案的配額欄位。

## issues（討論區）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | 畫面顯示 `#id` |
| type | VARCHAR(32) NOT NULL | `question \| bug \| feature` |
| title | VARCHAR(200) NOT NULL | |
| body | MEDIUMTEXT NOT NULL | markdown |
| status | VARCHAR(32) NOT NULL DEFAULT 'open' | `open \| closed` |
| author_id | BIGINT UNSIGNED NOT NULL FK users | |
| assignee_id | BIGINT UNSIGNED NULL FK users | admin 指派 |
| project_id | BIGINT UNSIGNED NULL FK projects | 可選關聯既有專案 |
| resolution_note | TEXT NULL | 關閉說明 |
| closed_by_id | BIGINT UNSIGNED NULL FK users | |
| closed_at | DATETIME(6) NULL | |
| comment_count | INT UNSIGNED NOT NULL DEFAULT 0 | 列表用的反正規化計數 |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_issues_status_created_at`、`ix_issues_type_status`、`ix_issues_author_id`、`ix_issues_project_id`。

## project_requests（專案申請內容；專案在送出時就建立）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| applicant_id | BIGINT UNSIGNED NOT NULL FK users | |
| title | VARCHAR(200) NOT NULL | 題目 |
| purpose | TEXT NOT NULL | 目的與背景（markdown） |
| data_type | VARCHAR(32) NOT NULL | `TABULAR \| IMAGE \| SEQUENCE \| TEXT \| SPECTRUM` |
| task_type | VARCHAR(32) NOT NULL | `classification \| regression \| detection \| segmentation \| anomaly_detection` |
| data_scale | VARCHAR(32) NOT NULL | `tiny \| small \| medium \| large`（對應 MODEL_CATALOG 的資料量級） |
| data_description | TEXT NULL | 資料來源與格式描述 |
| requested_gpu | SMALLINT UNSIGNED NOT NULL DEFAULT 0 | |
| requested_cpu | DECIMAL(5,2) NOT NULL DEFAULT 2 | |
| requested_memory_mb | INT UNSIGNED NOT NULL DEFAULT 4096 | |
| requested_storage_mb | INT UNSIGNED NOT NULL DEFAULT 10240 | |
| proposed_slug | VARCHAR(64) NULL | 送出時決定的專案 slug（建議值或由題目產生，保證唯一） |
| members | JSON NULL | `[{"email": "...", "role": "member"}]` |
| status | VARCHAR(32) NOT NULL DEFAULT 'submitted' | `submitted \| in_review \| approved \| rejected`（`projects.status` 的歷史鏡像；真相在 projects） |
| reviewer_id | BIGINT UNSIGNED NULL FK users | |
| review_note | TEXT NULL | 退回理由 / 核准備註 |
| reviewed_at | DATETIME(6) NULL | |
| project_id | BIGINT UNSIGNED NULL FK projects | 送出時回填（撤回時連同專案一起刪除）；`uq_project_requests_project_id` |
| submitted_at | DATETIME(6) NOT NULL | 重送時更新 |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_project_requests_status_submitted_at`、`ix_project_requests_applicant_id`。

## comments（討論區與專案申請共用）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| target_type | VARCHAR(32) NOT NULL | `issue \| project_request` |
| target_id | BIGINT UNSIGNED NOT NULL | 多型關聯；service 層驗證目標存在與權限，刪除目標時由 service 連帶刪留言 |
| author_id | BIGINT UNSIGNED NULL FK users | system 事件為 NULL |
| kind | VARCHAR(32) NOT NULL DEFAULT 'comment' | `comment \| system`（狀態變更、指派、核准） |
| body | MEDIUMTEXT NOT NULL | markdown；system 為簡短句 |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_comments_target (target_type, target_id, created_at)`。

## projects

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| slug | VARCHAR(64) NOT NULL | URL 與 `DATA_ROOT/projects/{slug}` 用；`uq_projects_slug`；`^[a-z0-9][a-z0-9-]{1,62}$` |
| name | VARCHAR(120) NOT NULL | |
| description | TEXT NULL | markdown |
| data_type | VARCHAR(32) NOT NULL | |
| task_type | VARCHAR(32) NOT NULL | |
| status | VARCHAR(32) NOT NULL DEFAULT 'pending' | `pending \| in_review \| active \| rejected \| completed \| archived` |
| kind | VARCHAR(16) NOT NULL DEFAULT 'standard' | `standard \| shared \| personal`；shared = 唯一的工具池（slug `tools`，所有前處理 / 分析任務），不列在專案列表，配額來自 `tool_pool`；personal = 舊版個人工作區（0007 封存） |
| owner_id | BIGINT UNSIGNED NOT NULL FK users | |
| request_id | BIGINT UNSIGNED NULL FK project_requests | 申請內容；`uq_projects_request_id`（工具池沒有） |
| gpu_limit | SMALLINT UNSIGNED NOT NULL DEFAULT 0 | 本專案同時可用 GPU 數 |
| cpu_limit | DECIMAL(5,2) NOT NULL DEFAULT 2 | |
| memory_limit_mb | INT UNSIGNED NOT NULL DEFAULT 4096 | |
| storage_quota_mb | INT UNSIGNED NOT NULL DEFAULT 10240 | `DATA_ROOT/projects/{slug}` 上限 |
| storage_used_bytes | BIGINT UNSIGNED NOT NULL DEFAULT 0 | 由 backend 重算目錄大小後更新 |
| max_concurrent_jobs | SMALLINT UNSIGNED NOT NULL DEFAULT 1 | |
| default_job_timeout_minutes | INT UNSIGNED NULL | NULL = 用 `system_settings.job_defaults` |
| approved_by_id | BIGINT UNSIGNED NULL FK users | |
| approved_at | DATETIME(6) NULL | |
| completed_at | DATETIME(6) NULL | 結束時間（`completed`） |
| archived_at | DATETIME(6) NULL | 軟刪除 |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_projects_owner_id`、`ix_projects_status_created_at`。

## project_members

| 欄位 | 型別 | 說明 |
|---|---|---|
| project_id | BIGINT UNSIGNED FK projects ON DELETE CASCADE | 複合 PK（project_id, user_id） |
| user_id | BIGINT UNSIGNED FK users | |
| role | VARCHAR(32) NOT NULL | `owner \| maintainer \| member \| viewer`；每專案恰一個 owner（service 層保證） |
| added_by_id | BIGINT UNSIGNED NULL FK users | |
| created_at | DATETIME(6) | |

索引：`ix_project_members_user_id`。

## data_sources（使用者的外部資料來源；只存參考，不存資料）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| project_id | BIGINT UNSIGNED NOT NULL FK projects | |
| name | VARCHAR(120) NOT NULL | `uq_data_sources_project_id_name` |
| kind | VARCHAR(32) NOT NULL | `minio \| url` |
| endpoint | VARCHAR(255) NULL | minio：`https://minio.example.com`（含 scheme） |
| bucket | VARCHAR(128) NULL | minio |
| object_path | VARCHAR(1024) NULL | minio：物件或前綴（結尾 `/` 表示整個前綴） |
| url | VARCHAR(2048) NULL | url |
| credentials_enc | VARBINARY(4096) NULL | Fernet 加密的 JSON：`{access_key, secret_key, region?}` 或 `{headers}` |
| format | VARCHAR(32) NOT NULL | `csv \| parquet \| image_folder \| coco \| yolo \| npy \| jsonl \| spectrum_csv` |
| default_spec | JSON NULL | 預設欄位設定（target、classes…），建立 Job 時可覆寫 |
| last_check_ok | BOOL NULL | `check` 結果 |
| last_check_message | VARCHAR(255) NULL | |
| last_checked_at | DATETIME(6) NULL | |
| created_by_id | BIGINT UNSIGNED NOT NULL FK users | |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_data_sources_project_id`。

## uploads（一次性上傳的暫存登記）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| project_id | BIGINT UNSIGNED NOT NULL FK projects | |
| original_filename | VARCHAR(255) NOT NULL | 只做顯示，不當路徑 |
| path | VARCHAR(512) NOT NULL | 相對 `DATA_ROOT`：`uploads/{id}/data.<ext>` |
| size_bytes | BIGINT UNSIGNED NOT NULL | |
| format | VARCHAR(32) NOT NULL | 同 data_sources.format |
| detected_spec | JSON NULL | 表頭、列數估計、影像數、類別 |
| status | VARCHAR(32) NOT NULL DEFAULT 'pending' | `pending \| claimed \| purged` |
| claimed_by_job_id | BIGINT UNSIGNED NULL FK jobs ON DELETE SET NULL | 建立 Job 時搬到 `jobs/{job_id}/input/` 並標 claimed；刪除 Job 時歸 NULL（migration 0005） |
| expires_at | DATETIME(6) NOT NULL | pending 超過即 purge |
| created_by_id | BIGINT UNSIGNED NOT NULL FK users | |
| created_at | DATETIME(6) | 無 updated_at |

索引：`ix_uploads_status_expires_at`、`ix_uploads_project_id`。

## jobs（訓練與推論統一；單一全域佇列）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| project_id | BIGINT UNSIGNED NOT NULL FK projects | |
| kind | VARCHAR(32) NOT NULL | `train \| inference \| preprocess \| analysis`（後兩者 = 工具池的工具任務，`input.tool = true`，只有 `created_by_id` 與管理員看得到） |
| name | VARCHAR(120) NOT NULL | |
| status | VARCHAR(32) NOT NULL DEFAULT 'queued' | `queued \| scheduled \| running \| succeeded \| failed \| cancelled` |
| queue_rank | BIGINT NOT NULL | 佇列順序，小的先跑；新 Job = max + 1000；admin 重排會重新編號 |
| requested_gpu | SMALLINT UNSIGNED NOT NULL DEFAULT 0 | |
| requested_cpu | DECIMAL(5,2) NOT NULL DEFAULT 1 | |
| requested_memory_mb | INT UNSIGNED NOT NULL DEFAULT 2048 | |
| requested_gpu_memory_mb | INT UNSIGNED NULL | 每張 GPU 需要的顯存；有值 = 可依剩餘顯存與其他任務共用一張 GPU（資源池 `gpu_share`），NULL = 獨占整張 |
| timeout_minutes | INT UNSIGNED NOT NULL | 建立時從專案或 job_defaults 決定 |
| assigned_gpus | JSON NULL | 例 `[0]` |
| assigned_cpus | JSON NULL | 排程器配給的邏輯 CPU 編號，例 `[0, 1]`（affinity / cgroup cpuset） |
| container_id | VARCHAR(64) NULL | |
| progress | DECIMAL(5,2) NOT NULL DEFAULT 0 | 0–100 |
| current_stage | VARCHAR(64) NULL | `fetching \| preparing \| training \| evaluating \| exporting \| predicting` |
| task_type | VARCHAR(32) NULL | train 必填；inference 取自 artifact |
| mode | VARCHAR(32) NULL | train：`manual \| auto` |
| model_family | VARCHAR(64) NULL | train manual 必填；auto 完成後回填最佳 |
| data_source_id | BIGINT UNSIGNED NULL FK data_sources ON DELETE RESTRICT | `input.kind = data_source` 時必填 |
| artifact_id | BIGINT UNSIGNED NULL FK artifacts ON DELETE RESTRICT | inference 必填 |
| input | JSON NOT NULL | `{kind: upload \| data_source \| inline, upload_id?, original_filename?, size_bytes?, format, spec, rows?}` |
| config | JSON NULL | train manual：`{hyperparams, split}`；auto：`{search: {candidates, max_trials, time_budget_minutes, metric, direction}}` |
| metrics | JSON NULL | 最終指標；auto 另含 `leaderboard` |
| result | JSON NULL | inference 的小結果（≤ 1 MB） |
| output_path | VARCHAR(512) NULL | 相對 `DATA_ROOT`：`projects/{slug}/jobs/{id}`（產物 / 推論輸出根目錄） |
| log_path | VARCHAR(512) NULL | `projects/{slug}/jobs/{id}/logs/job.log` |
| error_message | TEXT NULL | |
| cancel_requested_at | DATETIME(6) NULL | 成員取消或 admin 強制中斷 |
| cancel_requested_by_id | BIGINT UNSIGNED NULL FK users | |
| cancel_reason | VARCHAR(255) NULL | admin 強制中斷必填，顯示在 Job 詳情與 log |
| started_at / finished_at | DATETIME(6) NULL | |
| created_by_id | BIGINT UNSIGNED NOT NULL FK users | |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_jobs_status_queue_rank (status, queue_rank, created_at)`、`ix_jobs_project_id_created_at`、`ix_jobs_kind_status`、`ix_jobs_data_source_id`、`ix_jobs_artifact_id`。

## resource_samples（使用率歷史）

排程器每 `USAGE_SAMPLE_INTERVAL_S`（預設 30）秒寫一筆；`USAGE_RETENTION_DAYS`（預設 90）後由排程器的每小時清理刪除。

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| sampled_at | DATETIME(6) NOT NULL | `ix_resource_samples_sampled_at` |
| payload | JSON NOT NULL | `{node: {cpu_pct, cpu_cores, mem_used_mb, mem_total_mb, gpus: [{index, util, mem_used_mb, mem_total_mb}]}, pool: {gpu, cpu, memory_mb, running_jobs, gpu_total, cpu_total, memory_total_mb}, projects: {"<project_id>": {gpu, cpu, memory_mb, running_jobs, cpu_actual, mem_actual_mb}}}` |

`GET /admin/usage?range=1h|6h|24h|7d|30d` 依區間分桶平均（60 s / 5 min / 15 min / 1 h / 4 h）並算各專案的時間加權平均配置相對配額 / 資源池 / 系統總量的百分比。

## artifacts（訓練產物，存於本機 `DATA_ROOT`）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| project_id | BIGINT UNSIGNED NOT NULL FK projects | |
| job_id | BIGINT UNSIGNED NOT NULL FK jobs ON DELETE RESTRICT | 產生它的訓練 Job |
| name | VARCHAR(120) NOT NULL | |
| version | INT UNSIGNED NOT NULL DEFAULT 1 | `uq_artifacts_project_id_name_version` |
| kind | VARCHAR(32) NOT NULL | `model \| weights \| preprocessor \| report \| metrics` |
| model_family | VARCHAR(64) NOT NULL | |
| framework | VARCHAR(32) NOT NULL | `sklearn \| xgboost \| torch \| ultralytics \| transformers` |
| path | VARCHAR(512) NOT NULL | 相對 `DATA_ROOT`：`projects/{slug}/jobs/{job_id}/model/...` |
| size_bytes | BIGINT UNSIGNED NOT NULL | backend `stat` 取得 |
| metrics | JSON NULL | |
| metadata | JSON NULL | 輸入 schema、類別名稱、前處理、automl 最佳參數 |
| is_default | BOOL NOT NULL DEFAULT 0 | 每專案最多一個 `kind=model` 為預設（service 層保證） |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_artifacts_project_id_kind`、`ix_artifacts_job_id`。

## audit_logs

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| actor_id | BIGINT UNSIGNED NULL FK users | system 動作為 NULL |
| action | VARCHAR(64) NOT NULL | `project_request.approve \| project.quota.update \| settings.resource_pool.update \| queue.reorder \| job.stop \| job.cancel \| job.delete \| user.role.update …` |
| target_type | VARCHAR(32) NOT NULL | `project_request \| issue \| project \| job \| artifact \| user \| settings` |
| target_id | BIGINT UNSIGNED NULL | settings 類為 NULL |
| payload | JSON NULL | 變更前後、理由 |
| created_at | DATETIME(6) | 無 updated_at |

索引：`ix_audit_logs_target (target_type, target_id)`、`ix_audit_logs_created_at`。

## 狀態機摘要

- project_requests：`submitted → in_review → approved | rejected`；`rejected → submitted`（修改後重送）；撤回 = 連同專案刪除（鏡像 projects）。
- issues：`open → closed`；`closed → open`（重開）。
- projects：`pending → in_review → active | rejected`；`rejected → pending`（修改後重送）；`pending | in_review | rejected → （撤回，刪除）`；`active → completed → active`（重新開啟）；`active | completed → archived → active`（解除封存）。
- jobs：`queued → scheduled → running → succeeded | failed`；`queued | scheduled | running → cancelled`（成員取消、admin 強制中斷、逾時）。
- uploads：`pending → claimed`（建立 Job）；`pending → purged`（過期）。

## 遷移注意事項

`0001_initial_schema` 以 `Base.metadata.create_all` 建表，所以**全新的資料庫在 0001 就已經是目前的 schema**；之後的每個遷移（0002 `assigned_cpus`、0003 `requested_gpu_memory_mb` + `resource_samples`、0004 `projects.kind`）；0005 把 `uploads.claimed_by_job_id` 改成 ON DELETE SET NULL（SQLite 跳過，因為 0001 已是最新 schema）都要先用 `sa.inspect()` 檢查欄位 / 表是否存在再加，既能升級舊資料庫也能在新資料庫上跑到 head。新增遷移時沿用同一寫法。

## 初始化

- `infra/mariadb/init/01_init.sh`：容器第一次啟動時依 `MARIADB_DATABASE` / `MARIADB_USER` 補字集並建立 `<db>_test`（資料庫與使用者本身由 MariaDB 映像的環境變數建立）。
- 表由 Alembic 建立；第一個 revision 包含以上全部表；`system_settings` 的 `resource_pool`（依 pynvml / psutil 偵測到的實體值）、`job_defaults`、`tool_defaults` 在第一次讀取時寫入。
- 唯一的 superadmin：`SUPERADMIN_USERNAME` 指定的帳號首次登入（或服務啟動）時即為 superadmin，其他帳號由 superadmin 在 `/admin/users` 指派為 admin / user；keycloak 模式不 seed 本地帳號。SQLite（dev / test）也會開 `PRAGMA foreign_keys=ON`，外鍵行為與 MariaDB 一致。
