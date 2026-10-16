# 模型目錄與選型 SOP

三個用途：
1. 使用者 SOP 的底稿：API `GET /api/v1/catalog` 把 §1–§5、§8 以結構化方式提供給前端的新建訓練精靈與 SOP 面板。
2. AutoML 候選來源：§5 的矩陣決定 `mode=auto` 時試哪些模型。
3. 程式對照：`backend/app/catalog/model_catalog.yaml`（唯一真相）與 `trainer/trainer/models/registry.py` 的 family id 必須一致（`backend/tests/test_catalog.py`、`trainer/tests/test_registry.py` 比對）。

半導體 / 電子製造的情境對照（哪種機台資料用哪個模型、推論時要做什麼）在 `docs/USE_CASES.md`。

## 1. 資料類型

| data_type | 白話 | 典型例子 |
|---|---|---|
| `TABULAR` | 表格：每列一筆、每欄一個特徵 | WAT / PCM 參數 → 良率、FDC 摘要 → 量測值 |
| `IMAGE` | 圖片 | TEM / SEM 表面、AOI 外觀、wafer map |
| `SEQUENCE` | 隨時間變化的曲線 / 訊號 | FDC trace、設備振動 |
| `TEXT` | 文字 | 設備 log、工單、客訴 |
| `SPECTRUM` | 光譜 / 頻譜（一筆樣本 = 一條曲線） | OCD、橢圓偏光、FTIR、Raman |

## 2. 資料格式要求（上傳前檢查）

| data_type | 接受格式 | `spec` | 備註 |
|---|---|---|---|
| TABULAR | `csv`、`parquet` | `target`（目標欄，訓練必填）、可選 `features`、`categorical`、`drop_columns`、`id_column` | 表頭必填；缺值自動補（數值中位數、類別眾數）；類別欄自動 one-hot |
| IMAGE classification | zip：`<class>/*.jpg`（可再分 `train/` `val/`）| 自動偵測 `classes`、`image_count` | jpg / png / bmp / tif；few-shot 每類 ≥ 3 張，YOLO 分類每類 ≥ 50 張 |
| IMAGE detection / segmentation | zip：YOLO 格式（`images/`、`labels/`、`data.yaml`） | | 分割用多邊形標註 |
| IMAGE anomaly_detection | zip：`good/`（或 `normal/`、`ok/`）為正常；其他資料夾視為異常（只用於評估） | | 沒有子資料夾時整包視為正常 |
| SEQUENCE | `csv` 長表 `series_id,t,feature…[,label]` 或 `npy`（`N × T × C`） | `window`、`stride`、`series_id`、`time`、可選 `label` | 等間隔取樣 |
| TEXT | `csv` / `jsonl`（`text,label`） | `text_column`、`label_column` | 建議每類 ≥ 100 筆 |
| SPECTRUM | `spectrum_csv` 寬表（每列一筆樣本，欄 = 波長）或 `npy`（`N × T`） | 可選 `label`（異常標籤或迴歸目標） | 長度不同的光譜在推論時自動重取樣到訓練長度 |
| 推論直接輸入 | `inline` JSON rows（表格 / 文字：欄位 = 特徵；序列 / 光譜：`{"id": …, "values": [...]}`） | | 小量即時推論用 |

zip 會在 Job 的工作目錄解壓，上傳檔本身在 Job 結束時刪除（不留存政策）。

## 3. 任務類型

| task_type | 白話 | 需要標籤 | 主要指標（第一個為 AutoML 目標） |
|---|---|---|---|
| `classification` | 預測類別（良 / 不良、bin code） | 是 | `f1_macro`、`accuracy`、`auroc`（二元） |
| `regression` | 預測數值（CD、膜厚、良率） | 是 | `rmse`、`mae`、`r2` |
| `detection` | 找出圖中物件位置與類別 | 是（框） | `map50_95`、`map50` |
| `segmentation` | 標出像素區域 | 是（多邊形） | `mask_map50_95`、`mask_map50` |
| `anomaly_detection` | 找出「不正常」的樣本 | 否（只需正常樣本）；有標籤可算 `auroc` | `auroc`、`f1`（門檻 = 正常樣本分數的 P99） |

