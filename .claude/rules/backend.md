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
- `core/`：`config.py`（pydantic-settings，只從環境變數讀）、`security.py`（Keycloak JWT 驗證，PyJWT + JWKS 快取；per-job token）、`deps.py`（`get_db`、`get_current_user`、`require_admin`、`require_project_role`）。
- `scheduler/`：佇列迴圈（`queue_rank`）、總資源池與配額檢查、GPU / CPU 核心分配、以主機子程序啟動（`runner.py`：systemd cgroup scope 或 subprocess + affinity）/ 監看（watchdog）/ 強制中斷 / 重啟後接回、tail log 檔推事件、清理任務；不被 routers import。
- `storage/`：`base.py` 定義 `Storage` 介面，`local.py` 實作本機 `DATA_ROOT`（上傳串流寫檔、產物 stat / 讀取 / 刪除、目錄用量、Job 目錄準備）；所有路徑以相對 `DATA_ROOT` 儲存，絕不把使用者檔名當路徑。
- `catalog/`：`model_catalog.yaml`（資料類型 × 任務 × 模型 × 搜尋空間）與載入器。
- `utils/`：純函式，無 I/O。

## API 慣例

- 前綴 `/api/v1`；資源複數名詞 kebab-case；列表回 `{"items": [...], "total": n, "page": p, "page_size": s}`。
- 錯誤：`HTTPException(detail={"code": "PROJECT_NOT_FOUND", "message": "..."})`，code 用 UPPER_SNAKE；422 交給 FastAPI 預設。
- 每個 endpoint 都要 `response_model`、`status_code`、`tags`、docstring；`tests/` 至少一個 happy path + 一個權限拒絕測試。
- 授權順序：驗 JWT（Keycloak JWKS，快取 1 小時）→ upsert `users`（同步 realm role）→ 查專案角色。admin 可做任何事；owner / maintainer 管成員；member 建資料來源 / Job、取消本專案 Job；viewer 只讀（含看 log）。
- 長任務永遠非同步：endpoint 只建立 `jobs` row（status=queued，`queue_rank = max + 1000`）並回 202 + job id。
- 管理員操作（資源池、佇列重排、強制中斷、刪 Job、改配額、改角色）只在 `/admin/*`，一律寫 `audit_logs` 並記 reason。
- SSE：`GET /jobs/{id}/events` 從 Redis stream `job:{id}:events` 讀取；斷線可用 `Last-Event-ID` 續讀。log 歷史走 `GET /jobs/{id}/logs`（讀檔分頁）。
- Trainer → backend 的 `/internal/*` 端點只接受 per-job token（HS256，`JOB_TOKEN_SECRET`），並驗證 token 的 job id 與路徑一致。

## 程式風格

- Python 3.12、全面 async（`AsyncSession`、`httpx.AsyncClient`；檔案 I/O、psutil、sha256 等同步呼叫用 `asyncio.to_thread`）。
- Ruff lint + format（line-length 120）、完整型別註記、`from __future__ import annotations`。
- 不用 `print`；用 `structlog`，log 不含 token、密碼、使用者憑證。
- 設定只透過 `Settings`；測試（`tests/conftest.py`）用 SQLite 暫存檔 + 記憶體事件 bus + tmp `DATA_ROOT`，排程器用假 runner；`tests/test_e2e_subprocess.py` 以 subprocess runner 跑真的 trainer（`-m e2e`）。
- 使用者資料來源憑證以 Fernet（`DATASET_SECRET_KEY`）加密存 `data_sources.credentials_enc`，只在 scheduler 組裝 Job 子程序環境變數時解密；API 回應只回 `has_credentials`。
- 不留存政策是硬規則：任何寫入使用者資料的程式碼只能落在 `uploads/` 或 `jobs/{id}/input/`，而且必須有對應的刪除路徑（Job 終態、過期清理）。
- 改 DB 結構請同時遵守 `.claude/rules/database.md`。

## Trainer

- 每個 model family 實作 `BaseTrainer`（`prepare / fit / evaluate / export`）與 `BaseInferencer`（`load / predict`），註冊到 `trainer/models/registry.py`；id 必須與 `backend/app/catalog/model_catalog.yaml` 一致（CI 測試比對）。
- 輸入在 `JOB_INPUT_DIR`：upload 已就緒；data_source 由 trainer 以 `minio` SDK / `httpx` 自行下載到那裡（stage `fetching`，回報進度）。暫存只能寫 `JOB_OUTPUT_DIR/_work`（結束自刪）。輸出寫 `JOB_OUTPUT_DIR/{model|preprocessor|report|metrics|output}/`，再呼叫 `/internal/jobs/{id}/artifacts` 登記（path 可為目錄）；trainer 不直接連 DB，不持有任何伺服器端憑證。log 直接印到 stdout（`trainer/log.py` 加時間戳），排程器把 stdout 導到 log 檔。
- 預訓練權重只透過 `ctx.weight(id)` 從 `MODEL_ZOO_ROOT` 取得；runner 設 `HF_HUB_OFFLINE=1` 等離線變數，任何 `from_pretrained` / `YOLO(...)` 都必須指向本地路徑（`local_files_only=True`），絕不自行下載。
- 一律把有意義的進度印到 stdout（每 epoch / trial 一行，含指標），因為 stdout 就是使用者看到的 log；不要印憑證或完整環境變數。
- 尊重資源限制：GPU 由 scheduler 用 `CUDA_VISIBLE_DEVICES` 指定；DataLoader workers ≤ cpu_limit；batch size 由搜尋空間決定但要有 OOM 回退（減半重試一次）。
- AutoML：Optuna 單程序循序 trial，`MedianPruner`，受 `max_trials` 與 `time_budget_minutes` 限制；每個 trial 回報一筆 leaderboard row。
- 收到 SIGTERM（取消 / 強制中斷）時在 10 秒內結束：寫出目前 checkpoint 的指標到 stdout 後退出非 0。
