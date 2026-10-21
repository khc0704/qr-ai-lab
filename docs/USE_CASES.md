# 半導體 / 電子製造的資料類型、模型與推論目的

這份文件回答「我們廠裡的哪種資料，可以用哪個模型，推論的時候到底要拿它做什麼」。模型本身只是手段；
每個情境都先定義**推論目的**（inference mode），再回推訓練方式。所有家族的實作在 `trainer/trainer/models/`，
目錄與搜尋空間在 `docs/MODEL_CATALOG.md`。

## 1. 推論模式（先想清楚推論要做什麼）

| mode | 白話 | 輸出 | 誰提供 |
|---|---|---|---|
| `predict` | 給一筆資料，回一個類別或數值 | `prediction`、`confidence` / 各類機率；DINO 另附 `attention`（模型關注的區塊疊圖） | 表格（XGBoost / CatBoost / TabPFN …）、文字（BERT、Qwen 向量 + 分類頭）、DINO few-shot / 微調、YOLO 分類、光譜 PLS / MAE 迴歸頭 |
| `score` | 這筆資料「正不正常」 | `anomaly_score`、`is_anomaly`（門檻存在模型裡，可覆寫） | Isolation Forest、Patch AE、光譜 MAE、PatchCore（附熱圖）、影像品質基準（附偏離區塊疊圖 + 調整建議）、Qwen（novelty） |
| `embed` | 把資料變成向量，給下游分析（分群、繪圖、相似度） | `embedding`（另存 `embeddings.npy`） | 所有深度學習家族、PLS（分數）、Qwen |
| `retrieve` | 跟參考庫比：最相似 / 最不相似是誰、有多新。`config.order = similar / dissimilar / both` 選方向、`k` 選幾個 | `most_similar[]`、`least_similar[]`、`neighbors[]`（選的那一邊）、`max_similarity`、`novelty`；DINO 另附 `attention` | Patch AE、光譜 MAE（參考庫 = 訓練視窗）、DINO few-shot / 微調（參考庫 = 範例 / 訓練影像）、Qwen（參考庫 = 訓練文字） |
| `detect` / `segment` | 圖裡東西在哪、哪些像素 | 框、遮罩、標註圖 | YOLO |
| `measure` | 從分割遮罩算幾何量（面積、寬高、等效直徑；給 `pixel_size` 可換算 nm / µm） | 每個物件一列 | YOLO segmentation |
| `extend` | **不重訓**，直接把新類別（新 bin code）的範例加進原型庫，產生新版本模型 | 新 model artifact（自動設為預設） | DINO few-shot |
| `compare` | 整批影像與黃金機台的影像品質基準比對（調機驗收） | 每個指標 match / drift / fail、總判定、`comparison.csv`、逐面向的調整建議（`advice`）；有 `golden/` 參考資料夾時逐張 PSNR / SSIM / MS-SSIM / GMSD（`paired`、`paired.csv`） | 影像品質基準 |

推論 Job 的 `config.mode` 指定模式；不填就用該模型 `inference_modes` 的第一個。

## 2. 總表：機台 / 資料 → 模型 → 推論目的

