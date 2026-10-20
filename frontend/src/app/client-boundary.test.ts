import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** A value exported from a "use client" module reaches a Server Component as a client reference, not the value:
 * calling it or reading it throws at render time ("Attempted to call X() from the server but X is on the client",
 * "X.has is not a function"). Server files may import components (PascalCase) from client modules; shared
 * constants and helpers belong in a plain module (src/lib/*). */
const SRC = resolve(__dirname, "..");
const EXT = [".tsx", ".ts", "/index.tsx", "/index.ts"];

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "node_modules" ? [] : files(p);
    return /\.(tsx|ts)$/.test(name) && !/\.test\.tsx?$/.test(name) && !name.endsWith(".d.ts") ? [p] : [];
  });
}

function isClientModule(src: string): boolean {
  const head = src.replace(/^\s*(\/\/[^\n]*\n|\/\*[\s\S]*?\*\/\s*)*/, "");
  return /^["']use client["']/.test(head);
}

function resolveImport(from: string, spec: string): string | null {
  const base = spec.startsWith("@/")
    ? join(SRC, spec.slice(2))
    : spec.startsWith(".")
      ? join(dirname(from), spec)
      : null;
  if (!base) return null;
  for (const ext of ["", ...EXT]) {
    const p = base + ext;
    try {
      if (statSync(p).isFile()) return p;
    } catch {
      /* try the next extension */
    }
  }
  return null;
}

describe("server modules import only components from client modules", () => {
  const all = files(SRC);
  const client = new Set(all.filter((f) => isClientModule(readFileSync(f, "utf8"))));
  it("finds client modules", () => expect(client.size).toBeGreaterThan(10));
  it("no server file imports a non-component value from a client module", () => {
    const violations: string[] = [];
    for (const file of all) {
      if (client.has(file)) continue;
      const src = readFileSync(file, "utf8");
      for (const m of src.matchAll(/import\s+(type\s+)?\{([^}]*)\}\s+from\s+["']([^"']+)["']/g)) {
        if (m[1]) continue; // type-only import
        const target = resolveImport(file, m[3]);
        if (!target || !client.has(target)) continue;
        for (const raw of m[2].split(",")) {
          const name = raw.trim().replace(/\s+as\s+.*$/, "");
          if (!name || name.startsWith("type ")) continue;
          if (!/^[A-Z]/.test(name)) violations.push(`${file.replace(SRC, "src")} imports ${name} from ${m[3]}`);
        }
      }
    }
    expect(violations, "move the value to a plain module under src/lib").toEqual([]);
  });
});