## 4. 模型家族與推論模式

每個家族在 trainer 實作 `BaseTrainer`（`fit / evaluate / finalize / export`）與 `BaseInferencer`（`load / predict`）。
推論模式：`predict`（類別 / 數值）、`score`（異常分數 + 門檻判定）、`compare`（整批影像對黃金基準的機台比對報告）、`embed`（向量）、`retrieve`（對參考庫找最相似 / 最不相似）、
`detect` / `segment`（框 / 遮罩）、`measure`（遮罩幾何量）、`extend`（免重訓新增類別）。

| id | 支援 | 推論模式 | 白話 | 資源 | 預訓練權重 | 產物 |
|---|---|---|---|---|---|---|
| `tabular.linear` | TABULAR × cls / reg；TEXT × cls（TF-IDF） | predict | 線性 / 邏輯迴歸，可解釋基準線 | CPU | 無 | `model/model.joblib` + `report/feature_importance.json` |
| `tabular.svm` | TABULAR × cls / reg | predict | SVM，小資料、特徵多時好；≤ 50k 列 | CPU | 無 | `.joblib` |
| `tabular.random_forest` | TABULAR × cls / reg | predict | 穩健、免調參、特徵重要度 | CPU | 無 | `.joblib` + 重要度 |
| `tabular.xgboost` | TABULAR × cls / reg | predict | 表格預設首選 | CPU（可 GPU） | 無 | `.joblib` + 重要度 |
| `tabular.isolation_forest` | TABULAR × anomaly | score | 多參數離群 | CPU | 無 | `.joblib`（含門檻） |
| `vision.yolo` | IMAGE × detection / segmentation / classification | detect / segment / measure / predict | Ultralytics YOLO11，微調或從頭 | GPU | `yolo11n/s/m[-seg|-cls].pt` | `model/best.pt` + `report/training_curve.csv` |
| `vision.dino_fewshot` | IMAGE × classification | predict / embed / retrieve / extend | 凍結 DINOv2 + 原型庫；新類別免重訓 | GPU | `dinov2-small/`、`dinov2-base/` | `model/prototypes.npz` |
| `vision.dino_patchcore` | IMAGE × anomaly | score（熱圖）/ embed | 正常影像 patch 記憶庫 | GPU | `dinov2-small/` | `model/memory_bank.npz` |
| `vision.image_quality` | IMAGE × anomaly | compare / score / embed | 17 個無參考影像品質指標的黃金機台基準與浮動範圍；compare 產出機台比對報告 | CPU | 無 | `model/baseline.json` + `report/baseline_ranges.csv` |
| `sequence.patch_autoencoder` | SEQUENCE / SPECTRUM × anomaly | score / embed / retrieve | patch 嵌入 + 位置編碼 + 視窗 latent | CPU / GPU | 無 | `model/model.pt` + `reference.npz` |
| `spectrum.masked_autoencoder` | SPECTRUM × anomaly / regression | score / embed / retrieve / predict | 遮蔽重建的光譜鑑別器；可接迴歸頭 | CPU / GPU | 無 | `model/model.pt` + `reference.npz` + `head.joblib` |
| `text.bert_classifier` | TEXT × classification | predict / embed | 預訓練 BERT 微調 | GPU | `bert-base-chinese/`、`xlm-roberta-base/` | `model/bert/`（HF 格式） |

### 4.1 預設超參數與搜尋空間（Optuna）