| 來源 | data_type | 情境 | 建議家族 | 推論目的 |
|---|---|---|---|---|
| OCD / 散射量測、橢圓偏光、反射光譜 | `SPECTRUM` | 光譜鑑別器：和黃金樣本比，找最像 / 最不像、追蹤批次漂移 | `spectrum.masked_autoencoder`（候補 `sequence.patch_autoencoder`） | `retrieve`、`score` |
| 同上 + 有量測值（CD、膜厚、側壁角） | `SPECTRUM` × `regression` | 光譜 → 量測值（快速虛擬量測） | `spectrum.pls`（PLS 迴歸，幾十筆就能用、VIP 說哪些波長重要）；資料多時 `spectrum.masked_autoencoder`（自監督 + Ridge 迴歸頭） | `predict` |
| 光譜 + 已知類別（配方 / 材料 / 批次） | `SPECTRUM` × `classification` | 光譜分類 | `spectrum.pls`（PLS-DA） | `predict` |
| FTIR / Raman / XRF / PL | `SPECTRUM` | 材料 / 配方 / 批次異常、污染偵測 | 同上 | `score`、`retrieve`、`embed` |
| TEM / SEM / 光學顯微 表面影像 | `IMAGE` × `classification` | bin code 分類，類別會持續增加 | `vision.dino_fewshot`（DINOv2 或 DINOv3 骨幹；每類幾張就能用；新類別用 `extend`；結果可看模型關注的區塊） | `predict`、`retrieve`、`extend` |
| 同上，類別固定、每類幾十張以上 | `IMAGE` × `classification` | 更準的分類，並看 Grad-CAM 知道模型看哪裡 | `vision.dino_finetune`（`linear` / `lora` / `full`） | `predict`（附 Grad-CAM）、`retrieve` |
| 同上，資料量大、類別固定 | `IMAGE` × `classification` | 高準確度分類 | `vision.yolo`（`-cls` 權重微調，或 `pretrained=false` 從頭訓） | `predict` |
| 同上，只有良品影像 | `IMAGE` × `anomaly_detection` | 找「跟正常不一樣」的影像並標出位置 | `vision.dino_patchcore` | `score`（含熱圖） |
| SEM 線寬 / 孔洞 / 顆粒 | `IMAGE` × `segmentation` | 分割後量測幾何 | `vision.yolo`（`-seg`） | `segment`、`measure` |
| 任何機台（SEM / TEM / 光學）的影像品質 | `IMAGE` × `anomaly_detection` | 黃金機台建立品質基準與浮動範圍；調機後驗收（含該調哪個旋鈕的建議）、日常監控、同一樣品在兩台機台的逐張比對 | `vision.image_quality`（CPU、免權重） | `compare`、`score` |
| AOI / 外觀檢測 | `IMAGE` × `detection` | 缺陷定位、計數、分類 | `vision.yolo` | `detect` |
| Wafer map / bin map | `IMAGE` × `classification` | 失效圖樣（環、刮痕、邊緣…）分類 | 先把 map 轉成圖片 → `vision.dino_fewshot` / `vision.yolo` | `predict` |
| FDC / 機台感測器 trace | `SEQUENCE` × `anomaly_detection` | 異常 run 偵測、找相似 run | `sequence.patch_autoencoder` | `score`、`retrieve`、`embed` |
| FDC 摘要特徵 + 量測值 | `TABULAR` × `regression` | 虛擬量測（VM） | `tabular.xgboost`、`tabular.catboost`（AutoML 會一起試 TabPFN / RF / 線性） | `predict` |
| WAT / PCM / 電性、良率表 | `TABULAR` × `classification` / `regression` | 良率預測、失效分類、找關鍵參數（特徵重要度） | `tabular.xgboost`、`tabular.catboost`、`tabular.random_forest`、`tabular.linear`（可解釋基準） | `predict` |
| 小表格（幾十到幾千列）的分類 / 迴歸 | `TABULAR` × `classification` / `regression` | 免調參就要準、不想等 | `tabular.tabpfn`（表格基礎模型，權重來自模型庫） | `predict` |
| WAT / PCM 多參數 | `TABULAR` × `anomaly_detection` | 參數組合離群（單一 spec 內但組合怪） | `tabular.isolation_forest` | `score` |
| 設備 log、工單、客訴、8D 報告 | `TEXT` × `classification` | 自動歸類、派工 | `text.qwen_embedding`（向量 + 邏輯迴歸，幾十筆就能用）、`text.bert_classifier`（資料多時微調）、`tabular.linear`（TF-IDF 基準） | `predict`、`embed` |
| 同上 | `TEXT` × `classification` / `anomaly_detection` | 找相似的歷史工單 / 處置紀錄；偵測「和過去都不像」的新型問題 | `text.qwen_embedding` | `retrieve`、`score`、`embed` |

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

### 3.2 光譜 → CD / 膜厚（迴歸）與光譜分類

- 同 3.1 的資料，再加 `label` 欄為量測值；`task_type=regression`。
- **先用 `spectrum.pls`**（化學計量學的標準做法）：`n_components` 自動模式會搜 2 … 30；幾十筆就能用、秒級；產物 `report/vip.csv` 列出每個波長的 VIP（> 1 = 這個波長真的在用）與 loading，可直接拿去跟製程討論。推論 `predict` 回 `prediction`，`embed` 回 PLS 分數。
- 資料多（≥ 500 筆）再比 `spectrum.masked_autoencoder`：MAE 先做自監督預訓練，再以 embedding 接 Ridge 迴歸頭（`ridge_alpha`）；推論 `predict` 多給 `reconstruction_error`（誤差大 = 這筆光譜不在訓練分布內，預測值別信）。
- 光譜要分類（配方 / 材料 / 批次）：`task_type=classification` + `spectrum.pls`（PLS-DA：PLS 分數接邏輯迴歸），推論 `predict` 回類別與各類機率。
- MAE / Patch AE 的 `score` 回每個 patch 的分數與最偏離的波段（`hot_band_start / end` = 樣本點範圍，`summary.hot_bands` 統計異常最常落在哪一段），所以能說「這批異常都在 600–650 nm」；`score_method=patch_bank` 改用正常 patch token 庫的最近鄰距離（一維 PatchCore），對局部波段異常更敏感；MAE 的 embedding 可選 `embed_layers=mid / all` 與 `embed_pool=max / gem / meanmax`。

