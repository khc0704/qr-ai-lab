# 從零啟動（本地開發 SOP）

從 `git pull` 到前端、基礎服務、（未來的）後端全部跑起來。每一節都可以獨立執行；目前前端用假資料，不需要後端就能看完整 UI。

## 0. 前置需求

| 工具 | 版本 | 檢查指令 | 備註 |
|---|---|---|---|
| Git | 任意 | `git --version` | |
| Node.js | ≥ 20.9，建議 22 LTS | `node --version` | Next.js 16 要求；用 [nvm](https://github.com/nvm-sh/nvm) 或 [fnm](https://github.com/Schniz/fnm) 管理 |
| npm | ≥ 10 | `npm --version` | 隨 Node 安裝；本專案用 npm，不用 pnpm / yarn |
| Python | 3.12 | `python3 --version` | `scripts/design_lint.py` 與未來的 backend |
| uv | 最新 | `uv --version` | backend 套件管理：`curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker Engine + Compose v2 | 最新 | `docker compose version` | MariaDB、Redis；伺服器上也跑 backend / scheduler |
| NVIDIA driver + NVIDIA Container Toolkit | 配合 GPU | `nvidia-smi`、`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` | 只有 GPU 伺服器需要（跑訓練容器） |
| Playwright Chromium | 隨 `playwright` 套件 | `cd frontend && npx playwright install chromium` | 只有要跑截圖 / 設計檢查時需要 |

## 1. 取得程式碼

```bash
git clone https://github.com/khc0704/qr-ai-lab.git
cd qr-ai-lab
git checkout <分支>          # 例如 main 或 claude/beautiful-pasteur-i6dgoc
```

## 2. 前端（Next.js 16）

```bash
cd frontend
npm ci                        # 依 package-lock.json 安裝（第一次或 lock 變更後）
npm run dev                   # http://localhost:3000，Turbopack，熱更新
```

- 預設登入身分是假資料的管理員「王小明」，所有頁面（含管理員區）都看得到；Keycloak 接上後才會有真正的登入。
- 常用指令：

| 指令 | 用途 |
|---|---|
| `npm run lint` | ESLint（Next.js 16 已移除 `next lint`） |
| `npm run typecheck` | 產生路由型別並做 TypeScript 檢查 |
| `npm run format` | Prettier（含 Tailwind class 排序） |
| `npm run build && npm run start` | 正式建置與啟動（http://localhost:3000） |
| `npm run screenshots` | 對所有主要頁面截圖到 `docs/screenshots/`（需先啟動 dev 或 start，並已安裝 Playwright Chromium） |
| `python3 ../scripts/design_lint.py src` | 設計 token 檢查（從 repo 根目錄則是 `python3 scripts/design_lint.py frontend/src`） |

- 改 UI 前先讀 `DESIGN.md`；Claude Code 使用者會自動載入 `.claude/rules/frontend.md`，而且 `.claude/settings.json` 的 hook 會在每次寫檔後跑設計檢查。

## 3. 基礎服務（MariaDB、Redis）

```bash
cp infra/.env.example infra/.env     # 填入 MARIADB_ROOT_PASSWORD、MARIADB_PASSWORD
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
docker compose -f infra/docker-compose.yml ps                      # 兩個 service 都應為 healthy
docker compose -f infra/docker-compose.yml exec mariadb mariadb -uqr -p qr_ai_lab -e "SELECT VERSION();"
docker compose -f infra/docker-compose.yml exec redis redis-cli ping
```

- 資料存在 docker volume（`qr-ai-lab_mariadb-data`、`qr-ai-lab_redis-data`）。
- 停止：`docker compose -f infra/docker-compose.yml down`；連資料一起刪：加 `-v`。
- 第一次啟動會執行 `infra/mariadb/init/01_create.sql`（字集與測試用資料庫）。

## 4. 後端（FastAPI）— 尚未建立

`backend/` 目前不存在。建立後的啟動流程（會隨實作更新此節）：

```bash
cd backend
cp ../infra/.env.example .env         # 或 export 環境變數；至少要 DATABASE_URL、REDIS_URL、DATA_ROOT
uv sync                               # 建立 .venv 並安裝依賴
uv run alembic upgrade head           # 建表（需要第 3 節的 MariaDB）
uv run uvicorn app.main:app --reload  # http://localhost:8000/docs
uv run python -m app.scheduler        # 另一個終端：排程器（需要 docker socket 與 DATA_ROOT）
```

- 訓練 / 推論容器映像：`docker build -t qr-ai-lab/trainer:dev -f infra/trainer/Dockerfile trainer`（trainer 建立後）。
- 前端接上後端：在 `frontend/.env.local` 設 `BACKEND_URL=http://localhost:8000`，並把 `src/lib/api/index.ts` 的假資料換成 fetch（頁面不用改）。

## 5. Keycloak（外部）

公司既有的 Keycloak。需要向管理 Keycloak 的人取得：realm 名稱、client id / secret（confidential client，Authorization Code + PKCE）、允許的 redirect URI `http://localhost:3000/api/auth/callback/keycloak`、realm role `admin` 與 `user`。填入 `frontend/.env.local`（`AUTH_*`）與 backend 的 `KEYCLOAK_*`。接上前所有身分都是假資料。

## 6. 推薦的日常流程

```bash
git pull
cd frontend && npm ci && npm run dev          # 終端 1
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d   # 需要 DB / Redis 時
# 改完 UI
npm run lint && npm run typecheck && python3 ../scripts/design_lint.py src
```

## 7. 常見問題

- **`EADDRINUSE: 3000`**：有別的 dev server 在跑；`npm run dev -- -p 3001` 換 port，或關掉舊的。
- **Node 版本太舊**：Next.js 16 需要 ≥ 20.9；`nvm install 22 && nvm use 22`。
- **Turbopack 快取怪異**：`rm -rf frontend/.next` 後重跑。
- **`npm ci` 失敗提到 lock 不一致**：確認用的是 npm 10 以上，且沒有用 pnpm / yarn 動過 `node_modules`。
- **Playwright 找不到瀏覽器**：`cd frontend && npx playwright install chromium`；或設 `CHROMIUM_PATH=/path/to/chrome` 再跑 `npm run screenshots`。
- **MariaDB 一直不 healthy**：第一次初始化要 20–40 秒；看 `docker compose -f infra/docker-compose.yml logs mariadb`。
- **Windows**：建議在 WSL2 內操作（Docker Desktop + WSL 整合），避免路徑與換行問題。
