---
paths:
  - "backend/alembic/**"
  - "backend/app/models/**"
  - "docs/DATABASE.md"
  - "infra/mariadb/**"
---

# 資料庫規則（MariaDB 11 + SQLAlchemy 2.0 + Alembic）

- Schema 的真相在 `docs/DATABASE.md`：改表 = 先改文件 → 改 `app/models` → `alembic revision --autogenerate` → 檢視並修正遷移檔，三者同一個 commit。
- 命名：表名 snake_case 複數（`train_jobs`）；欄位 snake_case；FK 欄位 `<entity>_id`；索引 `ix_<table>_<cols>`；唯一鍵 `uq_<table>_<cols>`；外鍵 `fk_<table>_<col>`。
- 每張表：`id BIGINT UNSIGNED AUTO_INCREMENT` 主鍵、`created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)`、`updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)`（`project_members` 這類關聯表除外，用複合主鍵）。
- 列舉存 `VARCHAR(32)` + 應用層 Enum（SQLAlchemy `Enum(native_enum=False, length=32)`），不用 MySQL 原生 ENUM（改值要 ALTER）。
- JSON 欄位用 `JSON` 型別（MariaDB 為 LONGTEXT + `json_valid` CHECK），只放不需要查詢條件的設定 / 指標 / payload。
- 字集 `utf8mb4` / `utf8mb4_unicode_ci`；時間一律 UTC naive `DATETIME(6)`，由應用層轉時區。
- 軟刪除只用在 `projects.archived_at`；其他資料靠狀態欄位或直接刪除。刪專案前必須沒有 artifacts / running jobs（外鍵 RESTRICT，不 CASCADE 到產物）。
- 遷移：描述性 message（`add_train_jobs_table`）；禁止修改已套用到任何環境的遷移檔；資料搬移與 schema 變更分開兩個 revision。
- 查詢：避免 N+1（`selectinload`）；列表必分頁（預設 20，上限 100）；scheduler 取 queued job 用 `SELECT ... FOR UPDATE SKIP LOCKED`。
- 本地開發：`docker compose -f infra/docker-compose.yml up -d mariadb` → `uv run alembic upgrade head`；初始化 SQL（建庫、使用者、字集）放 `infra/mariadb/init/`。
