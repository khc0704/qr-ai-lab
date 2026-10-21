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

資料類型 × 任務的組合由目錄決定：只有至少一個家族 `supports` 的組合才能申請專案（`POST /projects` 與修改申請對其他組合回 400 `TASK_NOT_SUPPORTED`，申請表單的任務下拉只列出可做的）。目前：

| data_type | 可申請的任務 |
|---|---|
| TABULAR | classification、regression、anomaly_detection |
| IMAGE | classification、detection、segmentation、anomaly_detection |
| SEQUENCE | anomaly_detection |
| TEXT | classification、anomaly_detection |
| SPECTRUM | classification、regression、anomaly_detection |

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
| `tabular.catboost` | TABULAR × cls / reg | predict | 梯度提升樹的第二個強基準（有序提升，小資料與類別欄較穩） | CPU（可 GPU） | 無 | `.joblib` + 重要度 |
| `tabular.tabpfn` | TABULAR × cls / reg | predict | TabPFN v2.5 表格基礎模型：免訓練、免調參，把訓練列放進上下文直接預測；幾十到幾千列最準，≤ 5 萬列 | CPU（GPU 快很多） | `tabpfn-v2.5-classifier-v2.5_default.ckpt`、`tabpfn-v2.5-regressor-v2.5_default.ckpt` | `.joblib` |
| `tabular.isolation_forest` | TABULAR × anomaly | score | 多參數離群 | CPU | 無 | `.joblib`（含門檻） |
| `vision.yolo` | IMAGE × detection / segmentation / classification | detect / segment / measure / predict | Ultralytics YOLOv8（ultralytics 8.1），微調或從頭；`freeze=auto` 影像少時凍結骨幹 | GPU | `yolov8n/s/m[-seg|-cls].pt`（Hugging Face `Ultralytics/YOLOv8`） | `model/best.pt` + `report/training_curve.csv` |
| `vision.dino` | IMAGE × classification | predict / embed / retrieve / extend | 一條流程：`finetune`（none 凍結 / lora / full）→ 骨幹的 patch 特徵（`layers` last / cross）→ 分類頭（auto / prototype / knn / linear / svm）；有正常資料夾時可開 PatchCore 兩階段（先判異常、再分缺陷類別）；新類別免重訓；predict / retrieve 附疊圖（原型相似度或線性頭的 CAM） | GPU | `dinov2-small/`、`dinov2-base/`、`dinov3-vits16/`、`dinov3-vitb16/` | `model/prototypes.npz` + `head.joblib`（+ `lora.pt` 或 `backbone/`）+ `output/attention/*.png` |
| `vision.dino_patchcore` | IMAGE × anomaly | score（熱圖）/ embed | 正常影像 patch 記憶庫（PatchCore）；`layers` cross / last、`score_agg` max / top1、`coreset_ratio` / `bank_augment` 自動 | GPU | `dinov2-small/`、`dinov3-vits16/` | `model/memory_bank.npz` |
| `vision.image_quality` | IMAGE × anomaly | compare / score / embed | 17 個無參考影像品質指標的黃金機台基準與浮動範圍；compare 產出機台比對報告 + 逐面向的調整建議；有 `golden/` 參考資料夾時逐張算全參考指標（PSNR / SSIM / MS-SSIM / GMSD）；每張影像附「偏離基準最多的區塊」疊圖 | CPU | 無 | `model/baseline.json` + `report/baseline_ranges.csv`；`output/maps/*.png`、`paired.csv` |
| `sequence.patch_autoencoder` | SEQUENCE / SPECTRUM × anomaly | score / embed / retrieve | patch 嵌入 + 位置編碼 + 視窗 latent；score 回每個 patch 的分數與最偏離的區段；`score_method=patch_bank` 改用正常 patch 庫最近鄰 | CPU / GPU | 無 | `model/model.pt` + `reference.npz` |
| `spectrum.masked_autoencoder` | SPECTRUM × anomaly / regression | score / embed / retrieve / predict | 遮蔽重建的光譜鑑別器；embedding 可選 `embed_layers`（last / all）與 `embed_pool`（mean / meanmax）；score 回每個 patch 的分數與最偏離的波段；可接迴歸頭 | CPU / GPU | 無 | `model/model.pt` + `reference.npz` + `head.joblib` |
| `spectrum.pls` | SPECTRUM × regression / classification | predict / embed | 化學計量學標準做法：PLS 迴歸（光譜 → CD / 膜厚 / 濃度）與 PLS-DA（PLS 分數 + 邏輯迴歸）；秒級、幾十筆就能用；`report/vip.csv` 說哪些波長重要 | CPU | 無 | `model/model.joblib` + `report/vip.csv` |
| `text.bert_classifier` | TEXT × classification | predict / embed | 預訓練 BERT 微調 | GPU | `bert-base-chinese/`、`xlm-roberta-base/` | `model/bert/`（HF 格式） |
| `text.qwen_embedding` | TEXT × classification / anomaly | predict / retrieve / embed / score | 凍結 Qwen3-Embedding-0.6B（多語）：向量 + 邏輯迴歸分類、找最相似 / 最不相似的歷史紀錄、novelty 分數找新型問題；`pool` last_token / mean；產物只有參考庫與分類頭，骨幹推論時再從模型庫載入 | CPU（GPU 快很多） | `qwen3-embedding-0.6b/` | `model/reference.npz` + `head.joblib` |

