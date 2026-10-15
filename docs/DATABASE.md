# 資料庫 Schema（MariaDB 11）

真相來源。改表時先改這裡，再改 `backend/app/models`，再產 Alembic 遷移（同一個 commit）。
通用規則見 `.claude/rules/database.md`：所有表有 `id BIGINT UNSIGNED AUTO_INCREMENT`、`created_at`、`updated_at DATETIME(6)`（關聯表除外）；列舉存 `VARCHAR(32)`；時間 UTC；字集 utf8mb4。

## ER 概觀

```
users ──< project_members >── projects ──< datasets
  │                              │  ├──< train_jobs ──< artifacts ──< inference_jobs
  ├──< issues ──< issue_comments │  └──< inference_jobs
  └──< audit_logs                └── request_issue (1:1, nullable)
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

## projects

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| slug | VARCHAR(64) NOT NULL | URL 與 MinIO prefix 用；`uq_projects_slug`；`^[a-z0-9][a-z0-9-]{1,62}$` |
| name | VARCHAR(120) NOT NULL | |
| description | TEXT NULL | markdown |
| data_type | VARCHAR(32) NOT NULL | `TABULAR \| IMAGE \| SEQUENCE \| TEXT \| SPECTRUM` |
| task_type | VARCHAR(32) NOT NULL | `classification \| regression \| detection \| segmentation \| anomaly_detection` |
| status | VARCHAR(32) NOT NULL DEFAULT 'active' | `active \| archived` |
| owner_id | BIGINT UNSIGNED NOT NULL FK users | |
| request_issue_id | BIGINT UNSIGNED NULL FK issues | 來源申請單；`uq_projects_request_issue_id` |
| gpu_limit | SMALLINT UNSIGNED NOT NULL DEFAULT 0 | 同時可用 GPU 數 |
| cpu_limit | DECIMAL(5,2) NOT NULL DEFAULT 2 | 同時可用 CPU 核數 |
| memory_limit_mb | INT UNSIGNED NOT NULL DEFAULT 4096 | |
| storage_quota_mb | INT UNSIGNED NOT NULL DEFAULT 10240 | 專案空間 |
| storage_used_bytes | BIGINT UNSIGNED NOT NULL DEFAULT 0 | 只由 backend 更新 |
| max_concurrent_jobs | SMALLINT UNSIGNED NOT NULL DEFAULT 1 | |
| default_job_timeout_minutes | INT UNSIGNED NOT NULL DEFAULT 240 | |
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

## issues（討論區）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | 畫面顯示 `#id` |
| type | VARCHAR(32) NOT NULL | `project_request \| question \| bug \| feature` |
| title | VARCHAR(200) NOT NULL | |
| body | MEDIUMTEXT NOT NULL | markdown |
| status | VARCHAR(32) NOT NULL DEFAULT 'open' | `open \| in_review \| approved \| rejected \| closed` |
| author_id | BIGINT UNSIGNED NOT NULL FK users | |
| assignee_id | BIGINT UNSIGNED NULL FK users | admin 指派 |
| project_id | BIGINT UNSIGNED NULL FK projects | 關聯既有專案（question / bug）或核准後回填 |
| request_payload | JSON NULL | project_request：`{data_type, task_type, data_scale, requested: {gpu, cpu, memory_mb, storage_mb}, members: [email]}` |
| resolution_note | TEXT NULL | 退回理由 / 關閉說明 |
| resolved_by_id | BIGINT UNSIGNED NULL FK users | |
| resolved_at | DATETIME(6) NULL | approved / rejected / closed 時間 |
| comment_count | INT UNSIGNED NOT NULL DEFAULT 0 | 列表用的反正規化計數 |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_issues_status_created_at`、`ix_issues_type_status`、`ix_issues_author_id`、`ix_issues_project_id`。

## issue_comments

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| issue_id | BIGINT UNSIGNED NOT NULL FK issues ON DELETE CASCADE | |
| author_id | BIGINT UNSIGNED NULL FK users | system 事件為 NULL |
| kind | VARCHAR(32) NOT NULL DEFAULT 'comment' | `comment \| system`（狀態變更、指派、核准） |
| body | MEDIUMTEXT NOT NULL | markdown；system 為簡短句 |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_issue_comments_issue_id_created_at`。

