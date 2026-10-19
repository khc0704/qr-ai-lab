// End-to-end walkthrough of the real frontend ↔ backend ↔ scheduler ↔ trainer stack, driven with Playwright.
// It logs in as `user` and `admin`, applies for projects, approves them, uploads data, trains (AutoML +
// manual), runs inference, exercises the discussion board and the admin console, and screenshots every step.
//
// Usage (all services already running — see docs/GETTING_STARTED.md):
//   BASE_URL=http://localhost:3000 API_URL=http://localhost:8000/api/v1 DATA_DIR=/path/to/datasets \
//   PHASES=all node scripts/e2e-walkthrough.mjs
// PHASES: comma list of request,approve,zoo,project,train,infer,iqa,spectrum,discussion,admin,visual,logout (or all).
// Output: ../docs/screenshots/e2e/NN-name.png + captions.json (+ state.json with the ids created).
import { chromium } from "playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const API = process.env.API_URL ?? "http://localhost:8000/api/v1";
const DATA = process.env.DATA_DIR ?? path.resolve("datasets");
const ZOO = process.env.ZOO_DIR ?? path.join(DATA, "zoo"); // yolov8n.pt for the browser-upload demo
const OUT =
  process.env.OUT_DIR ?? path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/screenshots/e2e");
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
    if (m.type() === "error" && !/favicon|ERR_ABORTED/.test(m.text()))
      errors.push(`${label} ${page.url()}: ${m.text()}`);
  });
  // Name the resource behind a "Failed to load resource" console error (the console message only has the page URL).
  page.on("response", (r) => {
    if (r.status() >= 400 && !/favicon/.test(r.url())) errors.push(`${label} ${page.url()}: ${r.status()} ${r.url()}`);
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
const superCtx = await browser.newContext({ viewport: VIEWPORT, locale: "zh-TW", colorScheme: "light" });
const superTok = await login("superadmin", "superadmin1234"); // resource pool, quotas, model zoo, roles, delete project
const adminTok = await login("admin", "admin1234"); // day-to-day: review, jobs, discussions
const userTok = await login("user", "user1234");

try {
  // =====================================================================================================
  if (want("request")) {
    phase = "request";
    console.log("▶ request");
    // the lab's total pool (admin setting) bounds what a request may ask for
    await api(superTok, "PUT", "/admin/settings/resource-pool", {
      gpu_indices: [],
      cpu_cores: 4,
      memory_mb: 12288,
      max_running_jobs: 1,
      allow_backfill: true,
      gpu_share: true,
    });
    const page = await userCtx.newPage();
    watch(page, "user");
    await goto(page, "/login");
    await shot(
      page,
      "login",
      "登入頁（AUTH_MODE=local）：開發環境用後端建立的本地帳號 superadmin / admin / user；正式環境改為 Keycloak 按鈕",
      { fullPage: false },
    );
    await page.fill("#username", "user");
    await page.fill("#password", "user1234");
    await shot(page, "login-filled", "以一般使用者 user 登入", { fullPage: false });
    await page.getByRole("button", { name: "登入" }).click();
    await page.waitForURL((u) => u.href.replace(/\/$/, "") === BASE.replace(/\/$/, "")); // home (with or without a base path)
    await settle(page);
    await shot(page, "home-user-empty", "一般使用者首頁：尚無專案、任務與申請（總資源池來自 backend /capacity）");
    await goto(page, "/projects");
    await shot(page, "requests-empty", "專案列表（空狀態）：申請與專案在同一頁，右上角「專案申請」");
    await goto(page, "/projects/new");
    await shot(
      page,
      "request-form-empty",
      "專案申請表單（題目與目的支援 Markdown、資料類型 / 任務、資源需求、以自動完成挑選成員）",
    );
    await page.fill("input[name=title]", "WAT 良率預測（Line A / B / C）");
    await page.fill(
      "textarea[name=purpose]",
      "用 WAT 電性參數（Vth、Idsat、Rs、CD、膜厚、量測溫度）預測 lot 良率，提前找出低良率 lot。\n\n目前以人工看 SPC 圖，希望 MAE < 1%。",
    );
    const combos = page.locator("button[role=combobox]");
    await pick(page, combos.nth(0), "表格");
    await pick(page, combos.nth(1), "迴歸");
    await pick(page, combos.nth(2), "極小（< 1k）");
    await page.fill(
      "textarea[name=dataDescription]",
      "MES 匯出 CSV，約 480 筆 lot，9 欄；部分 Rs / 膜厚缺值。之後改由 MinIO 每週同步。",
    );
    await fillNumber(page, "input[name=requestedGpu]", 0);
    await fillNumber(page, "input[name=requestedCpu]", 4);
    await fillNumber(page, "input[name=requestedMemoryMb]", 8192);
    await fillNumber(page, "input[name=requestedStorageMb]", 10240);
    await page.fill("input[name=proposedSlug]", "wat-yield-forecast");
    await shot(page, "request-form-filled", "填好的申請：表格 × 迴歸、0 GPU / 4 CPU / 8 GB、建議 slug");
    await page.getByRole("button", { name: "送出申請" }).click();
    await page.waitForURL(/\/projects\/wat-yield-forecast\/application$/, { timeout: 30_000 });
    await settle(page);
    state.slug = "wat-yield-forecast";
    await shot(page, "request-submitted", "送出後專案立刻以「申請中」建立，只有「申請」分頁；申請人可修改、撤回或留言");
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
    await goto(page, "/projects?status=pending");
    await shot(page, "admin-requests", "管理員：專案列表以「申請中 / 審核中」篩選，就是待審清單");
    state.slug = state.slug || "wat-yield-forecast";
    await goto(page, `/projects/${state.slug}/application`);
    await shot(page, "admin-request-detail", "管理員看申請分頁：右側審核面板");
    await page.getByRole("button", { name: "開始審核" }).click();
    await settle(page, 1200);
    await shot(page, "admin-request-in-review", "狀態變為 in_review，出現核准 / 退回按鈕");
    await page.getByRole("button", { name: "核准", exact: true }).click();
    await page.getByRole("dialog").waitFor();
    await fillNumber(page, "#q-gpu", 0);
    await fillNumber(page, "#q-cpu", 4);
    await fillNumber(page, "#q-mem", 8192);
    await fillNumber(page, "#q-storage", 10240);
    await shot(
      page,
      "admin-approve-dialog",
      "核准對話框：設定配額（GPU / CPU / Memory / Storage / 同時任務數）與要加入的成員，不得超過總資源池",
      { fullPage: false },
    );
    await page.getByTestId("approve-confirm").click();
    await settle(page, 1500);
    await shot(page, "admin-request-approved", "核准後：狀態「進行中」，其他分頁開放，申請分頁留作紀錄");

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
      const created = await api(userTok, "POST", "/projects", body);
      await api(adminTok, "POST", `/projects/${created.slug}/review`);
      const quota = Object.fromEntries(Object.entries(approve).filter(([k]) => k !== "slug"));
      await api(adminTok, "POST", `/projects/${created.slug}/approve`, {
        ...quota,
        review_note: "CPU 即可，先用小資料驗證流程。",
      });
      state[`${key}Slug`] = created.slug;
    }
    await goto(page, "/projects");
    await shot(page, "admin-requests-after", "專案列表：三件申請都已核准，變成進行中的專案");
    await page.close();
    // the total pool is superadmin territory (admin only reads it)
    const sa = await uiLogin(superCtx, "superadmin", "superadmin1234");
    await goto(sa, "/admin");
    await shot(
      sa,
      "admin-dashboard-pool",
      "superadmin 的 Dashboard：GPU 卡片、總資源池設定（所有專案合計可用的 GPU / CPU / Memory / 同時任務數、依顯存共用 GPU）、工具池配額、節點狀態、任務執行方式（runner）",
    );
    await goto(sa, `/projects/${state.slug}/settings`);
    await shot(
      sa,
      "admin-quotas",
      "superadmin 在專案「設定」分頁調整該專案的配額（合計超過資源池時提示；排程仍以資源池為準）",
    );
    // Back on the dashboard: the total resource pool lives there, project quotas live in each project's settings.
    await goto(sa, "/admin");
    await fillNumber(sa, "input[name=memoryMb]", 14336);
    await fillNumber(sa, "input[name=maxRunningJobs]", 2);
    await sa.getByRole("button", { name: "儲存資源池" }).click();
    await sa.getByRole("alertdialog").waitFor();
    await shot(sa, "admin-pool-confirm", "更新總資源池前的確認（寫入 audit_logs）", { fullPage: false });
    await sa.getByRole("button", { name: "確認更新" }).click();
    await settle(sa, 1500);
    await shot(sa, "admin-pool-saved", "總資源池已更新：14 GB、最多 2 個同時任務（寫入 audit_logs）");
    await sa.close();
  }

  // =====================================================================================================
  if (want("zoo")) {
    phase = "zoo";
    console.log("▶ zoo");
    const page = await uiLogin(superCtx, "superadmin", "superadmin1234");
    await goto(page, "/admin/model-zoo");
    await shot(
      page,
      "zoo-empty",
      "模型庫（superadmin 才能上傳 / 匯入 / 移除）：目錄需要的預訓練權重與狀態；伺服器不連外，權重由管理員帶進來",
    );
    // 1) browser upload
    await page.setInputFiles('[data-testid="zoo-upload-yolov8n"]', path.join(ZOO, "yolov8n.pt"));
    await page.getByText("yolov8n 已匯入模型庫").waitFor({ timeout: 120_000 });
    await settle(page, 1500);
    await shot(
      page,
      "zoo-uploaded",
      "從瀏覽器上傳 yolov8n.pt：寫進 MODEL_ZOO_ROOT、sha256 記進 manifest.json，狀態「已就緒」",
    );
    // 2) import from a folder mounted on the server (MODEL_ZOO_IMPORT_ROOT)
    await page.locator("tr", { hasText: "yolov8s.pt" }).getByRole("button", { name: "匯入" }).click();
    await page.getByRole("dialog").waitFor();
    await page.getByRole("tab", { name: "伺服器路徑" }).click();
    await page.fill("#zoo-path", "yolov8s.pt");
    await shot(page, "zoo-import-path", "從伺服器路徑匯入（NAS / USB 掛載點，限 MODEL_ZOO_IMPORT_ROOT 底下）", {
      fullPage: false,
    });
    await page.getByRole("button", { name: "開始匯入" }).click();
    await settle(page, 800);
    // 3) fetch from an intranet URL (host must be in MODEL_ZOO_ALLOWED_HOSTS)
    await page.locator("tr", { hasText: "yolov8n-cls.pt" }).getByRole("button", { name: "匯入" }).click();
    await page.getByRole("dialog").waitFor();
    await page.getByRole("tab", { name: "內網 URL" }).click();
    await page.fill("#zoo-url", "http://127.0.0.1:8099/yolov8n-cls.pt");
    await shot(page, "zoo-import-url", "從內網 URL 下載（公司鏡像 / 檔案伺服器；主機白名單）", { fullPage: false });
    await page.getByRole("button", { name: "開始匯入" }).click();
    for (let i = 0; i < 60; i++) {
      const rows = await api(adminTok, "GET", "/admin/model-zoo");
      const done = rows.filter((r) => ["yolov8s", "yolov8n-cls"].includes(r.id) && r.status === "present").length;
      if (done === 2) break;
      await sleep(1000);
    }
    await goto(page, "/admin/model-zoo?verify=1", 1500);
    await shot(
      page,
      "zoo-verified",
      "三種方式匯入後重新驗證 sha256：三個 YOLO 權重已就緒，來源與時間都有記錄；DINO / BERT 仍缺",
    );
    await goto(page, "/admin/audit");
    await shot(page, "zoo-audit", "稽核紀錄：模型庫的上傳 / 匯入都有操作者與來源");
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
    // UserPicker: a combobox that searches our own users table (Keycloak only supplies identity).
    await page.locator("#inv-user").click();
    await page.getByLabel("搜尋使用者").fill("adm");
    await page.getByRole("option", { name: /admin/ }).first().click();
    await pick(page, page.getByRole("dialog").locator("button[role=combobox]").last(), "維護者");
    await shot(
      page,
      "members-invite",
      "邀請成員：以自動完成搜尋帳號 / 姓名 / email（只列已登入過的使用者）+ 專案角色",
      {
        fullPage: false,
      },
    );
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
    await shot(page, "data-source-dialog", "新增 URL 資料來源（MinIO 分頁可填 endpoint / bucket / access key）", {
      fullPage: false,
    });
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
    await shot(
      page,
      "wizard-2-fields",
      "② 欄位與前處理：目標欄位 yield_pct、類別欄位 line、識別欄位 lot_id；加入「補值」與「標準化」兩個步驟",
    );
    await page.getByRole("button", { name: "抽樣預覽" }).click();
    await page.getByText("處理後").first().waitFor({ timeout: 60_000 });
    await page.getByTestId("preprocess-grid").waitFor({ timeout: 60_000 });
    await settle(page, 1200);
    await shot(
      page,
      "wizard-2-preview",
      "前處理編輯器（全寬 drawer）：試算表式預覽、欄位標頭的型別 / 缺值 / 操作選單、步驟串、變動的格子標色；每次變動即時重新抽樣",
    );
    await page.getByTestId("editor-done").click();
    await settle(page, 500);
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
    await shot(
      page,
      "job-running",
      "排程器以主機子程序啟動 trainer（trainer venv，CPU 核心 affinity、記憶體 watchdog）：running，進度卡由 SSE 即時更新",
    );
    await page.getByRole("tab", { name: "Log" }).click();
    await sleep(4000);
    await shot(
      page,
      "job-log-live",
      "Log 分頁：trainer 直接寫 log 檔，排程器 tail 後經 SSE 即時串流（[system] 行寫明 runner 與限制方式）",
    );
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
    await page
      .locator("textarea")
      .first()
      .fill(JSON.stringify(INLINE_ROWS, null, 1));
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
      await shot(
        page,
        "iqa-family",
        "手動選「影像品質基準」：17 個無參考 IQA 指標 → 中位數 / 浮動範圍 / Mahalanobis 門檻",
      );
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
    await shot(
      page,
      "iqa-infer-model",
      "推論 ① 模型：影像品質基準模型支援 compare / score / embed，選「機台比對報告」",
    );
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
    await shot(
      page,
      "iqa-compare-result",
      "機台比對報告：整體判定 + 逐指標（golden 中位數 / 容許範圍 / 測試中位數 / 效應量 / KS p 值 / 判定）",
    );
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
      await page.getByTestId("editor-done").click();
      await settle(page, 400);
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
    await page.fill(
      "textarea[name=body]",
      "重現步驟：\n1. 用 predict 模式推論 4 筆 inline 列\n2. 下載 predictions.csv\n\n預期：lot_id 在第一欄\n實際：lot_id 在最後一欄",
    );
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
    await admin
      .getByPlaceholder(/留言|回覆/)
      .fill("已確認是輸出欄位依 dict 順序寫入；下個版本會把 id_column 固定放第一欄。");
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
      input: {
        kind: "upload",
        upload_id: up.id,
        spec: { target: "yield_pct", categorical: "line", id_column: "lot_id" },
      },
      task_type: "regression",
      mode: "auto",
      config: {
        search: {
          candidates: ["tabular.xgboost", "tabular.random_forest", "tabular.svm"],
          max_trials: 60,
          time_budget_minutes: 30,
        },
      },
      requested_gpu: 0,
      requested_cpu: 2,
      requested_memory_mb: 2048,
      timeout_minutes: 60,
    });
    const second = await api(userTok, "POST", `/projects/${slug}/jobs`, {
      kind: "train",
      name: "rf-baseline-waiting",
      input: {
        kind: "data_source",
        data_source_id: (await api(userTok, "GET", `/projects/${slug}/data-sources`))[0]?.id,
        spec: { target: "yield_pct", categorical: "line", id_column: "lot_id" },
      },
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
    await shot(
      page,
      "admin-queue",
      "管理員佇列：執行中的 AutoML（階段、進度、分配的資源）與等待中的任務及等待原因（專案已達同時執行上限）",
    );
    await page.getByRole("button", { name: "檢視" }).first().click();
    await page.getByRole("dialog").waitFor();
    await sleep(2500);
    await shot(page, "admin-queue-sheet", "任務抽屜：與專案頁共用的 JobStatusBar + LogViewer（即時 log）", {
      fullPage: false,
    });
    await page.keyboard.press("Escape");
    await settle(page, 400);
    await page.getByRole("button", { name: "強制中斷" }).first().click();
    await page.getByRole("alertdialog").waitFor();
    await page.fill("#stop-reason", "讓位給上線前的回歸測試；AutoML 可之後再排。");
    await shot(page, "admin-force-stop", "強制中斷需要理由（寫入 audit_logs，並顯示給任務建立者）", {
      fullPage: false,
    });
    await page.getByRole("alertdialog").getByRole("button", { name: "強制中斷" }).click();
    await settle(page, 1500);
    await waitJob(adminTok, long.id, ["cancelled", "failed", "succeeded"], 120_000);
    await waitJob(adminTok, second.id, ["running", "succeeded", "failed"], 120_000);
    await goto(page, "/admin/queue", 1500);
    await shot(page, "admin-queue-after", "中斷後：等待中的任務立刻取得資源開始執行");
    await goto(page, "/admin/audit");
    await shot(page, "admin-audit", "稽核紀錄：核准申請、更新資源池、強制中斷…都有操作者、對象與理由");
    await goto(page, "/admin");
    await shot(
      page,
      "admin-dashboard",
      "admin 的儀表板：GPU 卡片、資源池（唯讀，只有 superadmin 能改）、節點狀態與「任務執行方式」",
    );
    // restart: a finished job is re-queued as a new job with the same input / settings (admin: jobs.control)
    await waitJob(adminTok, second.id);
    await goto(page, `/projects/${slug}/jobs/${second.id}`, 1200);
    await shot(
      page,
      "admin-job-actions",
      "管理員在任務頁多了「重新執行」「刪除」（執行中則是「強制中斷」）；一次性上傳的任務不能重新執行",
    );
    await page.getByTestId("admin-restart").click();
    await page.getByRole("alertdialog").waitFor();
    await page.getByRole("alertdialog").getByRole("button", { name: "重新排入佇列" }).click();
    await page.waitForURL((u) => /\/jobs\/\d+$/.test(u.pathname) && !u.pathname.endsWith(`/${second.id}`), {
      timeout: 30_000,
    });
    await settle(page, 1200);
    state.restartedJob = Number(page.url().split("/").pop());
    await shot(page, "admin-job-restarted", "重新執行 = 新任務（config.restarted_from 指向原任務），原任務與 log 保留");
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
  if (want("roles")) {
    phase = "roles";
    console.log("▶ roles");
    const sa = await uiLogin(superCtx, "superadmin", "superadmin1234");
    await goto(sa, "/admin/users");
    await shot(
      sa,
      "roles-users",
      "superadmin 的使用者頁：三種系統角色（superadmin / admin / user）的權限說明，可直接改角色與啟用",
    );
    const row = sa.locator("tr", { hasText: "一般使用者" });
    await row.getByRole("combobox").click();
    await sa.getByRole("option", { name: "管理員", exact: true }).click();
    await settle(sa, 1500);
    await shot(
      sa,
      "roles-promoted",
      "把 user 升為 admin：下一個請求就生效（後端每次都從 users 表讀角色），並寫入稽核紀錄",
    );
    await row.getByRole("combobox").click();
    await sa.getByRole("option", { name: "使用者", exact: true }).click();
    await settle(sa, 1200);
    await goto(sa, "/admin");
    await shot(
      sa,
      "roles-superadmin-dashboard",
      "superadmin 的儀表板：GPU 卡片有「重置」、資源池可編輯（含「依顯存共用 GPU」開關）",
    );
    // a throwaway project so the delete can be shown end to end
    const tmpReq = await api(userTok, "POST", "/projects", {
      title: "暫時專案（示範刪除）",
      purpose: "示範 superadmin 刪除專案：任務、產物、資料來源與資料夾一併移除。",
      data_type: "TABULAR",
      task_type: "classification",
      data_scale: "small",
      requested_gpu: 0,
      requested_cpu: 1,
      requested_memory_mb: 1024,
      requested_storage_mb: 1024,
      proposed_slug: "tmp-delete-demo",
      members: [],
    });
    await api(adminTok, "POST", `/projects/${tmpReq.slug}/review`);
    await api(adminTok, "POST", `/projects/${tmpReq.slug}/approve`, {
      gpu_limit: 0,
      cpu_limit: 1,
      memory_limit_mb: 1024,
      storage_quota_mb: 1024,
      max_concurrent_jobs: 1,
    });
    await goto(sa, "/projects/tmp-delete-demo/settings");
    await shot(sa, "roles-delete-project", "superadmin 的專案設定頁多了「刪除專案」（admin 只能封存）");
    await sa.getByTestId("delete-project").click();
    await sa.getByRole("alertdialog").waitFor();
    await sa.getByLabel("輸入 slug 確認").fill("tmp-delete-demo");
    await shot(
      sa,
      "roles-delete-confirm",
      "刪除要輸入 slug 確認；還有未結束任務時後端會拒絕（PROJECT_HAS_ACTIVE_JOBS）",
      { fullPage: false },
    );
    await sa.getByRole("alertdialog").getByRole("button", { name: "永久刪除" }).click();
    await sa.waitForURL(/\/projects$/, { timeout: 30_000 });
    await settle(sa, 1200);
    await shot(sa, "roles-deleted", "刪除後回到專案列表；稽核紀錄記下 slug 與刪掉的任務 / 產物數");
    await sa.close();

    const ad = await uiLogin(adminCtx, "admin", "admin1234");
    await goto(ad, `/projects/${state.slug}/settings`);
    await shot(
      ad,
      "roles-admin-quotas-readonly",
      "admin 看專案設定：沒有配額表單（quota.manage 由後端把關，前端只是不顯示）",
    );
    await goto(ad, "/admin/model-zoo");
    await shot(ad, "roles-admin-zoo-readonly", "admin 看模型庫：只有狀態，沒有上傳 / 匯入 / 移除");
    const tmpIssue = await api(userTok, "POST", "/issues", {
      type: "question",
      title: "（示範）這個討論串會被管理員刪除",
      body: "測試刪除討論串。",
    });
    await goto(ad, `/discussions/${tmpIssue.id}`);
    await ad.getByRole("button", { name: "刪除" }).click();
    await ad.getByRole("alertdialog").waitFor();
    await shot(ad, "roles-delete-issue", "admin 刪除討論串（連同留言）需確認；寫入稽核紀錄", { fullPage: false });
    await ad.getByRole("alertdialog").getByRole("button", { name: "刪除" }).click();
    await ad.waitForURL(/\/discussions$/, { timeout: 30_000 });
    await settle(ad, 1000);
    await shot(ad, "roles-issue-deleted", "刪除後回到討論區列表");
    await ad.close();

    const u = await uiLogin(userCtx, "user", "user1234");
    await goto(u, "/admin", 800);
    await shot(u, "roles-user-no-admin", "一般使用者沒有「管理」選單；直接打 /admin 得到 404（後端 API 也回 403）");
    await u.close();
  }

  // =====================================================================================================
  if (want("usage")) {
    phase = "usage";
    console.log("▶ usage");
    const sa = await uiLogin(superCtx, "superadmin", "superadmin1234");
    await goto(sa, "/admin/usage?range=1h", 1500);
    await shot(
      sa,
      "usage-1h",
      "資源使用率歷史（1 小時）：節點實際 CPU / 記憶體、配置給任務的量、GPU 使用率與顯存、執行中任務數；分母預設「資源池」",
    );
    await sa.getByRole("tab", { name: "系統總量" }).click();
    await settle(sa, 600);
    await shot(
      sa,
      "usage-node-denominator",
      "分母切成「系統總量」：虛線上限改為伺服器實際核數 / 記憶體；各專案占用也改以系統總量計算百分比",
    );
    await sa.getByRole("tab", { name: "專案配額" }).click();
    await settle(sa, 600);
    await shot(
      sa,
      "usage-quota-denominator",
      "分母「專案配額」：各專案的時間加權平均配置相對自己配額的百分比，以及實際量到的 CPU / 記憶體",
    );
    await sa.close();
  }

  // =====================================================================================================
  if (want("tool")) {
    phase = "tool";
    console.log("▶ tool");
    const page = await uiLogin(userCtx, "user", "user1234");
    await goto(page, "/tools");
    await shot(
      page,
      "tool-hub",
      "工具首頁：資料前處理與資料分析兩個不需專案的工具、公共工具池的配額與我目前的任務數、我的工具任務",
    );
    await goto(page, "/tools/preprocess");
    await shot(
      page,
      "tool-empty",
      "資料前處理服務：不需專案，上傳 → 選類型 → 挑步驟 → 即時抽樣預覽 → 建立任務（整檔處理在公共工具池排隊執行）；不保存資料",
    );
    await page.fill("#tool-spec-target", "yield_pct");
    await page.fill("#tool-spec-id_column", "lot_id");
    await page.setInputFiles('[data-testid="upload-input"]', DS.wat);
    await page.getByText("已上傳 wat_yield.csv").waitFor({ timeout: 60_000 });
    await settle(page, 800);
    await pick(page, page.getByRole("combobox", { name: "新增前處理步驟" }), "補值");
    await pick(page, page.getByRole("combobox", { name: "新增前處理步驟" }), "標準化（z-score）");
    await page.getByRole("button", { name: "抽樣預覽" }).click();
    await page.getByText("處理後").first().waitFor({ timeout: 60_000 });
    await page.getByTestId("preprocess-grid").waitFor({ timeout: 60_000 });
    await settle(page, 1200);
    await shot(
      page,
      "tool-preview",
      "上傳 WAT CSV、指定目標 / ID 欄位（受保護）、在試算表式編輯器加入補值與標準化：即時抽樣預覽、輸入 → 輸出列數、變動的格子標色",
    );
    await page.getByTestId("editor-done").click();
    await settle(page, 500);
    await shot(page, "tool-steps", "關閉編輯器後的摘要卡：步驟串、預覽的列數 / 欄數與警告數，隨時可再開啟");
    await page.getByTestId("tool-run").click();
    await page.getByText(/已建立前處理任務 #(\d+)/).waitFor({ timeout: 30_000 });
    await settle(page, 1500);
    await shot(
      page,
      "tool-queued",
      "建立後成為工具池裡的 preprocess 任務：進佇列、受工具池配額與每人上限限制，列表每 5 秒自動更新",
    );
    const mine = await api(userTok, "GET", "/tools/jobs");
    const pre = mine.find((j) => j.kind === "preprocess");
    state.toolJob = pre.id;
    const done = await waitJob(userTok, pre.id);
    if (done.status !== "succeeded") throw new Error(`preprocess job failed: ${done.error_message}`);
    await goto(page, `/tools/jobs/${pre.id}`, 1500);
    await shot(
      page,
      "tool-job-done",
      "前處理任務頁：和其他任務一樣有 log（含 limits: 實際核心 / 執行緒）、步驟、檔案與一次性的下載按鈕",
    );
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 60_000 }),
      page.getByTestId("tool-download").click(),
    ]);
    state.toolDownload = download.suggestedFilename();
    await settle(page, 2500);
    await goto(page, `/tools/jobs/${pre.id}`, 1200);
    await shot(
      page,
      "tool-downloaded",
      `下載 ${state.toolDownload}（processed.csv + pipeline.json + summary.json）後，結果檔立即從伺服器刪除；任務與 log 保留`,
    );
    await page.close();
  }

  // =====================================================================================================
  if (want("analyze")) {
    phase = "analyze";
    console.log("▶ analyze");
    const page = await uiLogin(userCtx, "user", "user1234");
    await goto(page, "/tools/analyze");
    await shot(
      page,
      "analyze-empty",
      "資料分析服務：表格資料探勘或影像品質分析，同樣以工具池的任務執行；只留報告不留資料",
    );
    await page.fill("#an-target", "yield_pct");
    await page.fill("#an-id", "lot_id");
    await page.setInputFiles('[data-testid="upload-input"]', DS.wat);
    await page.getByText("已上傳 wat_yield.csv").waitFor({ timeout: 60_000 });
    await page.getByTestId("analysis-run").click();
    await page.getByText(/已建立分析任務 #(\d+)/).waitFor({ timeout: 30_000 });
    await settle(page, 1000);
    const tab = (await api(userTok, "GET", "/tools/jobs")).find(
      (j) => j.kind === "analysis" && j.config?.analysis === "tabular_profile",
    );
    state.analysisTabular = tab.id;
    // image quality: three tools in three folders
    await page.getByTestId("analysis-image_quality").click();
    await page.setInputFiles('[data-testid="upload-input"]', path.join(DATA, "iqa_groups.zip"));
    await page.getByText("已上傳 iqa_groups.zip").waitFor({ timeout: 120_000 });
    await shot(
      page,
      "analyze-image-form",
      "影像品質分析：zip 的子資料夾（golden / tuned / bad 三台機台）就是群組；可選 DINOv2 embedding（沒有 GPU 配額時自動改用 IQA 指標向量）",
    );
    await page.getByTestId("analysis-run").click();
    await page.getByText(/已建立分析任務 #(\d+)/).waitFor({ timeout: 30_000 });
    await settle(page, 1500);
    await shot(page, "analyze-queued", "兩個分析任務排隊中（工具池每人同時最多 2 個）");
    const img = (await api(userTok, "GET", "/tools/jobs")).find(
      (j) => j.kind === "analysis" && j.config?.analysis === "image_quality",
    );
    state.analysisImage = img.id;
    const t = await waitJob(userTok, tab.id);
    if (t.status !== "succeeded") throw new Error(`tabular analysis failed: ${t.error_message}`);
    await goto(page, `/tools/jobs/${tab.id}`, 1500);
    await shot(
      page,
      "analyze-tabular-report",
      "表格資料探勘報告：建議（共線、缺值、解釋力、模型選擇）、對目標的解釋力（互資訊 + 相關性 + 置換重要度）、相關矩陣與 VIF、欄位概況",
    );
    const i = await waitJob(userTok, img.id);
    if (i.status !== "succeeded") throw new Error(`image analysis failed: ${i.error_message}`);
    await goto(page, `/tools/jobs/${img.id}`, 1500);
    await shot(
      page,
      "analyze-image-report",
      "影像品質分析報告：三台機台最會飄的 IQA 指標（飄移比、p 值、各群組中位數）、embedding PCA 散佈與群組相似度、偏離群組的影像、建議",
    );
    await page.close();
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
    const ap = await uiLogin(adminDark, "superadmin", "superadmin1234");
    await goto(ap, "/admin/queue", 800);
    await shot(ap, "light-admin-queue", "Light mode：管理員佇列", { theme: "light" });
    await goto(ap, "/admin/usage", 800);
    await shot(ap, "light-usage", "Light mode：資源使用率歷史", { theme: "light" });
    await ap.close();
    await adminDark.close();
    await dark.close();

    const mobile = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 2,
      isMobile: true,
      hasTouch: true,
      locale: "zh-TW",
    });
    const mp = await uiLogin(mobile, "user", "user1234");
    await shot(mp, "mobile-home", "手機版首頁（側欄收成抽屜）", { viewport: "mobile", fullPage: false });
    await mp
      .getByRole("button", { name: /選單|Toggle Sidebar|sidebar/i })
      .first()
      .click()
      .catch(() => {});
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
    await page
      .getByRole("button", { name: /user|使用者/ })
      .last()
      .click()
      .catch(() => {});
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
