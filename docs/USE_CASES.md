# 半導體 / 電子製造的資料類型、模型與推論目的

這份文件回答「我們廠裡的哪種資料，可以用哪個模型，推論的時候到底要拿它做什麼」。模型本身只是手段；
每個情境都先定義**推論目的**（inference mode），再回推訓練方式。所有家族的實作在 `trainer/trainer/models/`，
目錄與搜尋空間在 `docs/MODEL_CATALOG.md`。

## 1. 推論模式（先想清楚推論要做什麼）

| mode | 白話 | 輸出 | 誰提供 |
|---|---|---|---|
| `predict` | 給一筆資料，回一個類別或數值 | `prediction`、`confidence` / 各類機率 | 表格、文字、DINO few-shot、YOLO 分類、光譜 MAE 迴歸頭 |
| `score` | 這筆資料「正不正常」 | `anomaly_score`、`is_anomaly`（門檻存在模型裡，可覆寫） | Isolation Forest、Patch AE、光譜 MAE、PatchCore（附熱圖） |
| `embed` | 把資料變成向量，給下游分析（分群、繪圖、相似度） | `embedding`（另存 `embeddings.npy`） | 所有深度學習家族 |
| `retrieve` | 跟參考庫比：最相似 / 最不相似是誰、有多新 | `most_similar[]`、`least_similar[]`、`max_similarity`、`novelty` | Patch AE、光譜 MAE（參考庫 = 訓練視窗）、DINO few-shot（參考庫 = 範例影像） |
| `detect` / `segment` | 圖裡東西在哪、哪些像素 | 框、遮罩、標註圖 | YOLO |
| `measure` | 從分割遮罩算幾何量（面積、寬高、等效直徑；給 `pixel_size` 可換算 nm / µm） | 每個物件一列 | YOLO segmentation |
| `extend` | **不重訓**，直接把新類別（新 bin code）的範例加進原型庫，產生新版本模型 | 新 model artifact（自動設為預設） | DINO few-shot |
| `compare` | 整批影像與黃金機台的影像品質基準比對（調機驗收） | 每個指標 match / drift / fail、總判定、`comparison.csv` | 影像品質基準 |

推論 Job 的 `config.mode` 指定模式；不填就用該模型 `inference_modes` 的第一個。

## 2. 總表：機台 / 資料 → 模型 → 推論目的

| 來源 | data_type | 情境 | 建議家族 | 推論目的 |
|---|---|---|---|---|
| OCD / 散射量測、橢圓偏光、反射光譜 | `SPECTRUM` | 光譜鑑別器：和黃金樣本比，找最像 / 最不像、追蹤批次漂移 | `spectrum.masked_autoencoder`（候補 `sequence.patch_autoencoder`） | `retrieve`、`score` |
| 同上 + 有量測值（CD、膜厚、側壁角） | `SPECTRUM` × `regression` | 光譜 → 量測值（快速虛擬量測） | `spectrum.masked_autoencoder`（自監督 + Ridge 迴歸頭） | `predict` |
| FTIR / Raman / XRF / PL | `SPECTRUM` | 材料 / 配方 / 批次異常、污染偵測 | 同上 | `score`、`retrieve`、`embed` |
| TEM / SEM / 光學顯微 表面影像 | `IMAGE` × `classification` | bin code 分類，類別會持續增加 | `vision.dino_fewshot`（每類幾張就能用；新類別用 `extend`） | `predict`、`retrieve`、`extend` |
| 同上，資料量大、類別固定 | `IMAGE` × `classification` | 高準確度分類 | `vision.yolo`（`-cls` 權重微調，或 `pretrained=false` 從頭訓） | `predict` |
| 同上，只有良品影像 | `IMAGE` × `anomaly_detection` | 找「跟正常不一樣」的影像並標出位置 | `vision.dino_patchcore` | `score`（含熱圖） |
| SEM 線寬 / 孔洞 / 顆粒 | `IMAGE` × `segmentation` | 分割後量測幾何 | `vision.yolo`（`-seg`） | `segment`、`measure` |
| 任何機台（SEM / TEM / 光學）的影像品質 | `IMAGE` × `anomaly_detection` | 黃金機台建立品質基準與浮動範圍；調機後驗收、日常監控 | `vision.image_quality`（CPU、免權重） | `compare`、`score` |
| AOI / 外觀檢測 | `IMAGE` × `detection` | 缺陷定位、計數、分類 | `vision.yolo` | `detect` |
| Wafer map / bin map | `IMAGE` × `classification` | 失效圖樣（環、刮痕、邊緣…）分類 | 先把 map 轉成圖片 → `vision.dino_fewshot` / `vision.yolo` | `predict` |
| FDC / 機台感測器 trace | `SEQUENCE` × `anomaly_detection` | 異常 run 偵測、找相似 run | `sequence.patch_autoencoder` | `score`、`retrieve`、`embed` |
| FDC 摘要特徵 + 量測值 | `TABULAR` × `regression` | 虛擬量測（VM） | `tabular.xgboost`（AutoML 會一起試 RF / 線性） | `predict` |
| WAT / PCM / 電性、良率表 | `TABULAR` × `classification` / `regression` | 良率預測、失效分類、找關鍵參數（特徵重要度） | `tabular.xgboost`、`tabular.random_forest`、`tabular.linear`（可解釋基準） | `predict` |
| WAT / PCM 多參數 | `TABULAR` × `anomaly_detection` | 參數組合離群（單一 spec 內但組合怪） | `tabular.isolation_forest` | `score` |
| 設備 log、工單、客訴、8D 報告 | `TEXT` × `classification` | 自動歸類、派工 | `text.bert_classifier`（小資料先用 `tabular.linear` TF-IDF 基準） | `predict`、`embed` |

