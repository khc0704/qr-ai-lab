// End-to-end walkthrough of the real frontend ↔ backend ↔ scheduler ↔ trainer stack, driven with Playwright.
// It logs in as `user` and `admin`, applies for projects, approves them, uploads data, trains (AutoML +
// manual), runs inference, exercises the discussion board and the admin console, and screenshots every step.
//
// Usage (all services already running — see docs/GETTING_STARTED.md):
//   BASE_URL=http://localhost:3000 API_URL=http://localhost:8000/api/v1 DATA_DIR=/path/to/datasets \
//   PHASES=all node scripts/e2e-walkthrough.mjs
// PHASES: comma list of request,approve,project,train,infer,iqa,spectrum,discussion,admin,visual,logout (or all).
// Output: ../docs/screenshots/e2e/NN-name.png + captions.json (+ state.json with the ids created).
import { chromium } from "playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const API = process.env.API_URL ?? "http://localhost:8000/api/v1";
const DATA = process.env.DATA_DIR ?? path.resolve("datasets");
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/screenshots/e2e");
const PHASES = (process.env.PHASES ?? "all").split(",");
const want = (p) => PHASES.includes("all") || PHASES.includes(p);
const VIEWPORT = { width: 1440, height: 900 };

await mkdir(OUT, { recursive: true });
const readJson = async (f, d) => {
  try {
    return JSON.parse(await readFile(path.join(OUT, f), "utf8"));
  } catch {
    return d;
  }
};
const state = await readJson("state.json", {});
const captions = await readJson("captions.json", []);
let n = Number(process.env.START_N ?? (captions.length ? Math.max(...captions.map((c) => c.n)) + 1 : 1));
let phase = "";
const saveMeta = async () => {
  await writeFile(path.join(OUT, "state.json"), JSON.stringify(state, null, 2));
  await writeFile(path.join(OUT, "captions.json"), JSON.stringify(captions, null, 2));
};

