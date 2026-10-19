// Pure text transforms behind the MarkdownEditor toolbar: each rewrites the current selection of the source
// and says where the caret should land afterwards. Client-safe and DOM-free (unit-tested in markdown-tools.test.ts).
import { markdownCopy } from "@/i18n/zh-TW";

export type MarkdownTool = "bold" | "list" | "code" | "link";

export interface ToolResult {
  text: string;
  /** New selection; `start === end` for a bare caret. */
  start: number;
  end: number;
}

function wrap(
  text: string,
  start: number,
  end: number,
  before: string,
  after: string,
  placeholder: string,
): ToolResult {
  const inner = text.slice(start, end) || placeholder;
  const s = start + before.length;
  return { text: text.slice(0, start) + before + inner + after + text.slice(end), start: s, end: s + inner.length };
}

/** Apply a toolbar action to `text` with the selection `[start, end)`. */
export function applyMarkdownTool(tool: MarkdownTool, text: string, start: number, end: number): ToolResult {
  switch (tool) {
    case "bold":
      return wrap(text, start, end, "**", "**", markdownCopy.boldPlaceholder);
    case "code": {
      const selected = text.slice(start, end);
      if (!selected.includes("\n")) return wrap(text, start, end, "`", "`", markdownCopy.codePlaceholder);
      // Multi-line selection → fenced block on its own lines.
      const before = (start === 0 || text[start - 1] === "\n" ? "" : "\n") + "```\n";
      const after = "\n```" + (end === text.length || text[end] === "\n" ? "" : "\n");
      return wrap(text, start, end, before, after, "");
    }
    case "link": {
      const label = text.slice(start, end) || markdownCopy.linkText;
      const url = markdownCopy.linkUrl;
      const s = start + label.length + 3; // "[" + label + "]("
      return { text: `${text.slice(0, start)}[${label}](${url})${text.slice(end)}`, start: s, end: s + url.length };
    }
    case "list": {
      // Toggle "- " on every line the selection touches.
      const lineStart = start === 0 ? 0 : text.lastIndexOf("\n", start - 1) + 1;
      const nl = text.indexOf("\n", end);
      const lineEnd = nl === -1 ? text.length : nl;
      const lines = text.slice(lineStart, lineEnd).split("\n");
      const listed = lines.every((l) => /^\s*- /.test(l));
      const next = lines.map((l) => (listed ? l.replace(/^(\s*)- /, "$1") : `- ${l}`)).join("\n");
      const caretOnly = start === end && lines.length === 1;
      return {
        text: text.slice(0, lineStart) + next + text.slice(lineEnd),
        start: caretOnly ? lineStart + next.length : lineStart,
        end: lineStart + next.length,
      };
    }
  }
}