### 4.1 預設超參數與搜尋空間（Optuna）

| id | 預設 | 搜尋空間 |
|---|---|---|
| `tabular.linear` | `C=1.0`（cls，LogisticRegression）、`alpha=1.0`（reg，Ridge） | `C: log 1e-3 … 1e2` |
| `tabular.svm` | `C=1, kernel=rbf, gamma=scale` | `C: log 1e-2 … 1e2`；`gamma: log 1e-4 … 1`；`kernel: rbf / linear` |
| `tabular.random_forest` | `n_estimators=300, max_depth=None, min_samples_leaf=1` | `n_estimators: 100 … 800`；`max_depth: 4 … 32`；`min_samples_leaf: 1 … 10` |
| `tabular.xgboost` | `n_estimators=500, learning_rate=0.05, max_depth=6, subsample=0.8, colsample_bytree=0.8` | `learning_rate: log 0.01 … 0.3`；`max_depth: 3 … 10`；`min_child_weight: 1 … 10`；`subsample / colsample_bytree: 0.5 … 1`；`reg_lambda: log 1e-3 … 10` |
| `tabular.catboost` | `iterations=500, learning_rate=0.05, depth=6, l2_leaf_reg=3` | `iterations: 200 … 1000`；`learning_rate: log 0.01 … 0.3`；`depth: 4 … 10`；`l2_leaf_reg: log 1 … 10`。共用 GPU 時自動改 CPU（CatBoost 的 GPU 配置不受 torch 的記憶體比例限制） |
| `tabular.tabpfn` | `n_estimators=auto` | `n_estimators: 1 / 4 / 8`（上下文集成數；越多越準越慢）。`ignore_pretraining_limits=true` 可超過預訓練上限（不建議） |
| `tabular.isolation_forest` | `n_estimators=200, contamination=auto` | `n_estimators: 100 … 500`；`max_samples: 0.2 … 1.0` |
| `vision.yolo` | `model=yolov8s, imgsz=640, epochs=100, lr0=0.01, batch=-1, pretrained=true, freeze=auto, augment=[hflip, crop, brightness]` | `model: yolov8n / s / m`；`imgsz: 512 / 640 / 800`；`lr0: log 1e-3 … 2e-2`；`epochs: 50 … 150`；`freeze: auto / 0 / 10`（auto：影像少於 200 張凍結前 10 層 = 骨幹）；`augment: default / none`（自動模式各試「預設增強」與「完全不增強」；全部不勾時連 ultralytics 內建的 mosaic / mixup / 色相 / 飽和 / RandAugment / 隨機擦除也關）。`augment` 自選：`hflip / vflip / rotate90 / crop / brightness` |
| `vision.dino` | `backbone=dinov2-small, finetune=none, image_size=224, layers=cross, head=auto, k=auto, patchcore=auto, normal_class="", neighborhood=1, score_agg=auto, coreset_ratio=auto, bank_augment=auto, epochs=auto, batch=auto, lr=1e-3, rank=8, lora_alpha=16, backbone_lr=1e-5, augment=[crop, hflip]` | `backbone: dinov2-small / dinov2-base / dinov3-vits16 / dinov3-vitb16`；`finetune: none / lora`（full 只在手動）；`layers: last / cross`；`head: prototype / knn / linear / svm`；`image_size: 224 / 336`；`augment: default / none`；`lr: log 1e-4 … 1e-2`；`rank: 4 / 8 / 16`（見 §4.1b；`auto` 的規則也在那裡）。`vision.dino_fewshot` / `vision.dino_finetune` 是併入前的舊 id（目錄標 `deprecated`，只能推論舊產物） |
| `vision.dino_patchcore` | `backbone=dinov2-small, image_size=224, layers=cross, neighborhood=1, score_agg=auto, coreset_ratio=auto, bank_augment=auto, k=3` | `backbone: dinov2-small / dinov3-vits16`；`layers: last / cross`；`image_size: 224 / 336 / 448`；`neighborhood: 1 / 3`；`k: 1 … 9`（最近鄰數） |
| `vision.image_quality` | `z_threshold=3.0, distance_percentile=99` | （無；推論 config：compare 的 `effect_warn / effect_fail / alpha`、全參考的 `paired`（預設自動）/ `reference_folder` / `ssim_warn=0.9` / `ssim_fail=0.7`、疊圖的 `maps=true` / `tiles=8`） |
| `sequence.patch_autoencoder` | `patch_size=16, latent=32, layers=3, lr=1e-3, epochs=50, score_method=recon, coreset_ratio=0.1, bank_k=3` | `patch_size: 8 / 16 / 32`；`latent: 8 … 128`；`layers: 2 … 4`；`lr: log 1e-4 … 1e-2`；`score_method: recon / patch_bank`（patch_bank = 正常視窗的 patch token 建記憶庫，分數 = patch 到庫的 k 近鄰距離，視窗分數 = 最大值） |
| `spectrum.masked_autoencoder` | `patch_size=16, mask_ratio=0.5, dim=64, depth=4, heads=4, lr=5e-4, epochs=100, embed_layers=last, embed_pool=mean, score_method=recon, coreset_ratio=0.1, bank_k=3` | `patch_size: 8 / 16 / 32`；`mask_ratio: 0.3 … 0.75`；`dim: 32 / 64 / 128`；`depth: 2 … 6`；`lr: log 1e-4 … 5e-3`；`embed_layers: last / all`（最後一個編碼區塊 / 全部拼接）；`embed_pool: mean / meanmax`；`score_method: recon / patch_bank` |
| `spectrum.pls` | `n_components=10, scale=false` | `n_components: 2 … 30`（自動上限 = 波長數與列數 − 2；`scale=true` 會把每個波長標準化，光譜通常不需要） |
| `text.bert_classifier` | `model=bert-base-chinese, max_len=256, lr=2e-5, epochs=3, batch=16` | `lr: log 1e-5 … 5e-5`；`epochs: 2 … 5`；`max_len: 128 / 256 / 512` |
| `text.qwen_embedding` | `model=qwen3-embedding-0.6b, max_len=512, batch=16, C=1.0, instruction="", pool=last_token` | `C: log 0.01 … 100`（分類頭）；`max_len: 256 / 512 / 1024`；`pool: last_token / mean`（mean 對長 log、條列式工單較穩）。`instruction` 只在 retrieve 的查詢端加上（Qwen3-Embedding 的 `Instruct: …\nQuery: …` 格式），同類文字互比時留空 |