### 3.3 TEM / SEM 表面影像 bin code（few-shot，新類別免重訓）

- **資料**：zip，`<bin_code>/*.png`，每類 ≥ 3 張即可開始（建議 10+）。
- **訓練**：`vision.dino_fewshot`（`backbone=dinov2-small / dinov2-base / dinov3-vits16 / dinov3-vitb16`）。凍結 DINO 讀幾層 patch 特徵（`layers=cross` 跨層 9 / 10 / 11，或 `last`）做成每張一個向量，再接分類頭；評估用分層切分或 leave-one-out。DINOv3 的 patch 更細（16 px、含 register token），SEM / TEM 紋理通常較穩；權重是 gated，管理員要先在 Hugging Face 接受授權。
- **怎麼分類**（`head`，`docs/MODEL_CATALOG.md` §4.1b）：`auto` 預設在每類不到 10 張時用最近原型（prototype：每類一個平均向量比 cosine）、夠多時用線性分類頭；同一類有多種長相用 `knn`；也可選 `svm`。`image_size=336 / 448` 看小瑕疵。
- **有正常類別時（good / normal / ok / pass 資料夾，或 `normal_class` 指定任何名字）** 自動走 PatchCore 兩階段：正常影像的 patch 建記憶庫先判「正常 / 異常」，異常影像只拿超過門檻的 patch（缺陷區塊）加權成描述子，再分 scratch / void … 這些缺陷資料夾；`predict` 多回 `anomaly_score`、`is_anomaly`、缺陷位置，疊圖就是 patch 異常分數；`score_agg` / `coreset_ratio` / `bank_augment` 預設 `auto`，實際選了什麼寫在 log 與 metadata 的 `resolved`。good 其實只是另一種圖樣時設 `patchcore=off`。
- **新增 bin code**：建推論 Job，`config.mode="extend"`，輸入是新類別的資料夾 zip → 產生新版本模型並設為預設，原本的類別都保留。
- **推論**：`predict`（`config.min_similarity` 低於門檻回 `unknown`，避免硬塞進既有類別）、`retrieve`（`order` 選只找最相似 / 只找最不相似 / 兩者，`k` 選幾個；最不相似用來找離群或挑下一批要標註的）。
- **看模型在看哪裡**：`predict` / `retrieve` 每張影像都寫一張「模型關注的區塊」疊圖（每個 patch 與匹配到的原型 / 鄰居的相似度），結果頁點開樣本就疊在原圖上（可關、可調透明度）；紅色區域就是這張圖被判成該類別的依據，和你的直覺不合時通常是背景或資訊列在主導 → 先用 `image.crop` 前處理切掉。
- **何時改用微調**：類別固定、每類有幾十張以上、凍結特徵不夠準 → `vision.dino_finetune`（LoRA：在 DINO 的注意力層加低秩轉接器和線性頭一起訓練，產物只有幾 MB；`epochs` / `batch` 預設 auto）。推論同樣有 `predict`（`config.min_confidence` 低於門檻回 `unknown`；附 CAM 疊圖 = 線性頭權重對每個 patch 的貢獻）、`retrieve`（同樣可選方向）、`embed`。
- **何時改用 YOLO 分類**：類別固定、每類有數百張、要更高準確度 → `vision.yolo`（`model=yolov8s`、`pretrained=true` 用模型庫的 `yolov8s-cls.pt` 微調；`pretrained=false` 從頭訓練）。

### 3.4 只有良品影像：PatchCore 異常 + 熱圖

- 資料夾 `good/`（或 `normal/`、`ok/`）為正常；其他資料夾視為異常（只用來評估）。
- `vision.dino_patchcore`：DINO patch 特徵建記憶庫（`coreset_ratio=auto` 讓庫不超過 10 萬個 patch），分數 = patch 到記憶庫的最近鄰距離，影像分數 = 最大值或前 1% 平均（`score_agg=auto`）；門檻 = 保留的正常影像分數 P99。預設讀 `layers=cross`（9 / 10 / 11）拼接，`last` 只讀最後一層；正常影像少於 20 張時 `bank_augment=auto` 把翻轉 / 旋轉後的影像也放進庫；小瑕疵把 `image_size` 拉到 336 / 448；瑕疵比 patch 大時 `neighborhood=3`。
- 推論 `score`：每張回分數、`hot_patch_row/col`，`output/heatmaps/*.png` 熱圖（`config.save_heatmaps=false` 可關）。

