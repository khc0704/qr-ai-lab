import { describe, expect, it } from "vitest";
import { applyMarkdownTool } from "@/lib/markdown-tools";

describe("applyMarkdownTool", () => {
  it("bold wraps the selection and keeps it selected", () => {
    const r = applyMarkdownTool("bold", "ab cd", 3, 5);
    expect(r.text).toBe("ab **cd**");
    expect(r.text.slice(r.start, r.end)).toBe("cd");
  });

  it("bold without a selection inserts a placeholder to overtype", () => {
    const r = applyMarkdownTool("bold", "x", 1, 1);
    expect(r.text).toBe("x**粗體文字**");
    expect(r.text.slice(r.start, r.end)).toBe("粗體文字");
  });

  it("code uses backticks inline and a fence across lines", () => {
    expect(applyMarkdownTool("code", "run it", 0, 3).text).toBe("`run` it");
    expect(applyMarkdownTool("code", "a\nb", 0, 3).text).toBe("```\na\nb\n```");
    expect(applyMarkdownTool("code", "x\na\nb\ny", 2, 5).text).toBe("x\n```\na\nb\n```\ny");
  });

  it("link keeps the selection as the label and selects the url placeholder", () => {
    const r = applyMarkdownTool("link", "docs", 0, 4);
    expect(r.text).toBe("[docs](https://)");
    expect(r.text.slice(r.start, r.end)).toBe("https://");
  });

  it("list toggles '- ' on every selected line", () => {
    const on = applyMarkdownTool("list", "a\nb\nc", 0, 3);
    expect(on.text).toBe("- a\n- b\nc");
    expect(on.text.slice(on.start, on.end)).toBe("- a\n- b");
    const off = applyMarkdownTool("list", on.text, 0, 7);
    expect(off.text).toBe("a\nb\nc");
  });

  it("list on an empty first line places the caret after the marker", () => {
    const r = applyMarkdownTool("list", "\nx", 0, 0);
    expect(r.text).toBe("- \nx");
    expect(r.start).toBe(2);
    expect(r.end).toBe(2);
  });
});