精靈的參數欄位依目錄型別呈現：有選項清單的（`backbone`、`model`、`layers`、`head`、`patchcore`、`score_agg` …；清單 = 前端 `paramChoices` ∪ `search_space` 的 categorical）是下拉選單（選項旁有中文說明，欄位下有一行提示）、布林是 true / false、`augment` 是多選（家族的 `augment_choices`，`defaults.augment` 預先勾好；全部不勾 = 完全不增強）、其餘是文字框（`auto` 也可以直接留著）；留空 = 用預設。只在特定設定下才有意義的欄位會隱藏（`k` 只在 `head=knn`、PatchCore 的欄位只在 `patchcore` 不是 off 時）。建立任務時後端會檢查 `backbone` / `model` 指到的權重真的在模型庫（否則 400 `WEIGHTS_MISSING`，不會等到任務跑起來才失敗）。

共通：驗證集 = 20% 分層切分（分類）或隨機；異常偵測只用正常樣本訓練、異常樣本進驗證集；手動 Job 的 `config` 會覆蓋預設；
AutoML 的 `config` 其他鍵（`search` 以外）同樣會覆蓋每個 trial 抽到的參數（例如固定 `epochs`）。

### 4.1b DINO 家族（`vision.dino`）：微調 → 特徵 → 分類（`jobs.config`）

訓練一個影像模型拆成六步：**前處理**（§4.2）→ **資料增強**（`augment`，只在微調時有意義）→ **骨幹**（精靈在「模式」之前獨立一步：`backbone` 選哪個權重、`finetune` = `none` 凍結、`lora`、`full`）→ **特徵**（從凍結或微調過的骨幹讀）→ **評分 / 分類** → **結果圖**。「模式」步驟說的是下游：手動 = 自己填特徵 / 分類頭 / PatchCore 參數，自動 = 把 `backbone` / `finetune` 固定（`config` 直接帶、不搜尋）、只對 `layers` / `head` / `image_size`（微調時再加 `lr` / `rank` / `augment`，搜尋空間的 `when` 條件）做 Optuna 搜尋。所有參數（實作在 `trainer/trainer/models/dino_features.py` 與 `vision.py`）：