## datasets

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| project_id | BIGINT UNSIGNED NOT NULL FK projects | |
| name | VARCHAR(120) NOT NULL | `uq_datasets_project_id_name` |
| source_type | VARCHAR(32) NOT NULL | `transient \| minio \| url` |
| uri | VARCHAR(1024) NOT NULL | transient：`tmp/datasets/{id}/`；minio：`s3://bucket/prefix`；url：完整 URL |
| endpoint | VARCHAR(255) NULL | 使用者自帶 MinIO 的 endpoint |
| credentials_enc | VARBINARY(4096) NULL | Fernet 加密的 JSON（access_key / secret_key / headers） |
| format | VARCHAR(32) NOT NULL | `csv \| parquet \| image_folder \| coco \| yolo \| npy \| jsonl \| spectrum_csv` |
| spec | JSON NULL | 欄位、target、類別、影像尺寸、split 比例、視窗長度等（見 MODEL_CATALOG §2） |
| size_bytes | BIGINT UNSIGNED NULL | |
| row_count | BIGINT UNSIGNED NULL | 列數 / 影像數 / 序列數的估計 |
| validated_at | DATETIME(6) NULL | 最近一次 validate 成功 |
| expires_at | DATETIME(6) NULL | transient 專用 |
| created_by_id | BIGINT UNSIGNED NOT NULL FK users | |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_datasets_project_id`、`ix_datasets_expires_at`。

## train_jobs

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| project_id | BIGINT UNSIGNED NOT NULL FK projects | |
| dataset_id | BIGINT UNSIGNED NOT NULL FK datasets ON DELETE RESTRICT | |
| name | VARCHAR(120) NOT NULL | |
| mode | VARCHAR(32) NOT NULL | `manual \| auto` |
| model_family | VARCHAR(64) NULL | manual 必填（例 `tabular.xgboost`）；auto 完成後回填最佳 |
| task_type | VARCHAR(32) NOT NULL | |
| config | JSON NOT NULL | manual：`{hyperparams, split, timeout_minutes}`；auto：`{search: {candidates, max_trials, time_budget_minutes, metric, direction}, timeout_minutes}` |
| status | VARCHAR(32) NOT NULL DEFAULT 'queued' | `queued \| scheduled \| running \| succeeded \| failed \| cancelled` |
| priority | SMALLINT NOT NULL DEFAULT 0 | admin 可調 |
| requested_gpu | SMALLINT UNSIGNED NOT NULL DEFAULT 0 | |
| requested_cpu | DECIMAL(5,2) NOT NULL DEFAULT 1 | |
| requested_memory_mb | INT UNSIGNED NOT NULL DEFAULT 2048 | |
| assigned_gpus | JSON NULL | 例 `[0]` |
| container_id | VARCHAR(64) NULL | |
| progress | DECIMAL(5,2) NOT NULL DEFAULT 0 | 0–100 |
| current_stage | VARCHAR(64) NULL | `preparing \| training \| evaluating \| exporting` |
| metrics | JSON NULL | 最終指標；auto 另含 `leaderboard: [...]` |
| error_message | TEXT NULL | |
| log_key | VARCHAR(512) NULL | 歸檔 log 的 MinIO key |
| cancel_requested_at | DATETIME(6) NULL | |
| started_at / finished_at | DATETIME(6) NULL | |
| created_by_id | BIGINT UNSIGNED NOT NULL FK users | |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_train_jobs_status_priority_created_at (status, priority, created_at)`、`ix_train_jobs_project_id_created_at`、`ix_train_jobs_dataset_id`。

## artifacts

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| project_id | BIGINT UNSIGNED NOT NULL FK projects | |
| train_job_id | BIGINT UNSIGNED NOT NULL FK train_jobs ON DELETE RESTRICT | |
| name | VARCHAR(120) NOT NULL | |
| version | INT UNSIGNED NOT NULL DEFAULT 1 | `uq_artifacts_project_id_name_version` |
| kind | VARCHAR(32) NOT NULL | `model \| weights \| preprocessor \| report \| metrics` |
| model_family | VARCHAR(64) NOT NULL | |
| framework | VARCHAR(32) NOT NULL | `sklearn \| xgboost \| torch \| ultralytics \| transformers` |
| storage_key | VARCHAR(512) NOT NULL | MinIO key |
| size_bytes | BIGINT UNSIGNED NOT NULL | |
| metrics | JSON NULL | |
| metadata | JSON NULL | 輸入 schema、類別名稱、前處理、automl 最佳參數 |
| is_default | BOOL NOT NULL DEFAULT 0 | 每專案最多一個 `kind=model` 為預設（service 層保證） |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_artifacts_project_id_kind`、`ix_artifacts_train_job_id`。

## inference_jobs

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| project_id | BIGINT UNSIGNED NOT NULL FK projects | |
| artifact_id | BIGINT UNSIGNED NOT NULL FK artifacts ON DELETE RESTRICT | |
| input_source_type | VARCHAR(32) NOT NULL | `inline \| transient \| minio \| url` |
| input_uri | VARCHAR(1024) NULL | |
| input_spec | JSON NULL | inline 資料或欄位對應 |
| status | VARCHAR(32) NOT NULL DEFAULT 'queued' | 同 train_jobs |
| requested_gpu / requested_cpu / requested_memory_mb | 同 train_jobs | 預設 0 / 1 / 2048 |
| container_id | VARCHAR(64) NULL | |
| result | JSON NULL | ≤ 1 MB 的結果 |
| output_key | VARCHAR(512) NULL | 大結果的 MinIO key |
| error_message | TEXT NULL | |
| started_at / finished_at | DATETIME(6) NULL | |
| created_by_id | BIGINT UNSIGNED NOT NULL FK users | |
| created_at / updated_at | DATETIME(6) | |

索引：`ix_inference_jobs_status_created_at`、`ix_inference_jobs_project_id_created_at`。

## audit_logs

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | BIGINT UNSIGNED PK | |
| actor_id | BIGINT UNSIGNED NULL FK users | system 動作為 NULL |
| action | VARCHAR(64) NOT NULL | `issue.approve \| project.quota.update \| job.cancel \| user.role.update …` |
| target_type | VARCHAR(32) NOT NULL | `issue \| project \| job \| artifact \| user` |
| target_id | BIGINT UNSIGNED NOT NULL | |
| payload | JSON NULL | 變更前後 |
| created_at | DATETIME(6) | 無 updated_at |

索引：`ix_audit_logs_target (target_type, target_id)`、`ix_audit_logs_created_at`。

## 狀態機摘要

- issues：`open → in_review → approved | rejected`；`rejected → open`（重新送審）；`question / bug / feature`：`open → closed`。
- projects：`active → archived`。
- train_jobs / inference_jobs：`queued → scheduled → running → succeeded | failed`；`queued | scheduled | running → cancelled`。

## 初始化

- `infra/mariadb/init/01_create.sql`：建庫 `qr_ai_lab`（utf8mb4_unicode_ci）、應用使用者、最小權限。
- 表由 Alembic 建立；第一個 revision 包含以上全部表。
- 第一位 admin：Keycloak realm role `admin` 的使用者首次登入即為 admin；不需要 seed。
