---
paths:
  - "backend/**/*.py"
  - "backend/pyproject.toml"
  - "trainer/**/*.py"
  - "trainer/pyproject.toml"
---

# Backend / Trainer 規則（FastAPI + SQLAlchemy 2.0 async）

## 分層（嚴格遵守）

- `routers/`：只做 HTTP：解析請求、呼叫 service、回傳 schema。不寫業務邏輯、不直接下 SQL。
- `services/`：業務邏輯與交易邊界（一個 service 函式 = 一個 use case）。可呼叫其他 service、storage、queue。
- `models/`：SQLAlchemy ORM（`Mapped[]` 註記 + `mapped_column`），每個聚合一個檔案；所有表繼承 `Base`（含 `id`、`created_at`、`updated_at`）。
- `schemas/`：Pydantic v2，命名 `XxxCreate | XxxUpdate | XxxRead | XxxList`；`model_config = ConfigDict(from_attributes=True)`。
- `core/`：`config.py`（pydantic-settings，只從環境變數讀）、`security.py`（Keycloak JWT 驗證，PyJWT + JWKS 快取）、`deps.py`（`get_db`、`get_current_user`、`require_admin`、`require_project_role`）。
- `scheduler/`：排程迴圈、資源管理、Docker 啟動；不被 routers import。
- `storage/`：MinIO 客戶端、presigned URL、資料集來源解析（transient / minio / url）。
- `catalog/`：`model_catalog.yaml`（資料類型 × 任務 × 模型 × 搜尋空間）與載入器。
- `utils/`：純函式，無 I/O。

## API 慣例

- 前綴 `/api/v1`；資源複數名詞 kebab-case；列表回 `{"items": [...], "total": n, "page": p, "page_size": s}`。
- 錯誤：`HTTPException(detail={"code": "PROJECT_NOT_FOUND", "message": "..."})`，code 用 UPPER_SNAKE；422 交給 FastAPI 預設。
- 每個 endpoint 都要 `response_model`、`status_code`、`tags`、docstring；`tests/` 至少一個 happy path + 一個權限拒絕測試。
- 授權順序：驗 JWT（Keycloak JWKS，快取 1 小時）→ upsert `users`（同步 realm role）→ 查專案角色。admin 可做任何事；owner / maintainer 管成員、配額內調 job；member 建 dataset / job；viewer 只讀。
- 長任務永遠非同步：endpoint 只建立 job row（status=queued）並回 202 + job id。
- SSE：`GET /jobs/{id}/events` 從 Redis stream `job:{id}:events` 讀取；斷線可用 `Last-Event-ID` 續讀。
- Trainer → backend 的 `/internal/*` 端點只接受 per-job token（HS256，`JOB_TOKEN_SECRET`），並驗證 token 的 job id 與路徑一致。

## 程式風格

- Python 3.12、全面 async（`AsyncSession`、`httpx.AsyncClient`；MinIO SDK 同步呼叫用 `asyncio.to_thread`）。
- Ruff lint + format（line-length 100）、完整型別註記、`from __future__ import annotations`。
- 不用 `print`；用 `structlog`，log 不含 token、密碼、憑證。
- 設定只透過 `Settings`；測試用 `.env.test` + 測試用 MariaDB（docker）或 SQLite 僅限純邏輯測試。
- 資料集憑證以 Fernet（`DATASET_SECRET_KEY`）加密存 `datasets.credentials_enc`，只在 scheduler 組裝容器環境變數時解密。
- 改 DB 結構請同時遵守 `.claude/rules/database.md`。

## Trainer

- 每個 model family 實作 `BaseTrainer`（`prepare / fit / evaluate / export`）與 `BaseInferencer`（`load / predict`），註冊到 `trainer/models/registry.py`；id 必須與 `backend/app/catalog/model_catalog.yaml` 一致（CI 測試比對）。
- 只透過 backend `/internal/*` API 取得 job spec、回報 status / metrics / log、取得產物上傳的 presigned URL；trainer 不直接連 DB、不持有 MinIO 根憑證。
- 尊重資源限制：GPU 由 scheduler 用 `CUDA_VISIBLE_DEVICES` 指定；DataLoader workers ≤ cpu_limit；batch size 由搜尋空間決定但要有 OOM 回退（減半重試一次）。
- AutoML：Optuna 單容器循序 trial，`MedianPruner`，受 `max_trials` 與 `time_budget_minutes` 限制；每個 trial 回報一筆 leaderboard row。
- 產物路徑固定 `projects/{slug}/jobs/{job_id}/{kind}/...`；最後呼叫 `complete` 讓 backend 計算配額用量。