| 參數 | 選項 | 意義與使用時機 |
|---|---|---|
| `finetune` | `none`（預設）/ `lora` / `full` | 要不要先訓練骨幹。`none`：凍結，直接用預訓練特徵（每類幾張就能用、幾分鐘、新類別免重訓）；`lora`：在注意力層的 q / k / v 加低秩轉接器（`rank`、`lora_alpha`）和線性頭一起訓練，基底權重不動、產物多一個幾 MB 的 `lora.pt`（影像和自然影像差很多、每類幾十張以上）；`full`：每個權重都訓練（`backbone_lr` 給預訓練權重、`lr` 給頭），產物包含整個 `backbone/`（每類上百張、VRAM 夠）。微調用類別資料夾當標籤、`epochs=auto`（約 400 步、5 … 40）、`batch=auto`（依解析度）、`augment` 預設 crop + hflip。微調完成後，下面的特徵、分類頭與 PatchCore **都改用微調過的骨幹**，推論與 `extend` 也一樣（轉接器 / 骨幹跟著產物走） |
| 參數 | 選項 | 意義與使用時機 |
|---|---|---|
| `layers` | `cross`（預設）/ `last` / 層數列表（`9,10,11,12`，負數從後數） | 讀哪些 transformer 層的 **patch token**（CLS 一律不用）；每層都套最後的 LayerNorm，patch 平均成一個向量，再把各層沿特徵維度拼接（兩層 (N,384) → (N,768)）。`cross` = 第 9 / 10 / 11 層（12 層的 ViT-S / B；其他深度按比例：ViT-L 18 / 20 / 22），紋理、局部缺陷、PatchCore 都用它；`last` = 只讀最後一層，類別差異是整體長相時夠用、也最省。資料分析報告的「各層特徵代表什麼」會告訴你在你的資料上哪幾層最可分，直接填列表 |
| `image_size` | `224`（預設）/ `336` / `448` | 短邊縮到此尺寸再中央裁切成正方形（HF 的 DINOv2 processor 預設是短邊 256 再裁 224，會切掉邊緣；這裡的 224 不切邊）；patch 數 2.25× / 4×，小瑕疵更清楚、計算也成比例變慢。舊產物沒有 `features` 時沿用 processor 預設 |
| `head`（分類） | `auto`（預設）/ `prototype` / `knn` / `linear` / `svm` | 向量怎麼變類別。`prototype` = 最近原型：每類把支援影像的向量平均成一個「原型」，新影像比 cosine 相似度（每類只有幾張時最穩，confidence = 相似度）；`knn` = 和每張支援影像逐一比再投票（`k`，同一類有多種長相時）；`linear` = 線性分類頭（邏輯迴歸 / 線性探針，每類 10 張以上）；`svm` = 線性 SVM。`auto`：最小類別不到 10 張用 prototype，否則 linear。prototype / knn 會先減去支援集平均再正規化（SimpleShot）。`extend` 加新類別時只在快取特徵上重新 fit 頭，不碰骨幹 |
| `patchcore` / `normal_class`（分類） | `auto`（預設）/ `on` / `off`；資料夾名稱 | 兩階段缺陷分類。`auto` = 資料夾裡有 good / normal / ok / pass（不分大小寫）就啟用，或用 `normal_class` 指定正常資料夾的名字（任何名字都可以）。第一階段：正常影像的 patch 建 PatchCore 記憶庫，影像任何 patch 超過門檻就是異常；第二階段：超過門檻的 patch 以分數加權平均成「缺陷描述子」（再接上整張圖的向量），用同一種 `head` 在缺陷資料夾（scratch、void …）之間分類；沒看過的缺陷在信心不足時回 unknown。`off` = 把正常資料夾當普通類別做純分類（good 其實只是另一種圖樣時）。推論 `config.patchcore=off` 可暫時關閉、`config.threshold` 覆寫門檻 |
| `neighborhood` | `1`（預設）/ `3` | PatchCore 的「locally aware patch features」：每個 patch 和 3×3 鄰域平均後再入庫 / 比對。ViT 的 patch 本來就帶全圖脈絡，所以預設不做；瑕疵明顯比一個 patch 大時用 3 |
| `score_agg` | `auto`（預設）/ `max` / `top1` | 影像異常分數怎麼從 patch 分數彙整：`max` 一個 patch 超標就算異常（PatchCore 原始做法）；`top1` 前 1% patch 的平均（抗單一雜訊 patch；AnomalyDINO 式）。`auto`：每張 ≤ 256 個 patch 用 max，更細的格用 top1 |
| `coreset_ratio` | `auto`（預設）/ 0 … 1 | 記憶庫保留的 patch 比例（隨機抽樣）。`auto` 讓記憶庫不超過 10 萬個 patch；正常影像很少時就是 1.0 |
| `bank_augment` | `auto`（預設）/ `on` / `off` | 正常影像翻轉 / 旋轉後也放進記憶庫（參考集增強）。`auto`：正常影像少於 20 張時開 |
| `k`（PatchCore）| 1 … 9，預設 3 | 每個 patch 取記憶庫最近的 k 個平均距離 |

