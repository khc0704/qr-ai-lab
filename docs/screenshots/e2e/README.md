# 端到端串接測試截圖

`frontend/scripts/e2e-walkthrough.mjs` 以 Playwright 驅動真的前端（`next start`）、backend（FastAPI + SQLite + Redis）、
排程器（`JOB_RUNNER=subprocess`）與 trainer，走完整流程並在每一步截圖；`captions.json` 記錄每張的說明、階段、主題與視窗，
`state.json` 記錄建立的申請 / 任務 id（讓部分階段可以單獨重跑）。報告 PDF 由 `frontend/scripts/e2e-report.mjs` 產生到
`docs/manuals/QR-AI-Lab-串接測試報告.pdf`，`index.html` 是同一份內容的網頁版。

重跑方式見 `docs/GETTING_STARTED.md` §4.8。截圖用 PNG 256 色儲存以縮小 repo（`scripts/`
不含壓縮腳本；Pillow 的 `Image.quantize(256)` 即可）。

## 合成資料（`gen_data.py`）

全部為程式產生、不含任何真實量測，只為了展示流程：

| 檔案 | 內容 | 用在 |
|---|---|---|
| `wat_yield.csv` | 480 個 lot 的 WAT 電性參數（Vth、Idsat、Rs、CD、膜厚、量測溫度）→ `yield_pct`；`line` 類別欄、`lot_id` 識別欄；少量缺值 | 表格 × 迴歸：AutoML、前處理預覽、推論 |
| `sem_golden_tool.zip` | golden 機台 40 張 128×128 灰階「SEM 風格」影像（條紋 + 棋盤 + 雜訊，逐張有對焦 / 亮度 / 雜訊抖動） | 影像品質基準（訓練） |
| `sem_tuned_tool.zip` | 調機機台 16 張：稍微失焦、偏暗、雜訊略高 | `compare` 機台比對報告 |
| `sem_bad_tool.zip` | 明顯失焦、偏暗、雜訊高的機台 12 張 | 備用 |
| `ocd_spectra.csv` | 264 片 wafer × 200 個波長（400–800 nm）的干涉條紋光譜；最後 24 片膜厚偏厚並多一個吸收谷（`label=1`） | 光譜 Masked AE（訓練 + 異常分數） |

```bash
python3 docs/screenshots/e2e/gen_data.py /path/to/datasets     # 需要 numpy、Pillow（trainer 的 .venv 就有）
```