## 3. 各情境 SOP

### 3.1 OCD 光譜鑑別器（黃金樣本比對、漂移、異常）

- **資料**：寬表 `spectrum_csv`（每列一筆光譜，欄 = 波長 / 波數）或 `npy`（`N × T`）。可選 `label` 欄（`normal` / 異常種類）評估用；沒有標籤也能訓練。
- **訓練**：`mode=auto`（候選 `spectrum.masked_autoencoder`、`sequence.patch_autoencoder`）或手動 `spectrum.masked_autoencoder`。有標籤時只用正常樣本訓練，異常樣本留在驗證集算 `auroc`。
- **產物**：`model/model.pt`、`reference.npz`（訓練光譜的 embedding = 黃金樣本庫）、門檻（訓練分數的 P99）。
- **推論**：
  - `retrieve`（`k=5`）：每條新光譜回最相似 / 最不相似的黃金樣本 id、`max_similarity`、`novelty`；`summary.most_novel` 直接列出最可疑的樣本。`config.reference="self"` 可改成輸入資料彼此比。
  - `score`：`anomaly_score`（遮蔽重建誤差）與 `is_anomaly`；可用 `config.threshold` 覆寫門檻。
  - 漂移追蹤：定期對新批次跑 `retrieve`，看 `max_similarity` 中位數是否下降。
- **讀結果**：`auroc > 0.9` 才可靠；`novelty` 高但 `anomaly_score` 低 = 是新的、但重建得來（可能是製程改變而非缺陷），兩個一起看。

### 3.2 光譜 → CD / 膜厚（迴歸）

- 同 3.1 的資料，再加 `label` 欄為量測值；`task_type=regression`。
- MAE 先做自監督預訓練，再以 embedding 接 Ridge 迴歸頭（`ridge_alpha`）；指標 `rmse`、`mae`、`r2`。
- 推論 `predict`：每筆回 `prediction` 與 `reconstruction_error`（誤差大 = 這筆光譜不在訓練分布內，預測值別信）。

### 3.3 TEM / SEM 表面影像 bin code（few-shot，新類別免重訓）

- **資料**：zip，`<bin_code>/*.png`，每類 ≥ 3 張即可開始（建議 10+）。
- **訓練**：`vision.dino_fewshot`（`backbone=dinov2-small` 或 `dinov2-base`，`k` = kNN 票數）。凍結 DINOv2 取 CLS + 平均 patch 特徵，每類存原型；評估用分層切分或 leave-one-out。
- **新增 bin code**：建推論 Job，`config.mode="extend"`，輸入是新類別的資料夾 zip → 產生新版本模型並設為預設，原本的類別都保留。
- **推論**：`predict`（`config.min_similarity` 低於門檻回 `unknown`，避免硬塞進既有類別）、`retrieve`（看最像的範例影像，方便人工覆核）。
- **何時改用 YOLO 分類**：類別固定、每類有數百張、要更高準確度 → `vision.yolo`（`model=yolov8s`、`pretrained=true` 用模型庫的 `yolov8s-cls.pt` 微調；`pretrained=false` 從頭訓練）。

### 3.4 只有良品影像：PatchCore 異常 + 熱圖

- 資料夾 `good/`（或 `normal/`、`ok/`）為正常；其他資料夾視為異常（只用來評估）。
- `vision.dino_patchcore`：DINOv2 patch 特徵建記憶庫（`coreset_ratio` 抽樣），分數 = patch 到記憶庫的最近距離，影像分數 = 最大 patch 分數；門檻 = 正常訓練影像的 P99。
- 推論 `score`：每張回分數、`hot_patch_row/col`，`output/heatmaps/*.png` 熱圖（`config.save_heatmaps=false` 可關）。

### 3.5 SEM 線寬 / 顆粒量測

- YOLO segmentation 格式（多邊形標註 + `data.yaml`）訓練 `vision.yolo`（`-seg`）。
- 推論 `measure`：每個物件回 `area_px`、`width_px`、`height_px`、`equiv_diameter_px`；`config.pixel_size`（例如 2.5 代表每像素 2.5 nm）會多給 `*_phys` 欄。

### 3.5b 影像品質基準與機台比對（tool matching）

