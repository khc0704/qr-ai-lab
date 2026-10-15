# 審視：考慮不周之處與改善方向

對照目前的實作（backend / scheduler / trainer / libs/preprocess / 已串接 backend 的前端）逐項列出；標 ✅ 的是這一輪已做的。
分成「上線前必做」、「會讓使用者更好用」、「架構上要留意」、「模型與方法」四類；每項附目前狀態與建議做法。

## A. 上線前必做

1. ✅ **前端接 backend**：登入 → httpOnly cookie → `src/lib/api`（fetch）+ Server Actions + Route Handler 代理（上傳 / SSE / 下載）；沙盒以 SQLite + Redis + subprocess runner 走完整流程並截圖（`docs/screenshots/e2e/`、`docs/manuals/QR-AI-Lab-串接測試報告.pdf`）。待補：列表頁自動刷新（目前 RSC 需重新整理）、表單的樂觀更新。
2. **Keycloak**：目前本地帳號；切換時 `AUTH_MODE=keycloak`，前端 Auth.js 也要接上。本地帳號的密碼政策、鎖定、到期都沒有，不要長期使用。
3. **HTTPS / nginx / 對外介面**：✅ `infra/nginx/qr-ai-lab.conf` 與 systemd 的 frontend service 已就位；憑證用公司 CA。沒有 TLS 時 `COOKIE_SECURE=0`。
4. **備份與還原演練**：`DATA_ROOT`（產物、模型庫）與 MariaDB 的備份排程寫在文件裡但沒有腳本；至少要有 `mariadb-dump` + rsync 的 cron 與一次還原演練。
5. **資源池與真實 GPU 的對應**：✅ 排程前用 pynvml 檢查分到的 GPU 顯存是否被別的程序占用（`GPU_BUSY_THRESHOLD`），忙就等。MIG 與顯存不均仍未處理。
6. **安全審視**：任務改為主機子程序後沒有容器隔離：任務與排程器同一個 OS 使用者（`qrlab`），彼此可讀對方的產物；使用者不提交程式碼所以先接受，要升級時改走 system 層 `systemd-run`（`DynamicUser=`、`ProtectSystem=strict`、`ReadWritePaths=`），runner 介面不變。`data_source` 任務需要內網抓資料（NO_PROXY 行為）；上傳 zip 已防 path traversal，但 parquet / npy 由第三方套件解析，建議限制大小並隔離在 trainer 內而非 backend。✅ 前處理預覽已加逾時（`PREVIEW_TIMEOUT_S`，預設 30 秒）與取樣上限，仍在 API 程序內執行。
7. **Alembic migration**：`0001_initial_schema` 以 `create_all` 產生，之後的 schema 變更要用 autogenerate 並在 MariaDB 上實際跑過；SQLite 與 MariaDB 的型別差異（JSON、DATETIME(6)）要在 CI 以 MariaDB 容器驗證一次。

## B. 讓使用者更好用

1. ✅ **前處理的 UI**：建立任務精靈第 2 步的 `PreprocessEditor`：從目錄加步驟、調參數、「抽樣預覽」並排顯示處理前 / 後（表格：統計 + 前幾列；影像：縮圖；曲線：折線）；步驟隨任務送出、訓練時 fit、推論沿用。
2. **訓練結果的視覺化**：✅ leaderboard 柱狀圖（最佳 trial 標示、hover 顯示參數）、✅ 機台比對的逐指標表（判定徽章）、✅ 推論結果預覽表；待做：混淆矩陣、殘差圖、PR 曲線、重建誤差分布、effect 圖。
3. **推論結果的回寫**：現在是下載 CSV / JSONL；製造現場通常要回寫 MES / 報表或 MinIO，建議加「輸出到使用者 MinIO」的選項（沿用資料來源憑證）。
4. **資料來源的瀏覽**：只做了連線檢查，沒有列出 bucket 內容讓使用者挑路徑；加一個分頁列目錄的 API 會省很多錯誤。
5. **任務範本與複製**：✅ 任務頁「複製設定」會把輸入規格、前處理、模式 / 家族 / 參數、資源帶進精靈（`/jobs/new?from=`）；待做：專案層級的任務範本。
6. **通知**：任務完成 / 失敗、申請核准，目前只有 UI；email 或 Teams webhook 很便宜就能加。
7. **多語 / 單位**：指標名稱、單位（nm、µm）、時區在 UI 要統一。
8. **資料集版本與重現性**：平台不保存資料，重現同一個模型只能靠「同一個資料來源路徑 + 同一組 spec」；✅ 一次性上傳現在會算 sha256 與大小，並連同偵測到的列數 / 影像數寫進任務的 `input.fingerprint`，檔案刪掉後仍可比對；資料來源任務待補（抓檔後在 trainer 內算）。

## C. 架構上要留意