// --- helpers ---------------------------------------------------------------------------------------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(page, ms = 600) {
  await page.waitForLoadState("load").catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: 4000 }).catch(() => {});
  await page.waitForTimeout(ms);
}
async function shot(page, name, caption, opts = {}) {
  const file = `${String(n).padStart(2, "0")}-${name}.png`;
  const full = opts.fullPage ?? true;
  const vp = page.viewportSize();
  if (full && vp && vp.width >= 1024) {
    // The app shell has a fixed sidebar / sticky topbar, so a native full-page capture would paint them mid-page.
    // Grow the viewport to the document height instead and take a plain screenshot.
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.setViewportSize({ width: vp.width, height: Math.min(Math.max(h, vp.height), 3200) });
    await page.waitForTimeout(250);
    await page.screenshot({ path: path.join(OUT, file), fullPage: false, animations: "disabled" });
    await page.setViewportSize(vp);
  } else {
    await page.screenshot({ path: path.join(OUT, file), fullPage: false, animations: "disabled" });
  }
  const i = captions.findIndex((c) => c.file === file);
  const entry = { n, file, caption, phase, theme: opts.theme ?? "dark", viewport: opts.viewport ?? "desktop" };
  if (i >= 0) captions[i] = entry;
  else captions.push(entry);
  n += 1;
  console.log("  shot", file, "—", caption);
  await saveMeta();
}
async function pick(page, trigger, optionText) {
  await trigger.click();
  await page.getByRole("option", { name: optionText }).first().click();
}
async function fillNumber(page, selector, value) {
  await page.fill(selector, "");
  await page.fill(selector, String(value));
}
const errors = [];
function watch(page, label) {
  page.on("pageerror", (e) => errors.push(`${label} ${page.url()}: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/favicon|ERR_ABORTED/.test(m.text())) errors.push(`${label} ${page.url()}: ${m.text()}`);
  });
}

async function api(token, method, p, body, form) {
  const headers = { authorization: `Bearer ${token}` };
  let payload;
  if (form) payload = body;
  else if (body !== undefined) {
    headers["content-type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const r = await fetch(API + p, { method, headers, body: payload });
  const text = await r.text();
  if (!r.ok) throw new Error(`${method} ${p} → ${r.status} ${text}`);
  return text ? JSON.parse(text) : undefined;
}
async function login(username, password) {
  const r = await api(null, "POST", "/auth/login", { username, password });
  return r.access_token;
}
async function waitJob(token, id, terminal = ["succeeded", "failed", "cancelled"], timeoutMs = 600_000) {
  const t0 = Date.now();
  for (;;) {
    const j = await api(token, "GET", `/jobs/${id}`);
    if (terminal.includes(j.status)) return j;
    if (Date.now() - t0 > timeoutMs) throw new Error(`job ${id} still ${j.status} after ${timeoutMs}ms`);
    await sleep(1000);
  }
}
async function uiLogin(ctx, username, password) {
  const page = await ctx.newPage();
  watch(page, username);
  await page.goto(`${BASE}/login`);
  await settle(page);
  if (!page.url().includes("/login")) return page; // context already has a session cookie
  await page.fill("#username", username);
  await page.fill("#password", password);
  await page.getByRole("button", { name: "登入" }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
  await settle(page);
  return page;
}
async function goto(page, route, ms) {
  await page.goto(BASE + route);
  await settle(page, ms);
}

// --- datasets ---------------------------------------------------------------------------------------
const DS = {
  wat: path.join(DATA, "wat_yield.csv"),
  golden: path.join(DATA, "sem_golden_tool.zip"),
  tuned: path.join(DATA, "sem_tuned_tool.zip"),
  bad: path.join(DATA, "sem_bad_tool.zip"),
  spectra: path.join(DATA, "ocd_spectra.csv"),
};
const INLINE_ROWS = [
  { lot_id: "L25001", line: "A", vth_mv: 421.3, idsat_ua: 648.0, rs_ohm: 35.2, cd_nm: 28.1, thk_a: 52.3, temp_c: 23.1 },
  { lot_id: "L25002", line: "B", vth_mv: 405.8, idsat_ua: 690.5, rs_ohm: 34.1, cd_nm: 29.6, thk_a: 55.0, temp_c: 22.7 },
  { lot_id: "L25003", line: "C", vth_mv: 438.9, idsat_ua: 612.2, rs_ohm: 36.9, cd_nm: 26.9, thk_a: 49.8, temp_c: 23.4 },
  { lot_id: "L25004", line: "A", vth_mv: 419.0, idsat_ua: 655.3, rs_ohm: 35.0, cd_nm: 28.0, thk_a: 52.0, temp_c: 23.0 },
];

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const userCtx = await browser.newContext({ viewport: VIEWPORT, locale: "zh-TW", colorScheme: "light" });
const adminCtx = await browser.newContext({ viewport: VIEWPORT, locale: "zh-TW", colorScheme: "light" });
const adminTok = await login("admin", "admin1234");
const userTok = await login("user", "user1234");

try {
  // =====================================================================================================
  if (want("request")) {
    phase = "request";
    console.log("▶ request");
    // the lab's total pool (admin setting) bounds what a request may ask for
    await api(adminTok, "PUT", "/admin/settings/resource-pool", { gpu_indices: [], cpu_cores: 4, memory_mb: 12288, max_running_jobs: 1, allow_backfill: true });
    const page = await userCtx.newPage();
    watch(page, "user");
    await goto(page, "/login");
    await shot(page, "login", "登入頁：過渡期本地帳號（admin / user），Keycloak 之後接上", { fullPage: false });
    await page.fill("#username", "user");
    await page.fill("#password", "user1234");
    await shot(page, "login-filled", "以一般使用者 user 登入", { fullPage: false });
    await page.getByRole("button", { name: "登入" }).click();
    await page.waitForURL(`${BASE}/`);
    await settle(page);
    await shot(page, "home-user-empty", "一般使用者首頁：尚無專案、任務與申請（總資源池來自 backend /capacity）");
    await goto(page, "/project-requests");
    await shot(page, "requests-empty", "專案申請列表（空狀態）");
    await goto(page, "/project-requests/new");
    await shot(page, "request-form-empty", "新申請表單（結構化：題目、資料類型、任務、資料規模、資源需求、成員）");
    await page.fill("input[name=title]", "WAT 良率預測（Line A / B / C）");
    await page.fill(
      "textarea[name=purpose]",
      "用 WAT 電性參數（Vth、Idsat、Rs、CD、膜厚、量測溫度）預測 lot 良率，提前找出低良率 lot。\n\n目前以人工看 SPC 圖，希望 MAE < 1%。",
    );
    const combos = page.locator("button[role=combobox]");
    await pick(page, combos.nth(0), "表格");
    await pick(page, combos.nth(1), "迴歸");
    await pick(page, combos.nth(2), "極小（< 1k）");
    await page.fill("textarea[name=dataDescription]", "MES 匯出 CSV，約 480 筆 lot，9 欄；部分 Rs / 膜厚缺值。之後改由 MinIO 每週同步。");
    await fillNumber(page, "input[name=requestedGpu]", 0);
    await fillNumber(page, "input[name=requestedCpu]", 4);
    await fillNumber(page, "input[name=requestedMemoryMb]", 8192);
    await fillNumber(page, "input[name=requestedStorageMb]", 10240);
    await page.fill("input[name=proposedSlug]", "wat-yield-forecast");
    await shot(page, "request-form-filled", "填好的申請：表格 × 迴歸、0 GPU / 4 CPU / 8 GB、建議 slug");
    await page.getByRole("button", { name: "送出申請" }).click();
    await page.waitForURL(/\/project-requests\/\d+$/, { timeout: 30_000 });
    await settle(page);
    state.requestId = Number(page.url().split("/").pop());
    await shot(page, "request-submitted", "送出後的申請詳情（狀態 submitted，申請人可撤回或留言）");
    await page.getByPlaceholder(/回覆管理員|留言/).fill("資料已從 MES 匯出，約 480 筆 lot，本週內可提供。");
    await page.getByRole("button", { name: "送出" }).click();
    await settle(page, 1200);
    await shot(page, "request-comment", "申請討論串：申請人留言");
    await page.close();
  }

  // =====================================================================================================
  if (want("approve")) {
    phase = "approve";
    console.log("▶ approve");
    const page = await uiLogin(adminCtx, "admin", "admin1234");
    await shot(page, "home-admin", "管理員首頁：側欄顯示待審申請數、全站任務與資源池");
    await goto(page, "/admin/requests");
    await shot(page, "admin-requests", "管理員：申請審核列表");
    if (!state.requestId) {
      const list = await api(adminTok, "GET", "/project-requests?page_size=100");
      state.requestId = list.items[0].id;
    }
    await goto(page, `/project-requests/${state.requestId}`);
    await shot(page, "admin-request-detail", "管理員看申請詳情：右側審核面板");
    await page.getByRole("button", { name: "開始審核" }).click();
    await settle(page, 1200);
    await shot(page, "admin-request-in-review", "狀態變為 in_review，出現核准 / 退回按鈕");
    await page.getByRole("button", { name: "核准", exact: true }).click();
    await page.getByRole("dialog").waitFor();
    await page.fill("#slug", "wat-yield-forecast");
    await fillNumber(page, "#q-gpu", 0);
    await fillNumber(page, "#q-cpu", 4);
    await fillNumber(page, "#q-mem", 8192);
    await fillNumber(page, "#q-sto", 10240);
    await shot(page, "admin-approve-dialog", "核准對話框：指定 slug 與配額（GPU / CPU / Memory / Storage），不得超過總資源池", { fullPage: false });
    await page.getByRole("button", { name: "核准並建立" }).click();
    await settle(page, 1500);
    await shot(page, "admin-request-approved", "核准後：狀態 approved、專案已自動建立並連結");
    state.slug = "wat-yield-forecast";

    // two more projects for the image-quality and spectrum walkthroughs (created through the same API)
    for (const [key, body, approve] of [
      [
        "iqa",
        {
          title: "SEM 影像品質基準（golden tool vs 調機機台）",
          purpose: "用 golden 機台影像建立影像品質基準與浮動範圍，調機後比對其他機台是否一致。",
          data_type: "IMAGE",
          task_type: "anomaly_detection",
          data_scale: "tiny",
          data_description: "每台機台 10–40 張 SEM 影像（PNG，128×128）。",
          requested_gpu: 0,
          requested_cpu: 2,
          requested_memory_mb: 4096,
          requested_storage_mb: 5120,
          proposed_slug: "sem-image-quality",
        },
        { slug: "sem-image-quality", gpu_limit: 0, cpu_limit: 2, memory_limit_mb: 4096, storage_quota_mb: 5120 },
      ],
      [
        "spectrum",
        {
          title: "OCD 光譜鑑別器（Masked AutoEncoder）",
          purpose: "用正常 wafer 的 OCD 光譜訓練 MAE，重建誤差當異常分數，找出膜厚漂移的 wafer。",
          data_type: "SPECTRUM",
          task_type: "anomaly_detection",
          data_scale: "tiny",
          data_description: "寬表 CSV：每列一片 wafer，200 個波長（400–800 nm）。",
          requested_gpu: 0,
          requested_cpu: 2,
          requested_memory_mb: 4096,
          requested_storage_mb: 5120,
          proposed_slug: "ocd-spectrum",
        },
        { slug: "ocd-spectrum", gpu_limit: 0, cpu_limit: 2, memory_limit_mb: 4096, storage_quota_mb: 5120 },
      ],
    ]) {
      const existing = await api(adminTok, "GET", `/projects/${approve.slug}`).catch(() => null);
      if (existing) continue;
      const req = await api(userTok, "POST", "/project-requests", body);
      await api(adminTok, "POST", `/project-requests/${req.id}/review`);
      await api(adminTok, "POST", `/project-requests/${req.id}/approve`, { ...approve, review_note: "CPU 即可，先用小資料驗證流程。" });
      state[`${key}Request`] = req.id;
    }
    await goto(page, "/admin/requests");
    await shot(page, "admin-requests-after", "審核列表：三件申請都已核准");

    await goto(page, "/admin/quotas");
    await shot(page, "admin-quotas", "管理員：各專案配額一覽（合計超過資源池時提示；排程仍以資源池為準）");
    await goto(page, "/admin");
    await shot(page, "admin-dashboard-pool", "管理員 Dashboard：總資源池設定（所有專案合計可用的 GPU / CPU / Memory / 同時任務數）、節點狀態、佇列");
    await fillNumber(page, "input[name=memoryMb]", 14336);
    await fillNumber(page, "input[name=maxRunningJobs]", 2);
    await page.getByRole("button", { name: "儲存資源池" }).click();
    await page.getByRole("alertdialog").waitFor();
    await shot(page, "admin-pool-confirm", "更新總資源池前的確認（寫入 audit_logs）", { fullPage: false });
    await page.getByRole("button", { name: "確認更新" }).click();
    await settle(page, 1500);
    await shot(page, "admin-pool-saved", "總資源池已更新：14 GB、最多 2 個同時任務（寫入 audit_logs）");
    await goto(page, "/admin/users");
    await shot(page, "admin-users", "管理員：使用者列表（系統角色 admin / user、啟用狀態）");
    await page.close();
  }

  // =====================================================================================================
  if (want("project")) {
    phase = "project";
    console.log("▶ project");
    const slug = state.slug ?? "wat-yield-forecast";
    const page = await uiLogin(userCtx, "user", "user1234");
    await goto(page, "/projects");
    await shot(page, "projects", "專案列表：核准後自動建立的三個專案（配額、成員、最近任務）");
    await goto(page, `/projects/${slug}`);
    await shot(page, "project-overview", "專案總覽：配額用量、資料來源、最近任務、SOP 提示");
    await goto(page, `/projects/${slug}/members`);
    await page.getByRole("button", { name: "邀請成員" }).click();
    await page.getByRole("dialog").waitFor();
    await page.fill("#inv-email", "admin");
    await pick(page, page.getByRole("dialog").locator("button[role=combobox]"), "維護者");
    await shot(page, "members-invite", "邀請成員（帳號或 email + 專案角色）", { fullPage: false });
    await page.getByRole("dialog").getByRole("button").last().click();
    await settle(page, 1200);
    await shot(page, "members", "成員列表：擁有者 user、維護者 admin");
    await goto(page, `/projects/${slug}/data-sources`);
    await shot(page, "data-sources-empty", "資料來源（空）：本服務不保存資料，只記連線參考與加密憑證");
    await page.getByRole("button", { name: "新增資料來源" }).click();
    await page.getByRole("dialog").waitFor();
    await page.getByRole("tab", { name: "URL" }).click();
    await page.fill("#du-name", "mes-wat-export");
    await page.fill("#du-url", "http://127.0.0.1:8099/wat_yield.csv");
    await shot(page, "data-source-dialog", "新增 URL 資料來源（MinIO 分頁可填 endpoint / bucket / access key）", { fullPage: false });
    await page.getByRole("button", { name: "儲存並檢查連線" }).click();
    await settle(page, 2000);
    await shot(page, "data-sources", "資料來源列表：連線檢查結果、格式、最後檢查時間");
    await goto(page, `/projects/${slug}/settings`);
    await shot(page, "project-settings", "專案設定：名稱、描述、預設逾時；配額由管理員調整");
    await page.close();
  }

  // =====================================================================================================
  if (want("train")) {
    phase = "train";
    console.log("▶ train");
    const slug = state.slug ?? "wat-yield-forecast";
    const page = await uiLogin(userCtx, "user", "user1234");
    await goto(page, `/projects/${slug}/jobs`);
    await shot(page, "jobs-empty", "任務列表（空）");
    await goto(page, `/projects/${slug}/jobs/new`);
    await shot(page, "wizard-1-data", "建立訓練任務 ① 資料：一次性上傳 / 資料來源；上傳檔只存在於任務執行期間");
    await page.setInputFiles("[data-testid=upload-input]", DS.wat);
    await page.getByText("480 列").waitFor({ timeout: 30_000 });
    await settle(page);
    await shot(page, "wizard-1-uploaded", "CSV 上傳完成：backend 偵測到 480 列與欄位");
    await page.getByRole("button", { name: "下一步" }).click();
    await page.fill("#spec-target", "yield_pct");
    await page.fill("#spec-categorical", "line");
    await page.fill("#spec-id_column", "lot_id");
    await pick(page, page.getByRole("combobox", { name: "新增前處理步驟" }), "補值");
    await pick(page, page.getByRole("combobox", { name: "新增前處理步驟" }), "標準化（z-score）");
    await shot(page, "wizard-2-fields", "② 欄位與前處理：目標欄位 yield_pct、類別欄位 line、識別欄位 lot_id；加入「補值」與「標準化」兩個步驟");
    await page.getByRole("button", { name: "抽樣預覽" }).click();
    await page.getByText("處理後").first().waitFor({ timeout: 60_000 });
    await settle(page, 800);
    await shot(page, "wizard-2-preview", "抽樣預覽：從上傳檔取樣，顯示前處理「套用前 / 套用後」的統計與資料列");
    await page.getByRole("button", { name: "下一步" }).click();
    await settle(page, 300);
    await shot(page, "wizard-3-mode", "③ 模式：自動（AutoML）或手動");
    await page.getByRole("button", { name: "下一步" }).click();
    await fillNumber(page, "#trials", 6);
    await fillNumber(page, "#minutes", 10);
    await shot(page, "wizard-4-automl", "④ AutoML 候選模型與預算：XGBoost / 隨機森林 / 線性 / SVM，最多 6 個 trial");
    await page.getByRole("button", { name: "下一步" }).click();
    await fillNumber(page, "#r-gpu", 0);
    await fillNumber(page, "#r-cpu", 2);
    await fillNumber(page, "#r-mem", 2048);
    await fillNumber(page, "#r-to", 30);
    await shot(page, "wizard-5-resources", "⑤ 資源：GPU 0、CPU 2、2 GB、逾時 30 分鐘（不得超過專案配額）");
    await page.getByRole("button", { name: "下一步" }).click();
    await page.fill("#job-name", "automl-wat-yield-v1");
    await shot(page, "wizard-6-confirm", "⑥ 確認：送出後 API 回 202 建立 jobs row，由排程器依佇列執行");
    await page.getByRole("button", { name: "建立任務" }).click();
    await page.waitForURL(/\/jobs\/\d+$/, { timeout: 30_000 });
    state.trainJob = Number(page.url().split("/").pop());
    await settle(page, 500);
    await shot(page, "job-queued", "任務建立：狀態 queued（佇列位置、申請的資源）");
    await waitJob(userTok, state.trainJob, ["running", "succeeded", "failed"], 120_000);
    for (let i = 0; i < 20; i++) {
      const j = await api(userTok, "GET", `/jobs/${state.trainJob}`);
      if (j.progress > 0 || j.status !== "running") break;
      await sleep(500);
    }
    await sleep(1200);
    await shot(page, "job-running", "排程器啟動 trainer 後：running，進度卡由 SSE 即時更新");
    await page.getByRole("tab", { name: "Log" }).click();
    await sleep(4000);
    await shot(page, "job-log-live", "Log 分頁：trainer 的 log 透過 Redis stream → SSE 即時串流（含 [system] 行）");
    const done = await waitJob(userTok, state.trainJob);
    console.log("  train job", done.status);
    await sleep(2500);
    await goto(page, `/projects/${slug}/jobs/${state.trainJob}`, 1200);
    await shot(page, "job-succeeded", "訓練完成：最佳家族回填、指標卡、AutoML leaderboard（圖 + 表）");
    await page.getByRole("tab", { name: "Log" }).click();
    await settle(page, 300);
    await shot(page, "job-log-final", "完整 log（可複製 / 下載）");
    await page.getByRole("tab", { name: "產物" }).click();
    await settle(page, 300);
    await shot(page, "job-artifacts", "產物：模型、前處理狀態、指標；可下載或設為專案預設");
    await page.getByRole("tab", { name: "設定" }).click();
    await settle(page, 300);
    await shot(page, "job-config", "設定分頁：輸入規格（含前處理步驟）與搜尋設定");
    await goto(page, `/projects/${slug}/models`);
    await shot(page, "models", "模型頁：AutoML 最佳模型已登記為預設");
    await page.close();
  }

  // =====================================================================================================
  if (want("infer")) {
    phase = "infer";
    console.log("▶ infer");
    const slug = state.slug ?? "wat-yield-forecast";
    const page = await uiLogin(userCtx, "user", "user1234");
    await goto(page, `/projects/${slug}/jobs/new?kind=inference`);
    await shot(page, "infer-1-model", "建立推論任務 ① 模型：預設選專案的預設模型，列出支援的推論模式");
    await page.getByRole("button", { name: "下一步" }).click();
    await page.locator("textarea").first().fill(JSON.stringify(INLINE_ROWS, null, 1));
    await shot(page, "infer-2-input", "② 輸入：直接貼 JSON 列（也可上傳檔案或用資料來源），推論模式 predict");
    await page.getByRole("button", { name: "下一步" }).click();
    await fillNumber(page, "#r-gpu", 0);
    await fillNumber(page, "#r-cpu", 1);
    await fillNumber(page, "#r-mem", 2048);
    await page.getByRole("button", { name: "下一步" }).click();
    await page.fill("#job-name", "predict-new-lots");
    await page.getByRole("button", { name: "建立任務" }).click();
    await page.waitForURL(/\/jobs\/\d+$/, { timeout: 30_000 });
    state.inferJob = Number(page.url().split("/").pop());
    const done = await waitJob(userTok, state.inferJob);
    console.log("  infer job", done.status);
    await sleep(2500);
    await goto(page, `/projects/${slug}/jobs/${state.inferJob}`, 1200);
    await page.getByRole("tab", { name: "結果" }).click();
    await settle(page, 300);
    await shot(page, "infer-result", "推論結果：摘要、前 20 筆預覽（帶回 lot_id）、下載 CSV");
    await goto(page, `/projects/${slug}/jobs`);
    await shot(page, "jobs-list", "任務列表：訓練與推論都在 jobs 表，狀態、資源、耗時");
    await page.close();
  }

  // =====================================================================================================
  if (want("iqa")) {
    phase = "iqa";
    console.log("▶ iqa");
    const slug = "sem-image-quality";
    const page = await uiLogin(userCtx, "user", "user1234");
    await goto(page, `/projects/${slug}`);
    await shot(page, "iqa-project", "影像品質專案（IMAGE × 異常偵測）");
    if (!state.iqaTrainJob) {
    await goto(page, `/projects/${slug}/jobs/new`);
    await page.setInputFiles("[data-testid=upload-input]", DS.golden);
    await page.getByText("40 張影像").waitFor({ timeout: 60_000 });
    await settle(page);
    await shot(page, "iqa-upload", "上傳 golden 機台 40 張 SEM 影像（zip）");
    await page.getByRole("button", { name: "下一步" }).click();
    await settle(page, 300);
    await page.getByRole("button", { name: "下一步" }).click();
    await page.getByRole("button", { name: "手動" }).click();
    await page.getByRole("button", { name: "下一步" }).click();
    await page.getByRole("button", { name: "影像品質基準" }).click();
    await shot(page, "iqa-family", "手動選「影像品質基準」：17 個無參考 IQA 指標 → 中位數 / 浮動範圍 / Mahalanobis 門檻");
    await page.getByRole("button", { name: "下一步" }).click();
    await fillNumber(page, "#r-gpu", 0);
    await fillNumber(page, "#r-cpu", 1);
    await fillNumber(page, "#r-mem", 2048);
    await page.getByRole("button", { name: "下一步" }).click();
    await page.fill("#job-name", "golden-tool-baseline");
    await page.getByRole("button", { name: "建立任務" }).click();
    await page.waitForURL(/\/jobs\/\d+$/, { timeout: 30_000 });
    state.iqaTrainJob = Number(page.url().split("/").pop());
    const done = await waitJob(userTok, state.iqaTrainJob);
    console.log("  iqa train", done.status);
    await sleep(2500);
    await goto(page, `/projects/${slug}/jobs/${state.iqaTrainJob}`, 1200);
    await shot(page, "iqa-train-done", "基準建立完成：golden 影像數、驗證指標、產物");
    }
    // compare a tuned tool against the baseline
    await goto(page, `/projects/${slug}/jobs/new?kind=inference`);
    await pick(page, page.locator("#infer-mode"), "機台比對報告");
    await shot(page, "iqa-infer-model", "推論 ① 模型：影像品質基準模型支援 compare / score / embed，選「機台比對報告」");
    await page.getByRole("button", { name: "下一步" }).click();
    await page.getByRole("tab", { name: "一次性上傳" }).click();
    await page.setInputFiles("[data-testid=upload-input]", DS.tuned);
    await page.getByText("16 張影像").waitFor({ timeout: 60_000 });
    await shot(page, "iqa-infer-input", "推論 ② 輸入：上傳調機機台 16 張影像（zip）");
    await page.getByRole("button", { name: "下一步" }).click();
    await fillNumber(page, "#r-gpu", 0);
    await fillNumber(page, "#r-cpu", 1);
    await fillNumber(page, "#r-mem", 2048);
    await page.getByRole("button", { name: "下一步" }).click();
    await page.fill("#job-name", "compare-tool-b");
    await page.getByRole("button", { name: "建立任務" }).click();
    await page.waitForURL(/\/jobs\/\d+$/, { timeout: 30_000 });
    state.iqaCompareJob = Number(page.url().split("/").pop());
    const cmp = await waitJob(userTok, state.iqaCompareJob);
    console.log("  iqa compare", cmp.status);
    await sleep(2500);
    await goto(page, `/projects/${slug}/jobs/${state.iqaCompareJob}`, 1200);
    await page.getByRole("tab", { name: "結果" }).click();
    await settle(page, 300);
    await shot(page, "iqa-compare-result", "機台比對報告：整體判定 + 逐指標（golden 中位數 / 容許範圍 / 測試中位數 / 效應量 / KS p 值 / 判定）");
    await page.close();
  }

  // =====================================================================================================
  if (want("spectrum")) {
    phase = "spectrum";
    console.log("▶ spectrum");
    const slug = "ocd-spectrum";
    const page = await uiLogin(userCtx, "user", "user1234");
    if (!state.spectrumJob) {
    await goto(page, `/projects/${slug}/jobs/new`);
    await page.setInputFiles("[data-testid=upload-input]", DS.spectra);
    await page.getByText("264 列").waitFor({ timeout: 60_000 });
    await page.getByRole("button", { name: "下一步" }).click();
    await page.fill("#spec-label", "label");
    await pick(page, page.getByRole("combobox", { name: "新增前處理步驟" }), "SNV");
    await page.getByRole("button", { name: "抽樣預覽" }).click();
    await page.getByText("處理後").first().waitFor({ timeout: 60_000 });
    await settle(page, 800);
    await shot(page, "spectrum-preview", "光譜前處理預覽：SNV 標準化前後的曲線");
    await page.getByRole("button", { name: "下一步" }).click();
    await page.getByRole("button", { name: "手動" }).click();
    await page.getByRole("button", { name: "下一步" }).click();
    await page.getByRole("button", { name: "光譜 Masked AE" }).click();
    await page.fill("#p-epochs", "40");
    await shot(page, "spectrum-family", "手動選「光譜 Masked AE」，覆寫 epochs=40（CPU 上約 30 秒）");
    await page.getByRole("button", { name: "下一步" }).click();
    await fillNumber(page, "#r-gpu", 0);
    await fillNumber(page, "#r-cpu", 2);
    await fillNumber(page, "#r-mem", 2048);
    await page.getByRole("button", { name: "下一步" }).click();
    await page.fill("#job-name", "ocd-mae-v1");
    await page.getByRole("button", { name: "建立任務" }).click();
    await page.waitForURL(/\/jobs\/\d+$/, { timeout: 30_000 });
    state.spectrumJob = Number(page.url().split("/").pop());
    await waitJob(userTok, state.spectrumJob, ["running", "succeeded", "failed"], 120_000);
    await sleep(6000);
    await shot(page, "spectrum-running", "MAE 訓練中：epoch 進度與即時指標");
    const done = await waitJob(userTok, state.spectrumJob);
    console.log("  spectrum", done.status);
    await sleep(2500);
    await goto(page, `/projects/${slug}/jobs/${state.spectrumJob}`, 1200);
    await shot(page, "spectrum-done", "光譜鑑別器訓練完成：AUROC 等指標、重建誤差門檻");
    }
    await page.close();
  }

  // =====================================================================================================
  if (want("discussion")) {
    phase = "discussion";
    console.log("▶ discussion");
    const page = await uiLogin(userCtx, "user", "user1234");
    await goto(page, "/discussions");
    await shot(page, "discussions-empty", "討論區（獨立於專案申請）：問題 / 錯誤回報 / 功能建議");
    await goto(page, "/discussions/new");
    await pick(page, page.locator("button[role=combobox]").nth(0), "錯誤回報");
    await page.fill("input[name=title]", "推論結果 CSV 的 lot_id 欄位順序與輸入不同");
    await page.fill("textarea[name=body]", "重現步驟：\n1. 用 predict 模式推論 4 筆 inline 列\n2. 下載 predictions.csv\n\n預期：lot_id 在第一欄\n實際：lot_id 在最後一欄");
    await pick(page, page.locator("button[role=combobox]").nth(1), "WAT 良率預測");
    await shot(page, "issue-form", "新增問題單：類型、標題、內容（Markdown）、關聯專案");
    await page.getByRole("button", { name: "建立問題" }).click();
    await page.waitForURL(/\/discussions\/\d+$/, { timeout: 30_000 });
    state.issueId = Number(page.url().split("/").pop());
    await settle(page);
    await shot(page, "issue-open", "問題單詳情（open）");
    await page.close();

    const admin = await uiLogin(adminCtx, "admin", "admin1234");
    await goto(admin, `/discussions/${state.issueId}`);
    await admin.getByPlaceholder(/留言|回覆/).fill("已確認是輸出欄位依 dict 順序寫入；下個版本會把 id_column 固定放第一欄。");
    await admin.getByRole("button", { name: "送出" }).click();
    await settle(admin, 1200);
    await admin.getByRole("button", { name: "關閉問題" }).click();
    await admin.getByRole("dialog").waitFor();
    await admin.fill("#resolution", "已修正並排入下次部署（trainer 0.2）。");
    await shot(admin, "issue-close-dialog", "管理員關閉問題單並寫處理結果", { fullPage: false });
    await admin.getByRole("dialog").getByRole("button").last().click();
    await settle(admin, 1200);
    await shot(admin, "issue-closed", "已關閉的問題單：處理結果卡 + 管理員回覆");
    await goto(admin, "/discussions");
    await shot(admin, "discussions-list", "討論區列表：狀態、類型、關聯專案、回覆數");
    await admin.close();
  }

  // =====================================================================================================
  if (want("admin")) {
    phase = "admin";
    console.log("▶ admin");
    const slug = state.slug ?? "wat-yield-forecast";
    // a long AutoML job started by the user through the API, so the admin console has something to manage
    const fd = new FormData();
    fd.append("file", new Blob([await readFile(DS.wat)], { type: "text/csv" }), "wat_yield.csv");
    fd.append("format", "csv");
    const up = await api(userTok, "POST", `/projects/${slug}/uploads`, fd, true);
    const long = await api(userTok, "POST", `/projects/${slug}/jobs`, {
      kind: "train",
      name: "automl-wat-yield-long",
      input: { kind: "upload", upload_id: up.id, spec: { target: "yield_pct", categorical: "line", id_column: "lot_id" } },
      task_type: "regression",
      mode: "auto",
      config: { search: { candidates: ["tabular.xgboost", "tabular.random_forest", "tabular.svm"], max_trials: 60, time_budget_minutes: 30 } },
      requested_gpu: 0,
      requested_cpu: 2,
      requested_memory_mb: 2048,
      timeout_minutes: 60,
    });
    const second = await api(userTok, "POST", `/projects/${slug}/jobs`, {
      kind: "train",
      name: "rf-baseline-waiting",
      input: { kind: "data_source", data_source_id: (await api(userTok, "GET", `/projects/${slug}/data-sources`))[0]?.id, spec: { target: "yield_pct", categorical: "line", id_column: "lot_id" } },
      task_type: "regression",
      mode: "manual",
      model_family: "tabular.random_forest",
      config: { n_estimators: 300 },
      requested_gpu: 0,
      requested_cpu: 4,
      requested_memory_mb: 2048,
      timeout_minutes: 30,
    });
    state.longJob = long.id;
    state.waitingJob = second.id;
    await waitJob(adminTok, long.id, ["running", "succeeded", "failed"], 120_000);
    await sleep(3000);

    const page = await uiLogin(adminCtx, "admin", "admin1234");
    await goto(page, "/admin/queue", 1200);
    await shot(page, "admin-queue", "管理員佇列：執行中的 AutoML（階段、進度、分配的資源）與等待中的任務及等待原因（專案已達同時執行上限）");
    await page.getByRole("button", { name: "檢視" }).first().click();
    await page.getByRole("dialog").waitFor();
    await sleep(2500);
    await shot(page, "admin-queue-sheet", "任務抽屜：與專案頁共用的 JobStatusBar + LogViewer（即時 log）", { fullPage: false });
    await page.keyboard.press("Escape");
    await settle(page, 400);
    await page.getByRole("button", { name: "強制中斷" }).first().click();
    await page.getByRole("alertdialog").waitFor();
    await page.fill("#stop-reason", "讓位給上線前的回歸測試；AutoML 可之後再排。");
    await shot(page, "admin-force-stop", "強制中斷需要理由（寫入 audit_logs，並顯示給任務建立者）", { fullPage: false });
    await page.getByRole("alertdialog").getByRole("button", { name: "強制中斷" }).click();
    await settle(page, 1500);
    await waitJob(adminTok, long.id, ["cancelled", "failed", "succeeded"], 120_000);
    await waitJob(adminTok, second.id, ["running", "succeeded", "failed"], 120_000);
    await goto(page, "/admin/queue", 1500);
    await shot(page, "admin-queue-after", "中斷後：等待中的任務立刻取得資源開始執行");
    await goto(page, "/admin/audit");
    await shot(page, "admin-audit", "稽核紀錄：核准申請、更新資源池、強制中斷…都有操作者、對象與理由");
    await goto(page, "/admin");
    await shot(page, "admin-dashboard", "管理員儀表板：資源池用量、佇列、申請、近期任務");
    await page.close();

    const user = await uiLogin(userCtx, "user", "user1234");
    await goto(user, `/projects/${slug}/jobs/${long.id}`, 1200);
    await shot(user, "job-cancelled-by-admin", "使用者看到的被中斷任務：誰中斷、理由；log 保留");
    await waitJob(userTok, second.id);
    await goto(user, `/projects/${slug}/jobs`, 1200);
    await shot(user, "jobs-list-final", "任務列表：成功 / 已取消 / 推論任務一覽");
    await user.close();
  }

  // =====================================================================================================
  if (want("visual")) {
    phase = "visual";
    console.log("▶ visual");
    const slug = state.slug ?? "wat-yield-forecast";
    const dark = await browser.newContext({ viewport: VIEWPORT, locale: "zh-TW", colorScheme: "light" });
    await dark.addInitScript(() => {
      try {
        localStorage.setItem("theme", "light");
      } catch {}
    });
    const page = await uiLogin(dark, "user", "user1234");
    const darkShots = [
      ["/", "light-home", "Light mode：首頁"],
      [`/projects/${slug}`, "light-project", "Light mode：專案總覽"],
      [`/projects/${slug}/jobs/${state.trainJob}`, "light-job", "Light mode：AutoML 任務詳情（leaderboard）"],
      [`/projects/${slug}/jobs/new`, "light-wizard", "Light mode：建立任務精靈"],
    ];
    for (const [route, name, caption] of darkShots) {
      await goto(page, route, 800);
      await shot(page, name, caption, { theme: "light" });
    }
    await page.close();
    const adminDark = await browser.newContext({ viewport: VIEWPORT, locale: "zh-TW", colorScheme: "light" });
    await adminDark.addInitScript(() => {
      try {
        localStorage.setItem("theme", "light");
      } catch {}
    });
    const ap = await uiLogin(adminDark, "admin", "admin1234");
    await goto(ap, "/admin/queue", 800);
    await shot(ap, "light-admin-queue", "Light mode：管理員佇列", { theme: "light" });
    await ap.close();
    await adminDark.close();
    await dark.close();

    const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "zh-TW" });
    const mp = await uiLogin(mobile, "user", "user1234");
    await shot(mp, "mobile-home", "手機版首頁（側欄收成抽屜）", { viewport: "mobile", fullPage: false });
    await mp.getByRole("button", { name: /選單|Toggle Sidebar|sidebar/i }).first().click().catch(() => {});
    await settle(mp, 500);
    await shot(mp, "mobile-sidebar", "手機版側欄抽屜", { viewport: "mobile", fullPage: false });
    await mp.keyboard.press("Escape");
    await goto(mp, `/projects/${slug}/jobs/${state.trainJob}`, 800);
    await shot(mp, "mobile-job", "手機版任務詳情", { viewport: "mobile", fullPage: false });
    await mp.close();
    await mobile.close();
  }

  // =====================================================================================================
  if (want("logout")) {
    phase = "logout";
    console.log("▶ logout");
    const page = await uiLogin(userCtx, "user", "user1234");
    await page.getByRole("button", { name: /user|使用者/ }).last().click().catch(() => {});
    await settle(page, 300);
    await shot(page, "user-menu", "使用者選單：主題、登出", { fullPage: false });
    await page.getByRole("menuitem", { name: "登出" }).click();
    await page.waitForURL(/\/login/, { timeout: 30_000 });
    await settle(page);
    await shot(page, "logged-out", "登出後回到登入頁；受保護頁面由 proxy.ts 導向 /login?next=", { fullPage: false });
    await page.close();
  }
} finally {
  await saveMeta();
  await browser.close();
  if (errors.length) {
    console.log("\nconsole / page errors:");
    for (const e of errors) console.log(" -", e);
  }
}
console.log("done:", captions.length, "screenshots in", OUT);
