# 審視：考慮不周之處與改善方向

對照目前的實作（backend / scheduler / trainer / libs/preprocess / 已串接 backend 的前端）逐項列出；標 ✅ 的是這一輪已做的。
分成「上線前必做」、「會讓使用者更好用」、「架構上要留意」、「模型與方法」四類；每項附目前狀態與建議做法。

## A. 上線前必做

1. ✅ **前端接 backend**：登入 → httpOnly cookie → `src/lib/api`（fetch）+ Server Actions + Route Handler 代理（上傳 / SSE / 下載）；沙盒以 SQLite + Redis + subprocess runner 走完整流程並截圖（`docs/screenshots/e2e/`、`docs/manuals/QR-AI-Lab-串接測試報告.pdf`）。待補：列表頁自動刷新（目前 RSC 需重新整理）、表單的樂觀更新。
2. ✅ **Keycloak**：`AUTH_MODE=keycloak`（後端驗 JWKS + azp，前端 Auth.js；token 更新只在 `proxy.ts` 並寫回 cookie）。本地帳號只剩登入失敗鎖定（5 分鐘 10 次）與 prod 的預設密碼拒絕，沒有密碼政策 / 到期，不要長期使用。
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
5. ✅ **CUDA 版本**：torch 由 `trainer/requirements-torch.txt`（index 寫在檔內：cu126；CPU 用 `requirements-torch-cpu.txt`；內網 `TORCH_INDEX_URL`）安裝，wheel 自帶 CUDA 函式庫；伺服器只要驅動版本對得上。
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
- infra：compose 只剩 MariaDB / Redis；`infra/systemd/*.service`、`infra/nginx/qr-ai-lab.conf`、`infra/install-00…03-*.sh`（走 PyPI / npm 鏡像）。

## G. 這一輪（Keycloak、三種角色、資源限制、GPU 共用、使用率歷史、前處理服務）新增的能力

- 認證：`AUTH_MODE=keycloak` 時前端用 Auth.js（`src/auth.ts`，Keycloak provider，PKCE，session 內自動 refresh）取得 access token 再轉給 FastAPI；後端驗 realm JWKS 只取身分（角色在 `users.role`；`KEYCLOAK_ROLE_MAP` 預設空，留作未來 opt-in）、`SUPERADMIN_USERNAME` 指定唯一的 superadmin、同名本地帳號自動接管；登出走 end-session。dev 維持本地帳號。`scripts/e2e-keycloak.mjs` + 假 Keycloak 可離線驗證整條流程。
- 角色：`superadmin | admin | user` 與權限矩陣（`app/core/permissions.py`，`require_perm`，`/me.permissions`）；superadmin 在 `/admin/users` 調整角色（最多到 admin；superadmin 由 `SUPERADMIN_USERNAME` 固定，不能指派 / 降級 / 停用）；新增刪專案、刪討論串、重啟任務；admin 的資源池 / 配額 / 模型庫頁改為唯讀。
- 資源限制：runner 設齊所有原生執行緒池變數（OMP / MKL / OpenBLAS / numexpr / TBB / numba / loky…），trainer `limits.py` 在程序內用 threadpoolctl + torch 再夾一次並把實際 affinity / 執行緒數印進 log。
- GPU：任務可填「每張 GPU 需要的顯存」，排程器依 pynvml 剩餘顯存 best-fit 讓多個任務共用一張（資源池 `gpu_share` 開關；trainer `set_per_process_memory_fraction`）；superadmin 可在 Dashboard 強制釋放顯存（中斷本系統任務 / kill 所有程序 / `GPU_RESET_COMMAND`）。
- 使用率歷史：`resource_samples` + `GET /admin/usage` + `/admin/usage` 頁（1h–30d、分母切換：專案配額 / 資源池 / 系統總量、各專案時間加權占用與實測 CPU / 記憶體）。
- 資料前處理服務（`/tools/preprocess`）：不需專案，上傳 → 預覽 → 整檔執行 → 下載 zip（processed.* + pipeline.json + summary.json），檔案只在 `DATA_ROOT/tools/<id>/`，下載 / 逾時即刪。
- 第二輪：GPU 改為**實測模式**（驅動程式實際用量 + 暖機期的「尚未分配」量；每個任務的實測顯存顯示在 GPU 卡片與使用率歷史）；前處理改為**任務**（個人工作區、佇列、配額、log、下載一次即刪、逾期清理），預覽維持即時；新增**資料分析**任務（表格探勘、影像品質飄移 / embedding）；`docs/ENVIRONMENT.md` 列出所有環境變數檔。
- 待辦：Keycloak 群組 → 專案成員的自動對應；使用率歷史匯出 CSV；分析報告 PDF 匯出；從專案內直接對資料來源啟動分析。

