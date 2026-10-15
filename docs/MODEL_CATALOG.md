# 模型目錄與選型 SOP

三個用途：
1. 使用者 SOP 的底稿：API `GET /catalog` 把 §2、§3、§8 以結構化方式提供給前端的新建訓練精靈與 SOP 面板。
2. AutoML 候選來源：§5 的矩陣決定 `mode=auto` 時試哪些模型。
3. 程式對照：`backend/app/catalog/model_catalog.yaml` 與 `trainer/trainer/models/registry.py` 的 family id 必須與本文件一致（CI 比對）。

## 1. 資料類型

| data_type | 白話 | 典型例子 |
|---|---|---|
| `TABULAR` | 表格：每列一筆、每欄一個特徵 | 製程參數 → 良率、客戶資料 → 流失 |
| `IMAGE` | 圖片 | 外觀瑕疵、物件計數、區域分割 |
| `SEQUENCE` | 隨時間變化的曲線 / 訊號 | 感測器時序、設備振動、圖表資料 |
| `TEXT` | 文字 | 客訴分類、情緒、工單歸類 |
| `SPECTRUM` | 光譜 / 頻譜（一筆樣本 = 一條曲線） | 拉曼、紅外、聲學頻譜 |

## 2. 資料格式要求（上傳前檢查）

| data_type | 接受格式 | `spec` 必填 | 備註 |
|---|---|---|---|
| TABULAR | `csv`、`parquet` | `target`（目標欄）、可選 `features`、`categorical` | 表頭必填；缺值允許（自動補值）；≥ 100 列 |
| IMAGE classification | `image_folder`（zip：`train/<class>/*.jpg`，可選 `val/`）或 `csv`（`path,label`） | `classes`（自動偵測） | jpg / png；建議每類 ≥ 50 張 |
| IMAGE detection | `yolo`（`images/`、`labels/`、`data.yaml`）或 `coco`（`annotations.json`） | `classes` | 標註框 |
| IMAGE segmentation | `yolo`（多邊形標註）或 `coco`（segmentation） | `classes` | |
| SEQUENCE | `csv`（長表：`series_id,t,feature…[,label]`）或 `npy`（`N × T × C`） | `window`、`stride`、可選 `label` | 等間隔取樣；缺值先補 |
| TEXT | `csv` / `jsonl`（`text,label`） | `text_column`、`label_column`、`language` | 建議每類 ≥ 100 筆 |
| SPECTRUM | `spectrum_csv`（寬表：每列一筆樣本，欄 = 波數）或 `npy` | 可選 `label`、`patch_size` | 無標籤可做異常偵測 |

## 3. 任務類型

| task_type | 白話 | 需要標籤 | 主要指標 |
|---|---|---|---|
| `classification` | 預測類別（良 / 不良、A / B / C） | 是 | `f1_macro`、`accuracy`、`auroc`（二元） |
| `regression` | 預測數值 | 是 | `rmse`、`mae`、`r2` |
| `detection` | 找出圖中物件位置與類別 | 是（框） | `map50_95`、`map50` |
| `segmentation` | 標出像素區域 | 是（多邊形 / 遮罩） | `miou`、`mask_map50` |
| `anomaly_detection` | 找出「不正常」的樣本 | 否（只需正常樣本）；有標籤可評估 | `auroc`、`f1@threshold` |

## 4. 模型家族

每個家族在 trainer 實作 `BaseTrainer` 與 `BaseInferencer`；id 為 `<group>.<name>`。

| id | 支援 data_type × task | 白話說明 | 資料量 | 資源 | 產物 |
|---|---|---|---|---|---|
| `tabular.linear` | TABULAR × classification / regression | 線性 / 邏輯迴歸。最簡單、可解釋、訓練秒級；當基準線 | 任意 | CPU | sklearn pipeline（含前處理）`.joblib` |
| `tabular.svm` | TABULAR × classification / regression | 支援向量機。小資料、特徵數多時表現好；> 50k 列會很慢 | ≤ 50k | CPU | `.joblib` |
| `tabular.random_forest` | TABULAR × classification / regression | 隨機森林。穩健、不太需要調參、給特徵重要度 | 任意 | CPU | `.joblib` |
| `tabular.xgboost` | TABULAR × classification / regression | 梯度提升樹。表格資料的預設首選，多數情況最準 | ≥ 1k | CPU（> 500k 列可用 GPU） | `.json` + 前處理 `.joblib` |
| `vision.yolo` | IMAGE × detection / segmentation / classification | Ultralytics YOLO（預設 `yolo11n/s/m`）。即時物件偵測 / 分割的標準做法 | ≥ 200 張 | GPU | `.pt`（+ `.onnx` 匯出） |
| `vision.dino` | IMAGE × classification / anomaly_detection | DINOv2 預訓練特徵 + 線性 / kNN 頭。少量標籤也能分得好；正常樣本的特徵距離可做異常偵測 | ≥ 20 張 / 類 | GPU | backbone 引用 + 頭 `.pt` + 特徵統計 |
| `sequence.patch_autoencoder` | SEQUENCE / SPECTRUM × anomaly_detection / regression（重建）| 把曲線切成 patch 後做自編碼器；重建誤差大 = 異常。也可輸出 embedding 給下游 | ≥ 500 條 | GPU（小資料 CPU 可） | `.pt` + 正規化統計 + 門檻 |
| `text.bert_classifier` | TEXT × classification | 預訓練 BERT（中文預設 `bert-base-chinese`，多語 `xlm-roberta-base`）接分類頭。語意理解 | ≥ 500 筆 | GPU | HF 格式目錄（`safetensors` + tokenizer） |