| id | 預設 | 搜尋空間 |
|---|---|---|
| `tabular.linear` | `C=1.0`（cls，LogisticRegression）、`alpha=1.0`（reg，Ridge） | `C: log 1e-3 … 1e2` |
| `tabular.svm` | `C=1, kernel=rbf, gamma=scale` | `C: log 1e-2 … 1e2`；`gamma: log 1e-4 … 1`；`kernel: rbf / linear` |
| `tabular.random_forest` | `n_estimators=300, max_depth=None, min_samples_leaf=1` | `n_estimators: 100 … 800`；`max_depth: 4 … 32`；`min_samples_leaf: 1 … 10` |
| `tabular.xgboost` | `n_estimators=500, learning_rate=0.05, max_depth=6, subsample=0.8, colsample_bytree=0.8` | `learning_rate: log 0.01 … 0.3`；`max_depth: 3 … 10`；`min_child_weight: 1 … 10`；`subsample / colsample_bytree: 0.5 … 1`；`reg_lambda: log 1e-3 … 10` |
| `tabular.isolation_forest` | `n_estimators=200, contamination=auto` | `n_estimators: 100 … 500`；`max_samples: 0.2 … 1.0` |
| `vision.yolo` | `model=yolo11s, imgsz=640, epochs=100, lr0=0.01, batch=-1, pretrained=true` | `model: yolo11n / s / m`；`imgsz: 512 / 640 / 800`；`lr0: log 1e-3 … 2e-2`；`epochs: 50 … 150` |
| `vision.dino_fewshot` | `backbone=dinov2-small, k=5, metric=cosine` | `backbone: dinov2-small / dinov2-base`；`k: 1 … 20` |
| `vision.dino_patchcore` | `backbone=dinov2-small, coreset_ratio=0.1, k=3` | `coreset_ratio: 0.02 … 0.3`；`k: 1 … 9` |
| `vision.image_quality` | `z_threshold=3.0, distance_percentile=99` | （無；compare 的 `effect_warn / effect_fail / alpha` 在推論 config 指定） |
| `sequence.patch_autoencoder` | `patch_size=16, latent=32, layers=3, lr=1e-3, epochs=50` | `patch_size: 8 / 16 / 32`；`latent: 8 … 128`；`layers: 2 … 4`；`lr: log 1e-4 … 1e-2` |
| `spectrum.masked_autoencoder` | `patch_size=16, mask_ratio=0.5, dim=64, depth=4, heads=4, lr=5e-4, epochs=100` | `patch_size: 8 / 16 / 32`；`mask_ratio: 0.3 … 0.75`；`dim: 32 / 64 / 128`；`depth: 2 … 6`；`lr: log 1e-4 … 5e-3` |
| `text.bert_classifier` | `model=bert-base-chinese, max_len=256, lr=2e-5, epochs=3, batch=16` | `lr: log 1e-5 … 5e-5`；`epochs: 2 … 5`；`max_len: 128 / 256 / 512` |

共通：驗證集 = 20% 分層切分（分類）或隨機；異常偵測只用正常樣本訓練、異常樣本進驗證集；手動 Job 的 `config` 會覆蓋預設；
AutoML 的 `config` 其他鍵（`search` 以外）同樣會覆蓋每個 trial 抽到的參數（例如固定 `epochs`）。

### 4.2 資料前處理（`input.spec.preprocess`）

共用套件 `libs/preprocess`（`qrlab_preprocess`）：使用者在上傳後挑步驟與參數，`POST /projects/{slug}/uploads/{id}/preview` 抽樣套用回傳前後對照；
步驟放在任務的 `input.spec.preprocess = [{op, params}]`。訓練時 fitted 步驟（補值數字、標準化統計、MSC 參考曲線、對位參考影像…）在訓練資料上學習並存進模型（`model/preprocess.json` 與產物 metadata）；推論自動沿用，不得再指定。
`GET /catalog/preprocess?data_type=` 列出每個步驟的參數規格。偵測 / 分割任務拒絕會改變座標的影像步驟。