### 3.5 SEM 線寬 / 顆粒量測

- YOLO segmentation 格式（多邊形標註 + `data.yaml`）訓練 `vision.yolo`（`-seg`）。
- 推論 `measure`：每個物件回 `area_px`、`width_px`、`height_px`、`equiv_diameter_px`；`config.pixel_size`（例如 2.5 代表每像素 2.5 nm）會多給 `*_phys` 欄。

### 3.5b 影像品質基準與機台比對（tool matching）

- **問題**：沒有標準答案的「影像品質」要怎麼量？做法是把黃金機台的一批影像變成 17 個無參考指標（清晰度 Laplacian / Tenengrad / Brenner、雜訊標準差、訊噪比、對比 RMS / Michelson、亮度平均 / P1 / P99、過暗 / 過亮飽和比例、亮度熵、高頻能量比、頻譜斜率、梯度與頻譜的方向性），以穩健中位數與 MAD 建立基準與浮動範圍（中位數 ± 3 × 尺度），並以 Mahalanobis 距離做整體判定。
- **訓練**：`vision.image_quality`，資料夾 `good/` 放黃金機台影像（≥ 30 張較穩）；其他資料夾可放已知偏差的影像當驗證。產物 `report/baseline_ranges.csv` 直接是每個指標的允收範圍。
- **推論 `compare`**：把調機後機台的一批影像丟進來 → 每個指標的 effect（偏移幾個尺度）、KS 檢定 p 值、in_range_ratio 與 verdict，總判定 pass / drift / fail，`output/comparison.csv` 就是調機報告；`score` 給單張影像的 z 分數與距離做日常監控。
- **該調什麼**：17 個指標分成五個面向（對焦 / 清晰度、雜訊、亮度、對比、方向性 / 像散），compare 的 `advice` 與 score 每列的 `advice` 依偏離的面向與方向給出動作（例如「比基準模糊 → 重新對焦、校正像散、確認工作距離」、「方向性不同 → stigmator X / Y、掃描方向」）；結果頁有「建議調整」卡片。
- **偏離在哪裡**：每張影像寫一張「偏離基準最多的區塊」疊圖（把偏離最多的指標依 8 × 8 方格著色），點開樣本就疊在原圖上：整張一致 = 機台設定，集中在某一角 = 樣品不平、帶電或掃描問題。
- **同一樣品兩台機台逐張比（全參考）**：zip 放 `golden/`（參考機台）與 `target/`（或任何名字）兩個資料夾、同檔名 → `compare` 自動逐張對位（相位相關）後算 PSNR、SSIM、MS-SSIM、GMSD，`summary.paired` 給平均與 pass / drift / fail（`ssim_warn=0.9`、`ssim_fail=0.7` 可調），`output/paired.csv` 逐張，疊圖改成 1 − SSIM 的差異方格圖。
- **注意**：基準只適用同類樣品與同倍率；先用前處理 `image.crop` 裁掉 SEM 資訊列。像散 / 掃描方向問題會反映在方向性指標，焦距在清晰度與高頻能量比，亮度 / 對比設定在亮度與飽和比例。
- **可再加**：DINO 特徵分布距離（Fréchet）當第 18 個「語意」指標、依樣品結構分區計算（中心 / 邊緣）、學習式 NR-IQA（需要人工評分資料）。

### 3.6 FDC trace 異常 / 找相似 run

- 長表 `series_id,t,feature…` + `spec.window` / `stride`（切視窗），或 `npy` `N × T × C`。
- `sequence.patch_autoencoder`：patch 嵌入 + 位置編碼 + 整段視窗壓到一個 latent，所以「峰值移位」也抓得到。
- 推論 `score`、`retrieve`（找跟歷史最像 / 最不像的 run）、`embed`（丟到 BI 做分群）。

### 3.7 WAT / PCM / 良率表

- `csv` / `parquet`，`spec.target` 為目標欄；類別欄自動 one-hot，缺值自動補。
- 第一次用 `mode=auto`：XGBoost / CatBoost / TabPFN / 隨機森林 / 線性 / SVM（> 50k 列自動剔除 SVM、> 10k 列剔除 TabPFN；< 1k 列優先 TabPFN 與隨機森林），leaderboard 看完再手動微調。
- TabPFN（`tabular.tabpfn`）是預訓練好的表格 transformer，fit 只是把訓練列放進上下文，沒有超參數要調，幾十到幾千列的表格常常直接最準；權重 `tabpfn-v2.5-*.ckpt` 來自模型庫，有 GPU 快很多。CatBoost 與 XGBoost 一起試，取 leaderboard 較好的。
- 產物附 `report/feature_importance.json`（前 50 個特徵），可直接拿去開會。
- 只想找離群：`task_type=anomaly_detection` → `tabular.isolation_forest`，推論 `score`。