預留（v2）：`tabular.lightgbm`、`vision.timm_classifier`、`sequence.tcn`、`text.embedding_classifier`。

### 4.1 預設超參數與搜尋空間（Optuna）

| id | 預設 | 搜尋空間 |
|---|---|---|
| `tabular.linear` | `C=1.0`（cls）、`alpha=1.0`（reg，Ridge） | `C / alpha: log 1e-3 … 1e2`；`penalty: l2 / l1`（saga） |
| `tabular.svm` | `kernel=rbf, C=1, gamma=scale` | `C: log 1e-2 … 1e2`；`gamma: log 1e-4 … 1`；`kernel: rbf / linear` |
| `tabular.random_forest` | `n_estimators=300, max_depth=None` | `n_estimators: 100 … 800`；`max_depth: 4 … 32 / None`；`min_samples_leaf: 1 … 10`；`max_features: sqrt / 0.3 … 1.0` |
| `tabular.xgboost` | `n_estimators=500, lr=0.05, max_depth=6, subsample=0.8, colsample=0.8`，early stopping 50 | `lr: log 0.01 … 0.3`；`max_depth: 3 … 10`；`min_child_weight: 1 … 10`；`subsample / colsample: 0.5 … 1`；`reg_lambda: log 1e-3 … 10`；`n_estimators` 由 early stopping 決定 |
| `vision.yolo` | `model=yolo11s, imgsz=640, epochs=100, batch=auto, lr0=0.01` | `model: n / s / m`；`imgsz: 512 / 640 / 800`；`lr0: log 1e-3 … 2e-2`；`epochs: 50 … 150`（pruner 看每 epoch `fitness`） |
| `vision.dino` | `backbone=dinov2_vits14, head=linear, lr=1e-3, epochs=20, freeze_backbone=true` | `backbone: vits14 / vitb14`；`head: linear / knn(k=5…50)`；`lr: log 1e-4 … 1e-2`；anomaly：`k: 1 … 10`、`score: mean / max` |
| `sequence.patch_autoencoder` | `patch_size=16, latent=32, layers=3, lr=1e-3, epochs=50` | `patch_size: 8 / 16 / 32`；`latent: 8 … 128`；`layers: 2 … 4`；`lr: log 1e-4 … 1e-2`；`dropout: 0 … 0.3` |
| `text.bert_classifier` | `model=bert-base-chinese, max_len=256, lr=2e-5, epochs=3, batch=16` | `lr: log 1e-5 … 5e-5`；`epochs: 2 … 5`；`max_len: 128 / 256 / 512`；`warmup_ratio: 0 … 0.1`；`weight_decay: 0 … 0.1` |

共通：`split` 預設 train 80 / val 20（有 `val/` 或 `split` 欄時用使用者的）；分類用 stratified；時序類不洗牌。

## 5. AutoML 候選矩陣（`mode = auto`）

| data_type | task_type | 候選（依序）| 條件 |
|---|---|---|---|
| TABULAR | classification / regression | `tabular.xgboost`、`tabular.random_forest`、`tabular.linear`、`tabular.svm` | `svm` 只在 `row_count ≤ 50k` 加入；`row_count < 1k` 時 `xgboost` 降為第二順位 |
| IMAGE | classification | `vision.dino`、`vision.yolo` | `image_count < 100 / class` 只用 `dino` |
| IMAGE | detection / segmentation | `vision.yolo`（n / s / m 當作搜尋維度） | |
| IMAGE | anomaly_detection | `vision.dino` | |
| SEQUENCE / SPECTRUM | anomaly_detection | `sequence.patch_autoencoder` | |
| SEQUENCE / SPECTRUM | regression | `sequence.patch_autoencoder`（embedding）+ `tabular.xgboost` 頭 | v2 |
| TEXT | classification | `text.bert_classifier`、`tabular.linear`（TF-IDF 基準線） | `row_count < 300` 只用 TF-IDF 基準線 |

預算預設：`max_trials = 20`、`time_budget_minutes = 60`（深度學習家族 `max_trials = 8`、`120` 分鐘）；metric 依 §3 第一個指標；`direction` 由 catalog 標示。

