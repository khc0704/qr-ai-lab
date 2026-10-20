# 功能截圖（模型升級批次）

在沙盒以真的 backend（內嵌排程器）、正式建置的前端與極小的 DINOv2 / Qwen3 測試權重跑出來的畫面
（`scripts` 之外的檢查腳本，不在 repo 裡）；正式環境的畫面相同，只是模型是真的。

| 檔案 | 畫面 |
|---|---|
| `01-infer-retrieve-options.png` | 一次性推論頁：推論模式選 `retrieve` 後出現「要找的方向」（最相似 / 最不相似 / 兩者）與「每筆回傳幾個」 |
| `02-sample-overlay.png` | 結果列點開樣本：模型關注的區塊疊在瀏覽器本地的原圖上，可關閉、可調透明度 |
| `03-iqa-advice.png` | 影像品質基準 `compare`：逐指標表之外多了「建議調整」卡片（依面向與方向給動作） |
| `03b-iqa-map-overlay.png` | 影像品質基準的結果列點開樣本：偏離基準最多的區塊 |
| `04-iqa-paired.png` | 有 `golden/` 參考資料夾時的「與參考影像逐張比對（全參考）」卡片（PSNR / SSIM / MS-SSIM / GMSD） |
| `05-wizard-retrieve.png` | 建立推論任務精靈：同一組 retrieve 選項 |
| `06-model-zoo.png` | 管理員「模型庫」：所有權重來源都是 Hugging Face Hub（snapshot 與單檔兩種類型） |