**自動建議的值都會印進任務 log 並寫到產物 metadata 的 `resolved`**（例如 `head=prototype (smallest class has 4 images (< 10) → prototypes)`、`coreset_ratio=0.21 (480,000 normal patches → keep 21% (bank ≤ 100,000))`），結果頁看得到。

**依任務的實際流程**：

| 資料夾長相 | 任務 | 走法 |
|---|---|---|
| `BIN_A/`、`BIN_B/`…（沒有正常資料夾） | 分類 | 特徵 → `head`；PatchCore 用不上 |
| 只有 `good/`（其他資料夾只拿來評估） | 異常偵測（`vision.dino_patchcore`） | PatchCore；沒有分類頭，出現一個異常 patch 就是異常 |
| `good/` + `scratch/`、`void/`… | 分類 + `patchcore` 開 | PatchCore 判正常 / 異常 → 異常區塊描述子 → `head` 分缺陷類別 |

**結果圖**（`output/attention/<id>.png`，結果頁點開樣本就疊在原圖上）：prototype / knn 畫「每個 patch 與匹配原型 / 鄰居的相似度」；linear / svm 與 LoRA 微調畫 **CAM**（logit = patch 平均 · w，所以每個 patch 的 w · patch 就是它的貢獻，不需要 Grad-CAM）；PatchCore / 兩階段畫 patch 異常分數。

**舊家族**：`vision.dino_fewshot`（= `finetune=none`）與 `vision.dino_finetune`（= `finetune=lora`，當年還有 linear / full）已併入 `vision.dino`；目錄裡標 `deprecated`，精靈不再列出、`POST /jobs` 用它們訓練會回 400 `MODEL_DEPRECATED`，舊產物仍可推論。

**同樣思路的其他家族**：光譜 MAE 的 `embed_layers`（last / all）、`embed_pool`（mean / meanmax）與 `score_method=patch_bank`（一維 PatchCore，對局部波段異常敏感）、Patch AE 的 `score_method`；兩者的 `score` 都回每個 patch 的分數與最偏離的區段（`hot_patch`、`hot_band_start/end` = 視窗內的樣本點範圍，`summary.hot_bands` 統計異常最常落在哪個波段）。Qwen 的 `pool=last_token / mean`。YOLO 的 `freeze=auto`（影像少於 200 張凍結骨幹）。

「資料分析 → 影像品質分析」開啟 DINO embedding（可選 `dinov2-small / dinov2-base / dinov3-vits16 / dinov3-vitb16`）時，報告多兩節：**標籤一致性檢查**（用最後一層與 `cross` 跨層特徵各做一次留一法最近質心，猜每張影像屬於哪個資料夾；兩種都歸到別處 = 疑似放錯）與**各層特徵代表什麼**（每層的群組可分性 — Fisher 比、留一法準確率 — 和主成分最相關的影像品質面向 — 亮度 / 對焦 / 雜訊 / 對比 … 的 Spearman ρ — 附中文解讀，並建議 `layers` 該填哪幾層）。

### 4.1a 推論選項與解釋圖（`jobs.config`）

