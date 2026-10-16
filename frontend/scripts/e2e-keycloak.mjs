// Keycloak-mode walkthrough: run against a frontend + backend started with AUTH_MODE=keycloak (a fake or real
// realm). Appends screenshots / captions to docs/screenshots/e2e like e2e-walkthrough.mjs.
//
//   CHROMIUM_PATH=/opt/pw-browsers/chromium BASE_URL=http://127.0.0.1:3000 node scripts/e2e-keycloak.mjs
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/screenshots/e2e");
const VIEWPORT = { width: 1440, height: 900 };
await mkdir(OUT, { recursive: true });
const readJson = async (f, d) => {
  try {
    return JSON.parse(await readFile(path.join(OUT, f), "utf8"));
  } catch {
    return d;
  }
};
const captions = await readJson("captions.json", []);
let n = Number(process.env.START_N ?? (captions.length ? Math.max(...captions.map((c) => c.n)) + 1 : 1));
const phase = "keycloak";
const saveMeta = async () => writeFile(path.join(OUT, "captions.json"), JSON.stringify(captions, null, 2));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(page, ms = 600) {
  await page.waitForLoadState("load").catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: 4000 }).catch(() => {});
  await page.waitForTimeout(ms);
}
async function shot(page, name, caption, opts = {}) {
  const file = `${String(n).padStart(2, "0")}-${name}.png`;
  const vp = page.viewportSize();
  if ((opts.fullPage ?? true) && vp) {
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.setViewportSize({ width: vp.width, height: Math.min(Math.max(h, vp.height), 3200) });
    await page.waitForTimeout(250);
    await page.screenshot({ path: path.join(OUT, file), animations: "disabled" });
    await page.setViewportSize(vp);
  } else await page.screenshot({ path: path.join(OUT, file), animations: "disabled" });
  const entry = { n, file, caption, phase, theme: "dark", viewport: "desktop" };
  const i = captions.findIndex((c) => c.file === file);
  if (i >= 0) captions[i] = entry;
  else captions.push(entry);
  n += 1;
  console.log("  shot", file, "—", caption);
  await saveMeta();
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const errors = [];
async function kcLogin(ctx, username) {
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`${username}: ${e.message}`));
  await page.goto(`${BASE}/login`);
  await settle(page);
  return page;
}
try {
  const ctx = await browser.newContext({ viewport: VIEWPORT, locale: "zh-TW", colorScheme: "light" });
  const page = await kcLogin(ctx, "superadmin");
  await shot(
    page,
    "kc-login",
    "AUTH_MODE=keycloak 的登入頁：只有「使用公司帳號登入（Keycloak）」按鈕（AUTH_LOCAL_FALLBACK=1 時多一個摺疊的本地表單）",
    { fullPage: false },
  );
  await page.getByRole("button", { name: /Keycloak/ }).click();
  await page.waitForURL(/openid-connect\/auth/, { timeout: 30_000 });
  await settle(page);
  await shot(
    page,
    "kc-realm-login",
    "Auth.js 帶著 PKCE + state 把瀏覽器導到 realm 的登入頁（這裡是模擬的 Keycloak；正式環境是公司 SSO）",
    { fullPage: false },
  );
  await page.selectOption("#username", "superadmin");
  await page.getByRole("button", { name: "登入" }).click();
  await page.waitForURL((u) => u.origin === new URL(BASE).origin && !u.pathname.startsWith("/login"), {
    timeout: 60_000,
  });
  await settle(page, 1200);
  await shot(
    page,
    "kc-home-superadmin",
    "回到首頁：Keycloak 的 superadmin realm role 經 KEYCLOAK_ROLE_MAP 對應成系統角色 superadmin；同名的本地帳號被接管（auth_provider=keycloak）",
  );
  await page.goto(`${BASE}/admin/users`);
  await settle(page, 1000);
  await shot(
    page,
    "kc-users",
    "使用者頁：Keycloak 登入過的帳號標記 keycloak；角色仍可在這裡調整（token 沒帶對應 role 時以這裡為準）",
  );
  await page.getByRole("button", { name: /使用者選單/ }).click();
  await settle(page, 300);
  await page.getByRole("menuitem", { name: "登出" }).click();
  await page.waitForURL(/\/login/, { timeout: 60_000 });
  await settle(page);
  await shot(
    page,
    "kc-logged-out",
    "登出：清掉 Auth.js session cookie，並導到 Keycloak 的 end-session（id_token_hint）結束 SSO，再回到 /login",
    { fullPage: false },
  );
  await page.close();
  await ctx.close();

  const ctx2 = await browser.newContext({ viewport: VIEWPORT, locale: "zh-TW", colorScheme: "light" });
  const p2 = await kcLogin(ctx2, "alice");
  await p2.getByRole("button", { name: /Keycloak/ }).click();
  await p2.waitForURL(/openid-connect\/auth/, { timeout: 30_000 });
  await p2.selectOption("#username", "alice");
  await p2.getByRole("button", { name: "登入" }).click();
  await p2.waitForURL((u) => u.origin === new URL(BASE).origin && !u.pathname.startsWith("/login"), {
    timeout: 60_000,
  });
  await settle(p2, 1200);
  await shot(
    p2,
    "kc-home-alice",
    "第一次登入的新帳號 alice：users 表自動建立；她的 client role qr-admin 對應到 admin（KEYCLOAK_ROLE_MAP=…,qr-admin:admin），所以看得到「管理」選單",
  );
  await p2.goto(`${BASE}/admin`);
  await settle(p2, 1000);
  await shot(p2, "kc-alice-admin", "alice（admin）的儀表板：資源池唯讀、GPU 卡片沒有重置按鈕");
  await p2.close();
  await ctx2.close();
  await sleep(300);
} finally {
  await saveMeta();
  await browser.close();
  if (errors.length) {
    console.log("\npage errors:");
    for (const e of errors) console.log(" -", e);
  }
}
console.log("done:", captions.length, "captions in", OUT);
