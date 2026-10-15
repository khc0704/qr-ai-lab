// Screenshots of every main page in dark and light mode, for design review and documentation.
// Usage: BASE_URL=http://localhost:3000 npm run screenshots   (server must already be running)
// Output: ../docs/screenshots/<name>.<theme>.png
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/screenshots");
const executablePath = process.env.CHROMIUM_PATH || undefined;

const pages = [
  ["home", "/"],
  ["discussions", "/discussions"],
  ["discussion-detail", "/discussions/56"],
  ["project-requests", "/project-requests"],
  ["project-request-new", "/project-requests/new"],
  ["project-request-detail", "/project-requests/40"],
  ["projects", "/projects"],
  ["project-overview", "/projects/demo-defect"],
  ["project-data-sources", "/projects/demo-defect/data-sources"],
  ["project-jobs", "/projects/demo-defect/jobs"],
  ["project-job-new", "/projects/demo-defect/jobs/new"],
  ["project-job-running", "/projects/demo-defect/jobs/128"],
  ["project-job-automl", "/projects/yield-forecast/jobs/126"],
  ["project-models", "/projects/demo-defect/models"],
  ["admin-dashboard", "/admin"],
  ["admin-queue", "/admin/queue"],
  ["admin-requests", "/admin/requests"],
  ["login", "/login"],
];
const lightSubset = new Set(["home", "project-job-running", "admin-dashboard", "project-request-new", "admin-queue"]);

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ executablePath });
const errors = [];
const watch = (page, label) => {
  page.on("console", (m) => { if (m.type() === "error") errors.push(`${label}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${label}: ${e.message}`));
};
try {
  for (const theme of ["dark", "light"]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: theme, locale: "zh-TW" });
    await context.addInitScript((t) => { try { localStorage.setItem("theme", t); } catch {} }, theme);
    const page = await context.newPage();
    watch(page, theme);
    for (const [name, route] of pages) {
      if (theme === "light" && !lightSubset.has(name)) continue;
      await page.goto(BASE + route, { waitUntil: "networkidle" });
      await page.waitForTimeout(400);
      const file = path.join(OUT, `${name}.${theme}.png`);
      await page.screenshot({ path: file, fullPage: true });
      console.log("saved", path.relative(process.cwd(), file));
    }
    await context.close();
  }
  // Mobile: home with the sidebar as off-canvas sheet trigger visible.
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "zh-TW" });
  const mp = await mobile.newPage();
  watch(mp, "mobile");
  await mp.goto(BASE + "/projects/demo-defect/jobs/128", { waitUntil: "networkidle" });
  await mp.waitForTimeout(400);
  await mp.screenshot({ path: path.join(OUT, "mobile-job.dark.png"), fullPage: false });
  console.log("saved mobile-job.dark.png");
  await mobile.close();
} finally {
  await browser.close();
}
if (errors.length) {
  console.log(`\n${errors.length} browser console error(s):`);
  for (const e of errors) console.log(" -", e.slice(0, 300));
} else {
  console.log("\nno browser console errors");
}