## 6. AutoML 流程

1. backend 依矩陣與 Job 輸入的 `spec`（`jobs.input.spec`，含 `row_count` / `image_count`）展開候選，寫入 `jobs.config.search`。
2. trainer：Optuna `TPESampler(seed)` + `MedianPruner(n_startup_trials=3)`；每個 trial 先抽 family，再抽該家族的空間。
3. 每個 trial 回報 leaderboard row：`{trial, family, params, metrics, duration_s, status}`。
4. 時間 / 次數到 → 取最佳 trial，以完整訓練集重訓並匯出產物；`metadata.automl = {best_trial, params, leaderboard_ref}`。
5. 前端在 job 詳情顯示 leaderboard（表 + 指標柱狀圖，顏色 `chart-1`），並提供「用此設定建立手動 job」捷徑。

## 7. 選最佳與門檻

- 分類：先看 `f1_macro`（不平衡資料更可靠），再看 `accuracy`；二元同時給 `auroc` 與預設門檻 0.5（anomaly 由驗證集的 F1 最大化決定門檻並存在產物）。
- 迴歸：`rmse` 最小；報告 `mae`、`r2`。
- 偵測 / 分割：`map50_95` 最大。
- 所有報告都附：混淆矩陣（分類）、殘差圖（迴歸）、PR 曲線（偵測）、重建誤差分布（異常）。

## 8. SOP 決策樹（給不懂程式的使用者；前端 SOP 面板內容）

1. **你的資料長什麼樣？**
   - Excel / CSV 表格 → `TABULAR`
   - 圖片 → `IMAGE`
   - 隨時間變化的曲線、感測器紀錄 → `SEQUENCE`
   - 光譜、頻譜（一筆樣本一條曲線）→ `SPECTRUM`
   - 文字、句子、工單內容 → `TEXT`
2. **你想得到什麼答案？**
   - 分類別（良 / 不良、A / B / C）→ `classification`
   - 一個數值（厚度、壽命、良率）→ `regression`
   - 圖裡「東西在哪」→ `detection`
   - 圖裡「哪些像素是什麼」→ `segmentation`
   - 「有沒有怪怪的」且多半只有正常樣本 → `anomaly_detection`
3. **你的資料有多少？有沒有標籤？**
   - 沒有標籤 → 只能做 `anomaly_detection`（或先去標註）。
   - 很少（表格 < 1k 列、每類圖片 < 100 張、文字 < 300 筆）→ 選「自動模式」，系統會偏向小資料友善的模型（線性、隨機森林、DINO、TF-IDF）。
   - 足夠 → 選「自動模式」跑一輪，拿 leaderboard 第一名再做手動微調。
4. **第一次就選「自動模式（AutoML）」**：預設預算 60 分鐘；結果頁會告訴你哪個模型最好、指標多少、下一步建議。
5. **看指標怎麼讀**：分類看 `f1_macro`（越接近 1 越好，> 0.8 通常可用）；迴歸看 `rmse`（越小越好，要跟目標數值的範圍比）；偵測看 `map50`（> 0.5 可試用）；異常看 `auroc`（> 0.9 才算可靠）。
6. **結果不好怎麼辦**：先檢查資料（標籤是否錯、類別是否極端不平衡、圖片是否太小）、增加資料量、再試手動模式調整搜尋空間或 epochs。
7. **要用模型**：到「模型」頁把最好的設為預設 → 「推論」頁上傳新資料 → 下載結果。

## 9. `model_catalog.yaml` 結構

```yaml
version: 1
data_types:
  TABULAR: { label: 表格, formats: [csv, parquet], icon: Table2 }
  # ...
tasks:
  classification: { label: 分類, metrics: [f1_macro, accuracy, auroc], direction: maximize }
  # ...
families:
  tabular.xgboost:
    label: XGBoost
    group: tabular
    supports: { TABULAR: [classification, regression] }
    resources: { gpu: optional, cpu_min: 1, memory_mb_min: 2048 }
    min_rows: 1000
    defaults: { n_estimators: 500, learning_rate: 0.05, max_depth: 6, subsample: 0.8, colsample_bytree: 0.8 }
    search_space:
      learning_rate: { type: float, low: 0.01, high: 0.3, log: true }
      max_depth: { type: int, low: 3, high: 10 }
      # ...
    sop: "梯度提升樹。表格資料的預設首選……"
automl:
  - { data_type: TABULAR, task: classification, candidates: [tabular.xgboost, tabular.random_forest, tabular.linear, tabular.svm],
      rules: [{ if: "row_count > 50000", drop: [tabular.svm] }, { if: "row_count < 1000", prefer: [tabular.random_forest] }],
      budget: { max_trials: 20, time_budget_minutes: 60 } }
  # ...
```
