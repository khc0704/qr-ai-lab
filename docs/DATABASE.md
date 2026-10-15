# 資料庫 Schema（MariaDB 11）

真相來源。改表時先改這裡，再改 `backend/app/models`，再產 Alembic 遷移（同一個 commit）。
通用規則見 `.claude/rules/database.md`：所有表有 `id BIGINT UNSIGNED AUTO_INCREMENT`、`created_at`、`updated_at DATETIME(6)`（關聯表與 `system_settings` 除外）；列舉存 `VARCHAR(32)`；時間 UTC；字集 utf8mb4。
本服務不存使用者資料集：`data_sources` 只存連線參考，`uploads` 只是暫存登記，檔案本體在 `DATA_ROOT` 且 Job 結束即刪。

## ER 概觀

```
users ──< project_requests ──(approve, 1:1)── projects ──< project_members >── users
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
| keycloak_sub | CHAR(36) NOT NULL | Keycloak `sub`；`uq_users_keycloak_sub` |
| username | VARCHAR(100) NOT NULL | `preferred_username` |
| email | VARCHAR(255) NOT NULL | `ix_users_email` |
| display_name | VARCHAR(100) NULL | |
| role | VARCHAR(32) NOT NULL DEFAULT 'user' | `admin \| user`；每次登入從 realm role 同步 |
| is_active | BOOL NOT NULL DEFAULT 1 | admin 可停用（停用者 API 全拒） |
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
- `resource_pool`：`{"gpu_indices": [0, 1], "cpu_cores": 24, "memory_mb": 98304, "max_running_jobs": 4, "allow_backfill": true}`，所有專案合計可用的總資源；scheduler 以此為容量上限。
- `job_defaults`：`{"timeout_minutes": 240, "upload_max_mb": 2048, "upload_ttl_minutes": 60, "log_max_mb": 50}`。

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

## project_requests（專案申請，與討論區分開）

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
| proposed_slug | VARCHAR(64) NULL | admin 核准時可改 |
| members | JSON NULL | `[{"email": "...", "role": "member"}]` |
| status | VARCHAR(32) NOT NULL DEFAULT 'submitted' | `submitted \| in_review \| approved \| rejected \| withdrawn` |
| reviewer_id | BIGINT UNSIGNED NULL FK users | |
| review_note | TEXT NULL | 退回理由 / 核准備註 |
| reviewed_at | DATETIME(6) NULL | |
| project_id | BIGINT UNSIGNED NULL FK projects | 核准後回填；`uq_project_requests_project_id` |
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
| status | VARCHAR(32) NOT NULL DEFAULT 'active' | `active \| archived` |
| owner_id | BIGINT UNSIGNED NOT NULL FK users | |
| request_id | BIGINT UNSIGNED NULL FK project_requests | 來源申請；`uq_projects_request_id` |
| gpu_limit | SMALLINT UNSIGNED NOT NULL DEFAULT 0 | 本專案同時可用 GPU 數 |
| cpu_limit | DECIMAL(5,2) NOT NULL DEFAULT 2 | |
| memory_limit_mb | INT UNSIGNED NOT NULL DEFAULT 4096 | |
| storage_quota_mb | INT UNSIGNED NOT NULL DEFAULT 10240 | `DATA_ROOT/projects/{slug}` 上限 |
| storage_used_bytes | BIGINT UNSIGNED NOT NULL DEFAULT 0 | 由 backend 重算目錄大小後更新 |
| max_concurrent_jobs | SMALLINT UNSIGNED NOT NULL DEFAULT 1 | |
| default_job_timeout_minutes | INT UNSIGNED NULL | NULL = 用 `system_settings.job_defaults` |
| approved_by_id | BIGINT UNSIGNED NULL FK users | |
| approved_at | DATETIME(6) NULL | |
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
| claimed_by_job_id | BIGINT UNSIGNED NULL FK jobs | 建立 Job 時搬到 `jobs/{job_id}/input/` 並標 claimed |
| expires_at | DATETIME(6) NOT NULL | pending 超過即 purge |
| created_by_id | BIGINT UNSIGNED NOT NULL FK users | |
| created_at | DATETIME(6) | 無 updated_at |

索引：`ix_uploads_status_expires_at`、`ix_uploads_project_id`。

## jobs（訓練與推論統一；單一全域佇列）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| project_id | BIGINT UNSIGNED NOT NULL FK projects | |
| kind | VARCHAR(32) NOT NULL | `train \| inference` |
| name | VARCHAR(120) NOT NULL | |
| status | VARCHAR(32) NOT NULL DEFAULT 'queued' | `queued \| scheduled \| running \| succeeded \| failed \| cancelled` |
| queue_rank | BIGINT NOT NULL | 佇列順序，小的先跑；新 Job = max + 1000；admin 重排會重新編號 |
| requested_gpu | SMALLINT UNSIGNED NOT NULL DEFAULT 0 | |
| requested_cpu | DECIMAL(5,2) NOT NULL DEFAULT 1 | |
| requested_memory_mb | INT UNSIGNED NOT NULL DEFAULT 2048 | |
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

- project_requests：`submitted → in_review → approved | rejected`；`rejected → submitted`（修改後重送）；`submitted | in_review → withdrawn`。
- issues：`open → closed`；`closed → open`（重開）。
- projects：`active → archived`。
- jobs：`queued → scheduled → running → succeeded | failed`；`queued | scheduled | running → cancelled`（成員取消、admin 強制中斷、逾時）。
- uploads：`pending → claimed`（建立 Job）；`pending → purged`（過期）。

## 初始化

- `infra/mariadb/init/01_create.sql`：建庫 `qr_ai_lab`（utf8mb4_unicode_ci）、應用使用者、最小權限。
- 表由 Alembic 建立；第一個 revision 包含以上全部表，並 seed `system_settings` 的 `resource_pool`（依 `NODE_*` 環境變數偵測到的實體值）與 `job_defaults`。
- 第一位 admin：Keycloak realm role `admin` 的使用者首次登入即為 admin；不需要 seed。