## H. 第三輪：自檢（四個面向的程式碼審視）後修掉的問題

安全與部署阻斷：systemd env 範本的行尾註解會變成值（已改成獨立行並加檢查）；`uv sync --frozen` 不走 PyPI proxy（伺服器改用 pip + `requirements.txt`）；MinIO 物件名稱 / zip 成員名稱的路徑穿越（`safe_join`）；任務子程序繼承伺服器 secret（環境白名單）；`/internal/*` 路徑只限 `DATA_ROOT`（改為任務目錄內 + 結束後拒絕寫入）；prod 接受預設 secret（啟動檢查）；Keycloak 同名帳號接管保留角色（重設為 user，keycloak 模式不 seed）；Keycloak 模式更新後的 token 寫不回 cookie（改由 proxy 更新）；登入後 `next=` 開放式重導向；登入沒有限速。

正確性：刪專案刪錯上傳目錄；刪 Job / 刪資料來源在 MariaDB 外鍵下 500（0005 + 解除引用；SQLite 測試也開外鍵）；GPU 暖機期以牆鐘計算造成重複配置（改為驅動看見程序前整個申請量保留）；實測 CPU 永遠 0；排隊超過 48 小時的任務輸入被清掉；AutoML 無標籤異常偵測最佳化 `score_mean`、trial 沒有 deadline；預覽 zip bomb / ReDoS；上傳代理整檔進記憶體；前端沒有 `error.tsx`、SSE 重播重複、斷線無提示、log 無上限；viewer 看得到不能用的按鈕；佇列頭 GPU 任務被 backfill 餓死；log 超過上限直接殺任務（改為就地截斷）；取消與啟動的競爭；重啟後 reconcile 讀到過期狀態；Redis 事件串流不過期；使用率歷史整段載入；`?min_role=` 外洩；欄位長度溢位等。

仍待做：Alembic 0001 仍是 `create_all`（要凍結成真正的 schema 並在 MariaDB 上跑 CI）；`docs/manuals` 與截圖讓 `.git` 超過 100 MB（改用 LFS 或 release 附件並清歷史）；XGBoost `device=cuda` 不受共用顯存上限約束（共用 GPU 時改走 CPU）；磁碟低於門檻時自動停排；資料來源瀏覽、通知、回寫 MES 等 B 節項目。

## I. 第四輪：使用回饋（申請 / 專案合併、工具池、前處理編輯器、討論區 Markdown、單一 superadmin）

- ✅ **申請就是專案**：`POST /projects` 送出申請即建立 `pending` 專案，專案頁的「申請」分頁承載申請內容、審核往返、核准 / 退回；核准前其他分頁不開放。狀態機 `pending → in_review → active | rejected`、`active → completed`（已結束，可重開）、`archived`。獨立的申請列表、`/admin/requests`、`/admin/quotas` 移除；配額在專案「設定」分頁；待審清單 = `/projects?status=pending`。
- ✅ **工具池**：所有前處理 / 分析任務共用一個系統專案（`kind=shared`，slug `tools`），配額與「每人同時任務數」在 Dashboard 的「工具池」設定；工具任務有自己的 `/tools/jobs/{id}` 頁，只有建立者與管理員看得到。舊的個人工作區封存（0007）。
- ✅ **前處理編輯器**：全寬 drawer 內的試算表式預覽（欄位標頭：型別 / 缺值 / 種類數 / 操作選單；列層級：重複列、缺值列、篩選；步驟串 chips 可調參數 / 排序；每次變動即時重新抽樣，變動的格子標色；輸入 → 輸出列數、新增 / 移除欄位與警告）；新增 `tabular.encode`（label / one-hot / ordinal，fit 後可 replay），`to_numeric` 改名並在大量值變缺值時警告；預覽多回傳每欄統計與每步警告。
- ✅ **討論區**：Markdown 編輯 / 預覽與安全渲染、作者或管理員可編輯討論串與留言、兩欄式發表表單；申請表的目的也用同一個編輯器。
- ✅ **帳號**：superadmin 固定一位（`SUPERADMIN_USERNAME`），介面只能指派 admin / user；Keycloak 只提供身分（`KEYCLOAK_ROLE_MAP` 預設空）；`GET /users/lookup` + 成員自動完成。
- ✅ **穩定性**：trainer 回報的 NaN / inf 一律變成 null（分析報告在群組太小、MAD 為 0 時不再讓任務失敗）；使用率取樣第一筆不再是 0；WSL2 下的節點數字在頁面上說明。
- 仍待做：工具池的 GPU 共用策略（目前與專案相同）；申請分頁的留言也支援編輯；前處理編輯器的欄位重新命名與型別轉換（datetime）；專案「已結束」後的產物保留期限。