| 選項 | 適用 | 意義 |
|---|---|---|
| `mode` | 全部 | 推論模式（§4 的清單；不填用模型 `inference_modes` 的第一個） |
| `order` | `retrieve` | 要找的方向：`similar`（只列最相似）/ `dissimilar`（只列最不相似）/ `both`（預設）。結果列 `most_similar[]` / `least_similar[]`，`neighbors[]` = 使用者挑的那一邊；一次性推論頁與精靈在選 retrieve 時會出現這個選項 |
| `k` | `retrieve` | 每筆回傳幾個鄰居（1 … 50，預設 5） |
| `reference` | `retrieve` | `self` = 輸入資料彼此比（不用訓練時的參考庫） |
| `attention` | DINO 家族 | 預設 `true`：`predict` / `retrieve` 每張影像多寫 `output/attention/<id>.png`（結果列 `attention` 欄），prototype / knn 是「每個 patch 與匹配到的原型 / 鄰居的相似度」，線性頭與 LoRA 微調是 CAM，PatchCore 是 patch 異常分數；結果頁點開樣本就會疊在原圖上（紅 = 影響判斷最多；只覆蓋模型實際看到的中央區域） |
| `maps` / `tiles` | 影像品質基準 | 預設 `true` / `8`：每張影像寫 `output/maps/<id>.png`（結果列 `map` 欄 + `map_metric`）：把偏離最多的指標依 8 × 8 方格著色（紅 = 偏離集中的位置）；全參考時改為 1 − SSIM 的方格圖 |
| `paired`、`reference_folder`、`ssim_warn`、`ssim_fail` | 影像品質基準 `compare` | 輸入 zip 有 `golden/`（或 `reference/`、`ref/`、`baseline/`）且其他資料夾有同檔名影像時自動逐張比對；`paired=false` 關閉 |
| `min_similarity` / `min_confidence` | few-shot / 微調 / Qwen | 低於門檻的 `prediction` 回 `unknown` |
| `threshold` | 所有 `score`；分類家族的 PatchCore 兩階段 | 覆寫模型存的異常門檻 |
| `patchcore` | `vision.dino` `predict` | `off` = 這次不走兩階段，直接用分類頭 |
| `instruction` | Qwen `retrieve` | 查詢端指令（非對稱檢索：用問題找答案）；同類文字互比時留空 |

解釋圖只在伺服器放 PNG 疊圖（不含原圖）；原圖仍只在使用者的瀏覽器（`SampleViewer` 把疊圖以可調透明度覆蓋在本地讀出的影像上）。畫面見 `docs/screenshots/features/`（retrieve 選項、疊圖、建議調整、全參考比對、模型庫）。

### 4.2 資料前處理（`input.spec.preprocess`）

共用套件 `libs/preprocess`（`qrlab_preprocess`）：使用者在上傳後挑步驟與參數，`POST /projects/{slug}/uploads/{id}/preview` 抽樣套用回傳前後對照；
步驟放在任務的 `input.spec.preprocess = [{op, params}]`。訓練時 fitted 步驟（補值數字、標準化統計、MSC 參考曲線、對位參考影像…）在訓練資料上學習並存進模型（`model/preprocess.json` 與產物 metadata）；推論自動沿用，不得再指定。
`GET /catalog/preprocess?data_type=` 列出每個步驟的參數規格。偵測 / 分割任務拒絕會改變座標的影像步驟。

- 類別欄用 `tabular.encode`（類別編碼，fitted）：`method = label`（依排序給 0…k−1 的整數代碼）/ `onehot`（每個類別一欄 `<欄位>__<類別>`，原欄移除）/ `ordinal`（`order` 指定由小到大的順序，不在順序中的值視為未知）；`unknown = missing | minus_one` 決定推論時沒看過的類別變成缺值或 −1（onehot 一律整列 0）；缺值維持缺值；一欄超過 `max_categories`（預設 200）就拒絕並建議移除該欄。`tabular.to_numeric`（文字數字轉成數值）只適合「以文字儲存的數字」，套在類別欄會整欄變缺值，預覽會警告。
- 預覽回傳除了 `steps / before / after`，還有 `step_details[{op, label, params, fitted, warnings[]}]`、`warnings[]`（各步驟警告加上「步驟 n（label）」前綴），TABULAR / TEXT 另附 `rows_in / rows_out` 與 `columns_in / columns_out[{name, dtype: number|text|bool|datetime, missing, missing_ratio, unique, min, max, mean, top[{value, count}]}]`（輸入樣本與整條管線的輸出）。

| data_type | 步驟 |
|---|---|
| TABULAR | `tabular.impute`、`drop_missing`、`clip_outliers`、`standardize`、`minmax`、`log`、`to_numeric`、`encode`、`filter_rows`、`drop_columns`、`keep_columns`、`drop_duplicates` |
| IMAGE | `image.resize`、`grayscale`、`crop`、`center_crop`、`autocontrast`、`equalize`、`gamma`、`stretch`、`denoise`、`sharpen`、`invert`、`flip`、`rotate`、`align` |
| SEQUENCE / SPECTRUM | `sequence.resample`、`crop`、`fill_nan`、`savgol`、`moving_average`、`derivative`、`baseline_poly`、`baseline_rolling_min`、`detrend`、`snv`、`minmax_sample`、`msc`、`standardize`、`clip` |
| TEXT | `text.lowercase`、`strip_whitespace`、`remove_punctuation`、`remove_urls`、`remove_numbers`、`truncate`、`replace_regex`、`drop_empty`、`dedupe` |

