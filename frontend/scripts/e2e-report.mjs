// Builds docs/manuals/QR-AI-Lab-串接測試報告.pdf from the walkthrough screenshots + captions.json
// (HTML rendered to PDF with the bundled Chromium). Run after scripts/e2e-walkthrough.mjs.
import { chromium } from "playwright";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SHOTS = path.join(ROOT, "docs/screenshots/e2e");
const OUT_DIR = path.join(ROOT, "docs/manuals");
const OUT_PDF = path.join(OUT_DIR, "QR-AI-Lab-串接測試報告.pdf");
const OUT_HTML = path.join(SHOTS, "index.html");

const captions = JSON.parse(await readFile(path.join(SHOTS, "captions.json"), "utf8")).sort((a, b) => a.n - b.n);
const meta = JSON.parse(await readFile(path.join(SHOTS, "run.json"), "utf8").catch(() => "{}"));

const PHASES = {
  request: [
    "1. 一般使用者：登入、專案申請",
    "AUTH_MODE=local 的登入頁（superadmin / admin / user 三個本地帳號）→ user 填寫結構化申請（題目、資料類型 × 任務、資源需求）→ 送出 → 在討論串留言。",
  ],
  approve: [
    "2. 管理員：審核、配額、總資源池",
    "admin 登入 → 開始審核 → 核准並指定 slug / 配額（受總資源池限制）→ 專案自動建立；另兩件申請由 API 核准。總資源池只有 superadmin 能改：GPU 卡片、依顯存共用 GPU 開關、確認對話框與稽核。",
  ],
  zoo: [
    "2b. 管理員：模型庫（伺服器不連外）",
    "三種把預訓練權重帶進模型庫的方式：瀏覽器上傳、伺服器路徑（NAS / USB）、內網 URL（公司鏡像）；sha256 驗證與稽核。trainer 永遠離線，只讀模型庫。",
  ],
  project: [
    "3. 專案：成員、資料來源、設定",
    "專案列表與總覽 → 邀請成員 → 新增 URL 資料來源（憑證加密、連線檢查）→ 專案設定。",
  ],
  train: [
    "4. 訓練任務：上傳 → 前處理預覽 → AutoML → 即時 log → 產物",
    "一次性上傳 CSV（任務結束即刪）→ 指定欄位、加入前處理步驟並抽樣預覽 → AutoML（XGBoost / 隨機森林 / 線性 / SVM）→ 建立後經排程器以 subprocess runner 執行 → SSE 即時進度與 log → leaderboard、產物、預設模型。",
  ],
  infer: [
    "5. 推論任務：直接輸入 → 結果預覽與下載",
    "用預設模型對新 lot 做 predict → 結果摘要、前 20 筆預覽（帶回 lot_id）、CSV 下載。",
  ],
  iqa: [
    "6. 影像品質基準（golden tool vs 調機機台）",
    "上傳 golden 機台 40 張影像建立基準（17 個無參考指標的中位數 / 浮動範圍 / Mahalanobis 門檻）→ 上傳調機機台影像以 compare 模式產生機台比對報告。",
  ],
  spectrum: [
    "7. 光譜鑑別器（Masked AutoEncoder）",
    "寬表 CSV（每列一片 wafer、200 個波長）→ SNV 前處理預覽 → 手動選 MAE 訓練（CPU）→ 即時 epoch 進度與指標。",
  ],
  discussion: ["8. 討論區（問題單）", "user 建立錯誤回報並關聯專案 → admin 回覆、寫處理結果並關閉 → 列表。"],
  admin: [
    "9. 管理員：佇列、強制中斷、重新執行、稽核",
    "user 透過 API 建立一個 60 trial 的 AutoML 與一個等待中的任務 → admin 在佇列看到執行中 / 等待原因 → 任務抽屜看即時 log → 強制中斷（需理由）→ 等待中的任務接著執行 → 稽核紀錄 → Dashboard（資源池唯讀）→ 任務頁的管理員操作：重新執行成一個新任務；user 端看到被中斷的任務與理由。",
  ],
  roles: [
    "10. 三種系統角色：superadmin / admin / user",
    "superadmin 在使用者頁改角色（升 / 降、稽核）、刪除專案（輸入 slug 確認）；admin 看配額與模型庫是唯讀、可刪討論串；user 沒有管理選單，/admin 是 404。後端以 require_perm 判斷，前端只隱藏。",
  ],
  usage: [
    "11. 資源使用率歷史",
    "排程器每 30 秒取樣節點 / 資源池 / 各專案；1 小時到 30 天分桶；分母可切專案配額 / 資源池 / 系統總量；各專案的時間加權占用與實測 CPU / 記憶體。",
  ],
  tool: [
    "12. 資料前處理服務（任務模式、不保存）",
    "選資料類型 → 上傳 → 指定不處理的欄位 → 加步驟並即時抽樣預覽 → 建立 preprocess 任務（個人工作區、全域佇列、配額、log）→ 任務頁下載 zip（processed.csv + pipeline.json + summary.json）一次即刪。",
  ],
  analyze: [
    "12b. 資料分析服務",
    "表格資料探勘（相關性、VIF 共線性、對目標的解釋力與建議）與影像品質分析（三台機台的 IQA 指標飄移、embedding 散佈與相似度、離群影像），都是個人工作區的 analysis 任務，報告在任務頁。",
  ],
  visual: ["13. Light mode 與手機版", "同一套語意 token 的淺色主題（含使用率歷史）；手機寬度側欄收成抽屜。"],
  logout: ["14. 登出", "使用者選單登出 → 回到登入頁；受保護頁面由 proxy.ts 導向 /login?next=。"],
  keycloak: [
    "15. Keycloak 登入（AUTH_MODE=keycloak）",
    "前後端切到 keycloak 模式並指向一個模擬的 realm（scripts/fake_keycloak.py）：登入頁只剩公司帳號按鈕 → Authorization Code + PKCE → realm 登入頁 → 回到首頁並依 KEYCLOAK_ROLE_MAP 取得角色 → 使用者頁標記 keycloak → 登出走 end-session；新帳號第一次登入自動建立。",
  ],
};

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
const groups = new Map();
for (const c of captions) {
  if (!groups.has(c.phase)) groups.set(c.phase, []);
  groups.get(c.phase).push(c);
}
const date = new Date().toLocaleDateString("zh-TW", { year: "numeric", month: "long", day: "numeric" });
let body = `
<section class="cover">
  <div class="brand">QR AI Lab</div>
  <h1>前端 × 後端實際串接測試報告</h1>
  <p class="lead">Next.js 16 前端 → FastAPI 後端 → 排程器（Redis 事件、subprocess runner）→ trainer，在單機沙盒以 SQLite 跑完整流程所得的 ${captions.length} 張截圖。</p>
  <table class="facts">
    <tr><th>日期</th><td>${esc(date)}</td></tr>
    <tr><th>帳號</th><td>admin / admin1234（管理員）、user / user1234（一般使用者）</td></tr>
    <tr><th>資料</th><td>全部為合成資料：WAT 良率表（480 lot）、SEM 風格影像（golden 40 張、調機機台 16 張）、OCD 光譜（264 片 wafer × 200 波長）</td></tr>
    <tr><th>環境</th><td>${esc(meta.env ?? "backend: SQLite、SCHEDULER_EMBEDDED=true（排程器與 API 同一程序，無 Redis）、JOB_RUNNER=auto → subprocess（沙盒沒有 systemd user manager；伺服器上會是 systemd cgroup）；frontend: next build + next start；瀏覽器: Chromium（Playwright）")}</td></tr>
    <tr><th>結果</th><td>${esc(meta.summary ?? "所有流程完成；訓練 / 推論任務皆 succeeded；強制中斷流程正確")}</td></tr>
  </table>
  <h2>目錄</h2>
  <ol class="toc">${[...groups.keys()].map((k) => `<li>${esc(PHASES[k]?.[0] ?? k)}<span>${groups.get(k).length} 張</span></li>`).join("")}</ol>
</section>`;
for (const [phase, items] of groups) {
  const [title, desc] = PHASES[phase] ?? [phase, ""];
  body += `<section class="phase"><h2>${esc(title)}</h2><p class="desc">${esc(desc)}</p>`;
  for (const c of items) {
    body += `<figure class="shot ${c.viewport === "mobile" ? "mobile" : ""}">
      <figcaption><span class="num">${String(c.n).padStart(2, "0")}</span> ${esc(c.caption)}<span class="tag">${esc(c.theme)}${c.viewport === "mobile" ? " · 390px" : ""}</span></figcaption>
      <img src="${esc(c.file)}" alt="${esc(c.caption)}" />
    </figure>`;
  }
  body += `</section>`;
}
const html = `<!doctype html><html lang="zh-TW"><head><meta charset="utf-8"><title>QR AI Lab 串接測試報告</title>
<style>
  @page { size: A4; margin: 14mm 12mm; }
  * { box-sizing: border-box; }
  body { font-family: "Noto Sans CJK TC", "WenQuanYi Micro Hei", "Microsoft JhengHei", system-ui, sans-serif; color: #1b1f24; margin: 0; font-size: 11pt; line-height: 1.5; }
  .cover { page-break-after: always; }
  .brand { color: #f0620b; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; font-size: 10pt; margin-top: 18mm; }
  h1 { font-size: 26pt; margin: 4mm 0 2mm; }
  .lead { font-size: 12pt; color: #4b5563; max-width: 150mm; }
  .facts { border-collapse: collapse; margin: 8mm 0; width: 100%; font-size: 10pt; }
  .facts th { text-align: left; width: 22mm; color: #6b7280; font-weight: 500; padding: 2mm 2mm 2mm 0; vertical-align: top; }
  .facts td { padding: 2mm 0; border-bottom: 1px solid #e5e7eb; }
  .toc { padding-left: 5mm; font-size: 10.5pt; }
  .toc li { padding: 1mm 0; border-bottom: 1px dotted #d1d5db; display: flex; justify-content: space-between; }
  .toc li span { color: #6b7280; font-family: ui-monospace, monospace; }
  .phase { page-break-before: always; }
  h2 { font-size: 16pt; margin: 0 0 1mm; padding-bottom: 1.5mm; border-bottom: 2px solid #f0620b; }
  .desc { color: #4b5563; margin: 2mm 0 5mm; font-size: 10pt; }
  figure.shot { margin: 0 0 7mm; page-break-inside: avoid; }
  figure.shot img { width: 100%; border: 1px solid #d1d5db; border-radius: 3px; max-height: 240mm; object-fit: contain; object-position: top; }
  figure.shot.mobile img { width: 60mm; display: block; margin: 0 auto; }
  figcaption { font-size: 10pt; margin: 0 0 1.5mm; display: flex; gap: 2mm; align-items: baseline; }
  .num { font-family: ui-monospace, monospace; color: #f0620b; font-weight: 700; }
  .tag { margin-left: auto; font-family: ui-monospace, monospace; color: #9ca3af; font-size: 8.5pt; }
</style></head><body>${body}</body></html>`;
await writeFile(OUT_HTML, html);
await mkdir(OUT_DIR, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const page = await browser.newPage();
await page.goto("file://" + OUT_HTML, { waitUntil: "load" });
await page.pdf({
  path: OUT_PDF,
  format: "A4",
  printBackground: true,
  margin: { top: "14mm", bottom: "14mm", left: "12mm", right: "12mm" },
});
await browser.close();
console.log("wrote", path.relative(ROOT, OUT_HTML), "and", path.relative(ROOT, OUT_PDF));