### 3.8 設備 log / 工單文字

- `jsonl` 或 `csv`，`spec.text_column` / `label_column`。
- 分類：AutoML 先試 `text.qwen_embedding`（凍結的 Qwen3-Embedding 向量 + 邏輯迴歸，幾十筆就能用、不用 GPU 也跑得動）與 TF-IDF + 邏輯迴歸；≥ 300 筆再加入 `text.bert_classifier`（微調 `bert-base-chinese` / `xlm-roberta-base`，需要 GPU）。
- 推論 `predict`（各類機率）或 `embed`（向量）。

### 3.9 文字相似搜尋與新型問題偵測（Qwen3 Embedding）

- **用途**：新工單進來先找最像的歷史工單與當時的處置（`retrieve`，`order=similar`）；每週把新 log 丟進去找「和過去都不像」的（`order=dissimilar` 或 `anomaly_detection` 的 `score`：novelty = 1 − 與參考庫的最大相似度，門檻 = 訓練文字的 P99）；`embed` 把工單變向量丟到 BI 做分群、找重複客訴。
- **訓練**：`text.qwen_embedding`；`task_type=classification`（有標籤 → 參考庫 + 分類頭）或 `anomaly_detection`（只要歷史文字；有 `normal` / 其他標籤時用來算 auroc）。模型只存參考庫的向量與 id / 標籤（不存原文），骨幹推論時再從模型庫載入。
- **選項**：`k`、`order`、`reference=self`（輸入互比，找一批裡的重複）、`instruction`（非對稱檢索，例如用問題找答案時加「Given a question, retrieve the ticket that answers it」；同類文字互比留空）。

## 3.10 資料前處理（所有資料類型）

上傳後可挑選前處理步驟並即時抽樣預覽（表格補值 / 離群 / 標準化、影像裁切 / 對比 / 去雜訊 / 對位、光譜 SNV / MSC / 平滑 / 基線、文字清理），步驟隨任務送出；訓練時學到的數值存進模型，推論自動沿用。清單見 `docs/MODEL_CATALOG.md` §4.2。

## 4. 預訓練權重政策（模型庫）

- 伺服器上的 Job 子程序**離線**（`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`YOLO_OFFLINE=1`），不會從任何套件自動下載模型。
- **權重以 Hugging Face Hub 為主**（YOLO 偵測版從 `Ultralytics/YOLOv8`、DINOv2 / v3 從 `facebook/*`、BERT、Qwen3-Embedding、TabPFN 從 `Prior-Labs/tabpfn_2_5`；YOLO 的 -seg / -cls 權重 Hugging Face 沒有，仍從 ultralytics 的 GitHub release 抓；清單與授權見 `docs/MODEL_CATALOG.md` §9）。需要的權重清單在 `backend/app/catalog/model_catalog.yaml` 每個家族的 `weights`；管理員在**有網路的機器**執行
  `python3 scripts/fetch_model_zoo.py --dest ./model_zoo`（DINOv3 是 gated：先在模型頁接受授權、`export HF_TOKEN=…`），把整個資料夾放到伺服器的 `MODEL_ZOO_ROOT`（預設 `DATA_ROOT/model_zoo`），
  再用 `.venv/bin/python -m app.cli model-zoo --verify` 或管理員頁「模型庫」確認。
- sklearn / XGBoost / CatBoost / PLS / 影像品質基準沒有預訓練權重，直接訓練；`vision.yolo` 的 `pretrained=false` 也不需要權重。
- 缺權重時 Job 會在 log 清楚說明缺哪個檔、該放哪裡，並以 failed 結束。

## 5. 還沒做、值得接著做

- 光譜 MAE 迴歸頭目前是 Ridge；資料量大時可改 MLP 頭或端到端微調（小資料已有 PLS）。
- 影像品質：學習式 NR-IQA（需要人工評分）、DINO 特徵分布距離當語意指標。
- PatchCore 的 coreset 目前是隨機抽樣，記憶庫很大時可換 greedy k-center。
- Wafer map 專用模型（直接吃 bin map 矩陣）、FDC 的 TCN / Transformer。
- 主動學習：把 `retrieve` 找出的「最不像」樣本送去人工標註，再 `extend` 進原型庫。
- 推論結果回寫到 MES / 報表系統的接口（目前是 CSV / JSONL 下載）。