## 5. AutoML 候選矩陣（`mode = auto`）

| data_type | task_type | 候選（依序） | 條件 | 預算 |
|---|---|---|---|---|
| TABULAR | classification / regression | `tabular.xgboost`、`tabular.catboost`、`tabular.tabpfn`、`tabular.random_forest`、`tabular.linear`、`tabular.svm` | `row_count > 50000` 剔除 svm；`row_count > 10000` 剔除 tabpfn；`row_count < 1000` 優先 tabpfn、random_forest；模型庫沒有 TabPFN 權重時自動跳過 | 20 trials / 60 min |
| TABULAR | anomaly_detection | `tabular.isolation_forest` | | 10 / 20 |
| IMAGE | classification | `vision.dino`（搜尋 `finetune: none / lora`）、`vision.yolo` | `row_count < 100` 剔除 yolo | 8 / 120 |
| IMAGE | detection / segmentation | `vision.yolo` | | 8 / 120 |
| IMAGE | anomaly_detection | `vision.dino_patchcore`、`vision.image_quality` | 沒申請 GPU 時只剩 image_quality | 6 / 60 |
| SEQUENCE | anomaly_detection | `sequence.patch_autoencoder` | | 10 / 60 |
| SPECTRUM | anomaly_detection | `spectrum.masked_autoencoder`、`sequence.patch_autoencoder` | | 10 / 60 |
| SPECTRUM | regression | `spectrum.pls`、`spectrum.masked_autoencoder` | `row_count < 500` 剔除 MAE | 10 / 60 |
| SPECTRUM | classification | `spectrum.pls` | | 10 / 30 |
| TEXT | classification | `text.qwen_embedding`、`text.bert_classifier`、`tabular.linear`（TF-IDF） | `row_count < 300` 剔除 bert | 8 / 120 |
| TEXT | anomaly_detection | `text.qwen_embedding` | | 4 / 60 |

Job 沒申請 GPU 時，需要 GPU 的候選會被拿掉（全部都需要 → 400 `GPU_REQUIRED`）。

**記憶體**：GPU 任務的主程序光是 torch + CUDA 函式庫 + cuDNN 就約 3 GB（CPU 任務約 1.5 GB），每個 DataLoader worker 再約 0.5–0.75 GB；目錄的 `memory_mb_min` 只是參考值（精靈預設 GPU 任務 8 GB、CPU 任務 4 GB），不再擋任務：給太少會被 cgroup OOM-kill，log 會寫明。runner 依 `JOB_MEMORY_MB` 縮減 DataLoader worker 數。

## 6. AutoML 流程（trainer 實作）

1. backend 展開候選寫入 `jobs.config.search = {candidates, metric, direction, max_trials, time_budget_minutes}`；spec 同時帶每個候選的 `defaults` / `search_space`。
2. trainer：Optuna `TPESampler(seed=42)` + `MedianPruner(n_startup_trials=3)`，ask / tell 介面；每個 trial 先抽 `family`，再抽 `family.參數`。對應到權重的選項（DINO 的 `backbone`、YOLO 的 `model` + 任務後綴）只會抽模型庫裡有的（`automl.available_choices`），不會為缺權重的選項浪費 trial。
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
3. **推論時要做什麼？** 看 §4 的推論模式；例如光譜要「找最像的黃金樣本」就是 `retrieve`（可選只找最相似、只找最不相似或兩者都列），影像類別會一直增加就選 `vision.dino_fewshot`（之後用 `extend` 加類別）；類別固定、每類有幾十張以上、few-shot 不夠準就選 `vision.dino_finetune`（`method=linear` 最快，`lora` 讓特徵適應你的影像，`full` 資料多時才用）；兩者在結果頁都能點開影像看「模型關注的區塊」。文字要找相似工單 / 看有沒有新型問題選 `text.qwen_embedding`；光譜有量測值先用 `spectrum.pls`。
4. **資料有多少？有沒有標籤？** 沒標籤 → 只能做異常偵測；很少 → 自動模式會偏向小資料友善的模型（TabPFN、線性、隨機森林、DINO few-shot、PLS、Qwen 向量 + 邏輯迴歸）。
5. **第一次就選自動模式**：看 leaderboard 第一名的家族與指標，再用「手動模式」微調。
6. **看指標怎麼讀**：`f1_macro > 0.8` 通常可用；`rmse` 要跟目標範圍比；`map50 > 0.5` 可試用；`auroc > 0.9` 才算可靠。
7. **結果不好**：先檢查資料（標籤錯、類別極端不平衡、圖片太小、光譜長度不一致）、增加資料、再調搜尋空間或 epochs。
8. **要用模型**：到「模型」頁設預設 → 建立推論 Job（選模式、上傳 / 選資料來源 / 直接輸入）→ 下載 `predictions.csv`。