| data_type | 步驟 |
|---|---|
| TABULAR | `tabular.impute`、`drop_missing`、`clip_outliers`、`standardize`、`minmax`、`log`、`to_numeric`、`filter_rows`、`drop_columns`、`keep_columns`、`drop_duplicates` |
| IMAGE | `image.resize`、`grayscale`、`crop`、`center_crop`、`autocontrast`、`equalize`、`gamma`、`stretch`、`denoise`、`sharpen`、`invert`、`flip`、`rotate`、`align` |
| SEQUENCE / SPECTRUM | `sequence.resample`、`crop`、`fill_nan`、`savgol`、`moving_average`、`derivative`、`baseline_poly`、`baseline_rolling_min`、`detrend`、`snv`、`minmax_sample`、`msc`、`standardize`、`clip` |
| TEXT | `text.lowercase`、`strip_whitespace`、`remove_punctuation`、`remove_urls`、`remove_numbers`、`truncate`、`replace_regex`、`drop_empty`、`dedupe` |

## 5. AutoML 候選矩陣（`mode = auto`）

| data_type | task_type | 候選（依序） | 條件 | 預算 |
|---|---|---|---|---|
| TABULAR | classification / regression | `tabular.xgboost`、`tabular.random_forest`、`tabular.linear`、`tabular.svm` | `row_count > 50000` 剔除 svm；`row_count < 1000` 優先 random_forest | 20 trials / 60 min |
| TABULAR | anomaly_detection | `tabular.isolation_forest` | | 10 / 20 |
| IMAGE | classification | `vision.dino_fewshot`、`vision.yolo` | `row_count < 100` 剔除 yolo | 8 / 120 |
| IMAGE | detection / segmentation | `vision.yolo` | | 8 / 120 |
| IMAGE | anomaly_detection | `vision.dino_patchcore`、`vision.image_quality` | 沒申請 GPU 時只剩 image_quality | 6 / 60 |
| SEQUENCE | anomaly_detection | `sequence.patch_autoencoder` | | 10 / 60 |
| SPECTRUM | anomaly_detection | `spectrum.masked_autoencoder`、`sequence.patch_autoencoder` | | 10 / 60 |
| SPECTRUM | regression | `spectrum.masked_autoencoder` | | 10 / 60 |
| TEXT | classification | `text.bert_classifier`、`tabular.linear`（TF-IDF） | `row_count < 300` 剔除 bert | 8 / 120 |

Job 沒申請 GPU 時，需要 GPU 的候選會被拿掉（全部都需要 → 400 `GPU_REQUIRED`）。

## 6. AutoML 流程（trainer 實作）

1. backend 展開候選寫入 `jobs.config.search = {candidates, metric, direction, max_trials, time_budget_minutes}`；spec 同時帶每個候選的 `defaults` / `search_space`。
2. trainer：Optuna `TPESampler(seed=42)` + `MedianPruner(n_startup_trials=3)`，ask / tell 介面；每個 trial 先抽 `family`，再抽 `family.參數`。
3. 深度學習家族每個 epoch 回報指標給 pruner（`ctx.epoch`），被剪掉的 trial 記為 pruned。
4. 每個完成的 trial 回報 leaderboard row `{trial, family, params, metric, metrics, seconds}` → `jobs.metrics.leaderboard`（依指標排序）。
5. 時間預算（取 `time_budget_minutes` 與 Job timeout 85% 的較小者）或 trial 數到 → 最佳 trainer `finalize`（表格家族以全部資料重訓）→ 匯出產物；`jobs.model_family` 回填最佳家族，`metrics/metrics.json` 含 leaderboard。

## 7. 選最佳與門檻

- 分類：`f1_macro`（不平衡資料更可靠）；二元另給 `auroc`。
- 迴歸：`rmse` 最小；報告 `mae`、`r2`。
- 偵測 / 分割：`map50_95` / `mask_map50_95`。
- 異常：`auroc`（有標籤時）；門檻 = 正常訓練樣本分數的 P99，存在模型 metadata，推論可用 `config.threshold` 覆寫。

## 8. SOP 決策樹（給不懂程式的使用者；前端 SOP 面板內容）

