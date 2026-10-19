import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** Next.js 16 instant navigations: a page segment must not read uncached / runtime data (fetch, cookies, params)
 * directly in its default export, or client navigations to it block ("blocking-prerender-dynamic"). Pages put
 * that work in an inner async component rendered under <Suspense>; a parent layout's boundary does not count. */
function pages(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return pages(p);
    return name === "page.tsx" ? [p] : [];
  });
}

describe("app router pages stream their data", () => {
  const files = pages(join(__dirname));
  it("finds pages", () => expect(files.length).toBeGreaterThan(10));
  it.each(files)("%s has a sync default export", (file) => {
    const src = readFileSync(file, "utf8");
    expect(src).not.toMatch(/export default async function/);
    expect(src).toMatch(/<Suspense/);
  });
});