## 9. 預訓練權重（模型庫）

- **權重來源以 Hugging Face Hub 為主**（`families.*.weights`：`id`、`file`、`source`、`license`、`sha256`、`kind: hf_repo | hf_file | file`）；唯一的例外是 YOLO 的分割 / 分類權重，Hugging Face 上沒有，仍從 ultralytics 的 GitHub release 抓：

| 權重 | 來源 | 授權 | 類型 |
|---|---|---|---|
| `yolov8n/s/m` | Hugging Face `Ultralytics/YOLOv8`（`resolve/main/<file>.pt`） | AGPL-3.0 | `hf_file` |
| `yolov8n/s/m-seg`、`yolov8n/s/m-cls` | GitHub `ultralytics/assets/releases/download/v8.1.0/<file>.pt`（Hugging Face 沒有這幾個檔） | AGPL-3.0 | `file` |
| `dinov2-small`、`dinov2-base` | `facebook/dinov2-small`、`facebook/dinov2-base` | Apache-2.0 | `hf_repo` |
| `dinov3-vits16`、`dinov3-vitb16` | `facebook/dinov3-vits16-pretrain-lvd1689m`、`facebook/dinov3-vitb16-pretrain-lvd1689m` | DINOv3 License（gated：先在模型頁接受授權，下載時要 `HF_TOKEN`） | `hf_repo` |
| `bert-base-chinese`、`xlm-roberta-base` | `google-bert/bert-base-chinese`、`FacebookAI/xlm-roberta-base` | Apache-2.0 / MIT | `hf_repo` |
| `qwen3-embedding-0.6b` | `Qwen/Qwen3-Embedding-0.6B` | Apache-2.0 | `hf_repo` |
| `tabpfn-v2.5-classifier`、`tabpfn-v2.5-regressor` | `Prior-Labs/tabpfn_2_5`（`tabpfn-v2.5-*-v2.5_default.ckpt`） | Prior Labs License（Apache-2.0 加註明出處） | `hf_file` |

- 伺服器不連外、trainer 不下載：管理員在 **管理 → 模型庫**（`/admin/model-zoo`）把權重帶進 `MODEL_ZOO_ROOT`，三種方式：瀏覽器上傳（單檔或 HF snapshot 的 zip）、伺服器路徑（`MODEL_ZOO_IMPORT_ROOT`）、內網 URL（`MODEL_ZOO_ALLOWED_HOSTS`）；匯入時比對 `sha256`、寫 `manifest.json` 與稽核紀錄。有網路的機器用 `scripts/fetch_model_zoo.py --dest <資料夾>`（需要 `pip install huggingface_hub pyyaml`；`hf_repo` 走 `snapshot_download`、`hf_file` 走 `hf_hub_download`、`file` 走 urllib；gated 模型先 `export HF_TOKEN=hf_…`，還沒有 token 就 `--skip dinov3-vits16 dinov3-vitb16`；單一檔案失敗會列在結尾、其他照抓，重跑會跳過已存在的）整批抓好再放到傳輸資料夾。
  Job 子程序以 `MODEL_ZOO_ROOT` 直接讀取，runner 設定 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`YOLO_OFFLINE=1`。
- `GET /api/v1/admin/model-zoo`、`.venv/bin/python -m app.cli model-zoo [--verify]` 顯示每個權重是否存在；`GET /api/v1/catalog` 的 `weights_ready` 讓精靈標示缺權重的家族，建立任務時缺權重會被拒絕（`WEIGHTS_MISSING`）。
- 新增需要權重的家族：先在 yaml 的 `weights` 登記，再實作 trainer（透過 `ctx.weight(id)` 取路徑，絕不自行下載）。
- `vision.dino` 的產物：`finetune=none` / `lora` 不含骨幹（lora 只多一個幾 MB 的 `lora.pt`），推論時再從模型庫載入同一個骨幹；只有 `finetune=full` 會把整個骨幹存進產物。

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
    augment_choices: []    # 影像訓練家族才有：精靈多選的增強 op（defaults.augment 為預選）
    sop: 把光譜切 patch 隨機遮蔽再重建……
automl:
  - data_type: SPECTRUM
    tasks: [anomaly_detection]
    candidates: [spectrum.masked_autoencoder, sequence.patch_autoencoder]
    budget: { max_trials: 10, time_budget_minutes: 60 }
```