1. **單一 scheduler 程序**：✅ 排程器重啟後以 pid + create_time（subprocess）或 systemd unit 名接回執行中的任務並重新 tail log；systemd service `Restart=always`。
2. **SQLite 僅限開發**：資料庫在單檔；沒有 `REDIS_URL` 時 event bus 在各程序的記憶體裡，backend 與排程器分開跑時 SSE 看不到 log 事件（沙盒串接測試即用本機 redis-server 解決）；正式環境一定要 Redis + MariaDB。
3. **大型產物與下載**：目錄產物即時打包 zip 會占記憶體與時間，大模型（YOLO m、BERT）建議 nginx `X-Accel-Redirect` 或預先打包。
4. **配額計算**：`storage_used_bytes` 以遞迴 stat 計算，專案產物多時每次任務結束都算一次會慢；可改為增量或背景計算。
5. **CUDA 版本**：trainer venv 用 PyPI 的 torch wheel（自帶 CUDA 函式庫），伺服器只要 driver 版本對得上；不行就在鏡像上放對應的 `+cu12x` wheel 並改 `uv.lock`。
6. **前處理在 backend 內執行**：預覽直接在 API 程序讀檔與運算（pandas / PIL），大檔或惡意檔會拖慢 API；已限制取樣大小並加 30 秒逾時（✅），但逾時只是放棄等待、執行緒仍會跑完，長期應搬到獨立 worker。
7. **AutoML 單容器循序**：候選含深度學習家族時一個任務可能跑很久；可加「每個 trial 的 epoch 上限」與「先用小資料子集篩家族再全量」兩段式。
8. **測試覆蓋**：systemd runner 只以假的 `systemd-run` 測參數組合，真正的 cgroup 強制要在伺服器上驗一次（建議：建一個申請 512 MB 的任務故意吃 1 GB，看是否被 OOM kill）；MariaDB、Keycloak、多 GPU 仍無自動化測試。

## D. 模型與方法

1. **影像品質基準**：目前 17 個經典指標 + Mahalanobis；可加 DINOv2 特徵分布距離當語意指標、依區域（中心 / 邊緣）分區統計、對焦序列（through-focus）自動找最佳焦。
2. **光譜**：MAE 迴歸頭是 Ridge；資料多時改 MLP / 微調；加入波長軸對齊（不同機台波長取樣不同）的前處理。
3. **時序**：只有 patch AE；FDC 多感測器可加 TCN / Transformer 與多變量相關性異常。
4. **Wafer map**：目前要先轉圖片；可做專用 loader（die map 矩陣 → 影像）與常見失效圖樣的分類範例。
5. **半監督 / 主動學習**：retrieve 找出的「最不像」樣本送人工標註再 `extend`，形成閉環；平台已有 `extend`，缺標註佇列與介面。
6. **校正與門檻**：異常門檻用 P99 經驗值；可加依驗證集最佳化 F1 的門檻與 OOD 拒答（few-shot 的 `min_similarity` 已有雛形）。
7. **模型解釋**：表格有特徵重要度；影像 / 光譜可加 Grad-CAM / patch 貢獻圖，現場更容易接受。
8. **評估的可信度**：小資料下驗證集只有幾筆，指標波動大；建議顯示信賴區間或用 repeated CV（表格家族容易做）。

## E. 這一輪串接測試發現並修掉的問題

- 寬內容（長 log 行、比對報告表）把整個內容欄撐寬：`SidebarInset` 缺 `min-w-0`，已修；表格外層加 `overflow-x-auto`。
- 伺服器與瀏覽器時鐘略有落差時，「剛建立」會顯示成「0 秒後」：`formatRelative` 對 5 分鐘內的負值一律顯示「剛剛」。
- 任務頁的指標卡顯示的是最後一個 trial 的指標而不是最佳模型：改為優先用 `result.metrics`（成功後）或 leaderboard 第一名的 `metrics`。
- 整數參數 / 指標（`n_estimators=500.0`、`n_golden 40.000`）：`formatMetric` 對整數不補小數。
- 序列 / 光譜預覽的統計是單一物件而非逐欄陣列，前端只處理了陣列：`PreviewSide.stats` 改為聯合型別並各自渲染。
- 前處理描述用 Python dict 顯示參數（`{'strategy': 'median'}`）：`Pipeline.describe()` 改輸出 JSON。
- Route Handler 不能用 `export const dynamic`（Cache Components 下 build 會失敗）：移除。

## F. 這一輪（任務不進容器 + 離線部署）新增的能力

- `JOB_RUNNER=auto | systemd | subprocess`：任務是主機子程序；systemd cgroup scope 強制記憶體 / CPU / 核心，subprocess 退路有 affinity + 記憶體 watchdog；兩者都能在排程器重啟後接回；GPU 啟動前預檢。
- `SCHEDULER_EMBEDDED=true`：排程器跑在 backend 程序內，開發機與小型部署不需要 Redis。
- 管理員「模型庫」頁：瀏覽器上傳、伺服器路徑匯入、內網 URL 下載，sha256 驗證、manifest、稽核；目錄回傳 `weights_ready`，精靈標示缺權重，建立任務時拒絕。
- Dashboard 顯示「任務執行方式」（runner、哪些限制由 cgroup 強制、trainer python 路徑）；任務頁顯示分到的 CPU 核心。
- infra：compose 只剩 MariaDB / Redis；`infra/systemd/*.service`、`infra/nginx/qr-ai-lab.conf`、`infra/install.sh`（走 PyPI / npm 鏡像）。