1. **你的資料長什麼樣？** 表格 → `TABULAR`；圖片 → `IMAGE`；感測器曲線 → `SEQUENCE`；光譜 → `SPECTRUM`；文字 → `TEXT`。
2. **你想得到什麼答案？** 類別 → `classification`；數值 → `regression`；圖裡東西在哪 → `detection`；哪些像素 → `segmentation`；有沒有怪怪的（多半只有正常樣本）→ `anomaly_detection`。
3. **推論時要做什麼？** 看 §4 的推論模式；例如光譜要「找最像的黃金樣本」就是 `retrieve`，影像類別會一直增加就選 `vision.dino_fewshot`（之後用 `extend` 加類別）。
4. **資料有多少？有沒有標籤？** 沒標籤 → 只能做異常偵測；很少 → 自動模式會偏向小資料友善的模型（線性、隨機森林、DINO few-shot、TF-IDF）。
5. **第一次就選自動模式**：看 leaderboard 第一名的家族與指標，再用「手動模式」微調。
6. **看指標怎麼讀**：`f1_macro > 0.8` 通常可用；`rmse` 要跟目標範圍比；`map50 > 0.5` 可試用；`auroc > 0.9` 才算可靠。
7. **結果不好**：先檢查資料（標籤錯、類別極端不平衡、圖片太小、光譜長度不一致）、增加資料、再調搜尋空間或 epochs。
8. **要用模型**：到「模型」頁設預設 → 建立推論 Job（選模式、上傳 / 選資料來源 / 直接輸入）→ 下載 `predictions.csv`。

## 9. 預訓練權重（模型庫）

- `families.*.weights` 列出需要的檔案（`id`、`file`、`source`、`license`、`sha256`、`kind: file | hf_repo`）。
- 伺服器不連外、trainer 不下載：管理員在 **管理 → 模型庫**（`/admin/model-zoo`）把權重帶進 `MODEL_ZOO_ROOT`，三種方式：瀏覽器上傳（單檔或 HF snapshot 的 zip）、伺服器路徑（`MODEL_ZOO_IMPORT_ROOT`）、內網 URL（`MODEL_ZOO_ALLOWED_HOSTS`）；匯入時比對 `sha256`、寫 `manifest.json` 與稽核紀錄。有網路的機器也可先用 `scripts/fetch_model_zoo.py --dest <資料夾>` 整批抓好再放到傳輸資料夾。
  Job 子程序以 `MODEL_ZOO_ROOT` 直接讀取，runner 設定 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`YOLO_OFFLINE=1`。
- `GET /api/v1/admin/model-zoo`、`.venv/bin/python -m app.cli model-zoo [--verify]` 顯示每個權重是否存在；`GET /api/v1/catalog` 的 `weights_ready` 讓精靈標示缺權重的家族，建立任務時缺權重會被拒絕（`WEIGHTS_MISSING`）。
- 新增需要權重的家族：先在 yaml 的 `weights` 登記，再實作 trainer（透過 `ctx.weight(id)` 取路徑，絕不自行下載）。

## 10. `model_catalog.yaml` 結構（version 2）

```yaml
version: 2
data_types:
  TABULAR: { label: 表格, formats: [csv, parquet] }
tasks:
  classification: { label: 分類, metrics: [f1_macro, accuracy, auroc], direction: maximize, needs_labels: true }
families:
  spectrum.masked_autoencoder:
    label: 光譜 Masked Autoencoder
    group: spectrum
    framework: torch
    supports: { SPECTRUM: [anomaly_detection, regression] }
    inference_modes: [score, embed, retrieve, predict]
    resources: { gpu: optional, cpu_min: 2, memory_mb_min: 4096 }
    min_rows: 500
    defaults: { patch_size: 16, mask_ratio: 0.5, dim: 64, depth: 4, heads: 4, lr: 0.0005, epochs: 100 }
    search_space:
      mask_ratio: { type: float, low: 0.3, high: 0.75 }
      dim: { type: categorical, choices: [32, 64, 128] }
    weights: []            # 或 [{ id, file, source, license, sha256, kind }]
    sop: 把光譜切 patch 隨機遮蔽再重建……
automl:
  - data_type: SPECTRUM
    tasks: [anomaly_detection]
    candidates: [spectrum.masked_autoencoder, sequence.patch_autoencoder]
    budget: { max_trials: 10, time_budget_minutes: 60 }
```
