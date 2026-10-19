// Pure helpers behind the spreadsheet-style preprocessing editor (unit-tested, no React).
import type { PreprocessOp, PreprocessStep, PreviewColumnStat } from "@/types/domain";

export type OpGroup = "column" | "row" | "other";

/** Column ops take a `columns` param and keep the rows; row ops drop or filter rows; the rest is generic. */
export function classifyOp(op: PreprocessOp): OpGroup {
  if (op.dropsRows) return "row";
  if (op.params.some((p) => p.name === "columns" && p.type === "columns")) return "column";
  return "other";
}

export function defaultParams(op: PreprocessOp): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const p of op.params) if (p.default !== undefined && p.default !== null) params[p.name] = p.default;
  return params;
}

function sameParamsExceptColumns(a: Record<string, unknown> | undefined, b: Record<string, unknown> | undefined) {
  const strip = (x: Record<string, unknown> | undefined) => {
    const copy = { ...(x ?? {}) };
    delete copy.columns;
    return JSON.stringify(copy, Object.keys(copy).sort());
  };
  return strip(a) === strip(b);
}

/**
 * Apply a column operation to one column: when the LAST step is the same op with identical other params, the
 * column is added to that step (so clicking 標準化 on three headers yields one step with three columns);
 * otherwise a new step is appended.
 */
export function addColumnStep(
  steps: PreprocessStep[],
  op: PreprocessOp,
  column: string,
  extra: Record<string, unknown> = {},
): PreprocessStep[] {
  const params = { ...defaultParams(op), ...extra, columns: [column] };
  const last = steps[steps.length - 1];
  if (last && last.op === op.id && sameParamsExceptColumns(last.params, params)) {
    const cols = Array.isArray(last.params?.columns) ? (last.params!.columns as string[]) : [];
    if (cols.includes(column)) return steps;
    return [...steps.slice(0, -1), { ...last, params: { ...(last.params ?? {}), columns: [...cols, column] } }];
  }
  return [...steps, { op: op.id, params }];
}

export function addStep(steps: PreprocessStep[], op: PreprocessOp, extra: Record<string, unknown> = {}) {
  return [...steps, { op: op.id, params: { ...defaultParams(op), ...extra } }];
}

export function moveStep(steps: PreprocessStep[], from: number, to: number): PreprocessStep[] {
  if (to < 0 || to >= steps.length || from === to) return steps;
  const copy = [...steps];
  const [s] = copy.splice(from, 1);
  copy.splice(to, 0, s);
  return copy;
}

export function removeStep(steps: PreprocessStep[], index: number): PreprocessStep[] {
  return steps.filter((_, i) => i !== index);
}

export function updateStepParams(
  steps: PreprocessStep[],
  index: number,
  params: Record<string, unknown>,
): PreprocessStep[] {
  return steps.map((s, i) => (i === index ? { ...s, params: { ...(s.params ?? {}), ...params } } : s));
}

/** Short human summary of a step's params for the chips: `columns` first, then the rest. */
export function describeParams(params: Record<string, unknown> | undefined): string {
  if (!params) return "";
  const parts: string[] = [];
  const cols = params.columns;
  if (Array.isArray(cols) && cols.length) parts.push(cols.length > 3 ? `${cols.length} 欄` : cols.join(", "));
  for (const [k, v] of Object.entries(params)) {
    if (k === "columns" || v === "" || v === undefined || v === null) continue;
    if (Array.isArray(v)) {
      if (v.length) parts.push(`${k}=${v.join("|")}`);
    } else parts.push(`${k}=${String(v)}`);
  }
  return parts.join(" · ");
}

export type CellKey = `${number}:${string}`;

/**
 * Cells whose value differs between the input sample and the pipeline output. Rows are matched by index, which
 * only makes sense when no step dropped or reordered rows, so the diff is empty when the row counts differ.
 */
export function changedCells(
  before: Record<string, unknown>[] | undefined,
  after: Record<string, unknown>[] | undefined,
  columns: string[],
): Set<CellKey> {
  const out = new Set<CellKey>();
  if (!before || !after || before.length !== after.length) return out;
  for (let i = 0; i < after.length; i++) {
    for (const c of columns) {
      if (!(c in before[i])) continue;
      if (!sameValue(before[i][c], after[i][c])) out.add(`${i}:${c}`);
    }
  }
  return out;
}

function sameValue(a: unknown, b: unknown): boolean {
  if ((a === null || a === undefined) && (b === null || b === undefined)) return true;
  if (typeof a === "number" && typeof b === "number")
    return Math.abs(a - b) < 1e-9 || (Number.isNaN(a) && Number.isNaN(b));
  return a === b;
}

export function columnDiff(
  before: PreviewColumnStat[] | null | undefined,
  after: PreviewColumnStat[] | null | undefined,
) {
  const b = new Set((before ?? []).map((c) => c.name));
  const a = new Set((after ?? []).map((c) => c.name));
  return {
    added: [...a].filter((c) => !b.has(c)),
    dropped: [...b].filter((c) => !a.has(c)),
  };
}

export function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return String(v);
    return Math.abs(v) >= 1000 ? v.toFixed(1) : v.toFixed(3);
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  const s = String(v);
  return s.length > 60 ? `${s.slice(0, 57)}…` : s;
}
