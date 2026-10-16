import { describe, expect, it } from "vitest";
import { safeNext } from "@/lib/safe-next";

describe("safeNext", () => {
  it("keeps same-origin absolute paths, including query and hash", () => {
    expect(safeNext("/")).toBe("/");
    expect(safeNext("/projects/demo/jobs?page=2#log")).toBe("/projects/demo/jobs?page=2#log");
    expect(safeNext("  /admin ")).toBe("/admin");
  });

  it("rejects protocol-relative and backslash tricks", () => {
    expect(safeNext("//evil.com")).toBe("/");
    expect(safeNext("/\\evil.com")).toBe("/");
    expect(safeNext("/\\/evil.com")).toBe("/");
    expect(safeNext("\\\\evil.com")).toBe("/");
    expect(safeNext("/projects\\..\\x")).toBe("/");
  });

  it("rejects anything with a scheme or that is not a path", () => {
    expect(safeNext("http://evil.com")).toBe("/");
    expect(safeNext("https://evil.com/x")).toBe("/");
    expect(safeNext("javascript:alert(1)")).toBe("/");
    expect(safeNext("projects/demo")).toBe("/");
    expect(safeNext("")).toBe("/");
    expect(safeNext(null)).toBe("/");
    expect(safeNext(undefined)).toBe("/");
    expect(safeNext(42)).toBe("/");
    expect(safeNext("/%0d%0aSet-Cookie:x")).toBe("/%0d%0aSet-Cookie:x"); // encoded CR/LF is an inert path
    expect(safeNext("/a\nb")).toBe("/");
  });

  it("uses the given fallback", () => {
    expect(safeNext("//evil.com", "/login")).toBe("/login");
  });
});