- **問題**：沒有標準答案的「影像品質」要怎麼量？做法是把黃金機台的一批影像變成 17 個無參考指標（清晰度 Laplacian / Tenengrad / Brenner、雜訊標準差、訊噪比、對比 RMS / Michelson、亮度平均 / P1 / P99、過暗 / 過亮飽和比例、亮度熵、高頻能量比、頻譜斜率、梯度與頻譜的方向性），以穩健中位數與 MAD 建立基準與浮動範圍（中位數 ± 3 × 尺度），並以 Mahalanobis 距離做整體判定。
- **訓練**：`vision.image_quality`，資料夾 `good/` 放黃金機台影像（≥ 30 張較穩）；其他資料夾可放已知偏差的影像當驗證。產物 `report/baseline_ranges.csv` 直接是每個指標的允收範圍。
- **推論 `compare`**：把調機後機台的一批影像丟進來 → 每個指標的 effect（偏移幾個尺度）、KS 檢定 p 值、in_range_ratio 與 verdict，總判定 pass / drift / fail，`output/comparison.csv` 就是調機報告；`score` 給單張影像的 z 分數與距離做日常監控。
- **注意**：基準只適用同類樣品與同倍率；先用前處理 `image.crop` 裁掉 SEM 資訊列。像散 / 掃描方向問題會反映在方向性指標，焦距在清晰度與高頻能量比，亮度 / 對比設定在亮度與飽和比例。
- **可再加**：DINOv2 特徵分布距離（Fréchet）當第 18 個「語意」指標、依樣品結構分區計算（中心 / 邊緣）。

### 3.6 FDC trace 異常 / 找相似 run

- 長表 `series_id,t,feature…` + `spec.window` / `stride`（切視窗），或 `npy` `N × T × C`。
- `sequence.patch_autoencoder`：patch 嵌入 + 位置編碼 + 整段視窗壓到一個 latent，所以「峰值移位」也抓得到。
- 推論 `score`、`retrieve`（找跟歷史最像 / 最不像的 run）、`embed`（丟到 BI 做分群）。

### 3.7 WAT / PCM / 良率表

- `csv` / `parquet`，`spec.target` 為目標欄；類別欄自動 one-hot，缺值自動補。
- 第一次用 `mode=auto`：XGBoost / 隨機森林 / 線性 / SVM（> 50k 列自動剔除 SVM；< 1k 列優先隨機森林），leaderboard 看完再手動微調。
- 產物附 `report/feature_importance.json`（前 50 個特徵），可直接拿去開會。
- 只想找離群：`task_type=anomaly_detection` → `tabular.isolation_forest`，推論 `score`。

### 3.8 設備 log / 工單文字

- `jsonl` 或 `csv`，`spec.text_column` / `label_column`。
- < 300 筆：AutoML 只會用 TF-IDF + 邏輯迴歸（秒級）；≥ 300 筆加入 `text.bert_classifier`（模型庫的 `bert-base-chinese` / `xlm-roberta-base`，需要 GPU）。
- 推論 `predict`（各類機率）或 `embed`（CLS 向量）。

## 3.10 資料前處理（所有資料類型）

上傳後可挑選前處理步驟並即時抽樣預覽（表格補值 / 離群 / 標準化、影像裁切 / 對比 / 去雜訊 / 對位、光譜 SNV / MSC / 平滑 / 基線、文字清理），步驟隨任務送出；訓練時學到的數值存進模型，推論自動沿用。清單見 `docs/MODEL_CATALOG.md` §4.2。

## 4. 預訓練權重政策（模型庫）

- 伺服器上的 Job 容器**離線**（`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`YOLO_OFFLINE=1`），不會從任何套件自動下載模型。
- 需要的權重清單在 `backend/app/catalog/model_catalog.yaml` 每個家族的 `weights`；管理員在**有網路的機器**執行
  `python3 scripts/fetch_model_zoo.py --dest ./model_zoo`，把整個資料夾放到伺服器的 `MODEL_ZOO_ROOT`（預設 `DATA_ROOT/model_zoo`），
  再用 `.venv/bin/python -m app.cli model-zoo --verify` 或管理員頁「模型庫」確認。
- sklearn / XGBoost 家族沒有預訓練權重，直接訓練；`vision.yolo` 的 `pretrained=false` 也不需要權重。
- 缺權重時 Job 會在 log 清楚說明缺哪個檔、該放哪裡，並以 failed 結束。

## 5. 還沒做、值得接著做

- 光譜迴歸頭目前是 Ridge；資料量大時可改 MLP 頭或端到端微調。
- PatchCore 的 coreset 目前是隨機抽樣，記憶庫很大時可換 greedy k-center。
- Wafer map 專用模型（直接吃 bin map 矩陣）、FDC 的 TCN / Transformer。
- 主動學習：把 `retrieve` 找出的「最不像」樣本送去人工標註，再 `extend` 進原型庫。
- 推論結果回寫到 MES / 報表系統的接口（目前是 CSV / JSONL 下載）。
