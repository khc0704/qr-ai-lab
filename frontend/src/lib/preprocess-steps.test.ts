import { describe, expect, it } from "vitest";
import {
  addColumnStep,
  changedCells,
  classifyOp,
  columnDiff,
  cropFromSteps,
  describeParams,
  moveStep,
  normalizeCropRect,
  opAppliesTo,
  removeStep,
  upsertStep,
} from "@/lib/preprocess-steps";
import type { PreprocessOp } from "@/types/domain";

const std: PreprocessOp = {
  id: "tabular.standardize",
  label: "標準化（z-score）",
  description: "",
  dataTypes: ["TABULAR"],
  params: [{ name: "columns", label: "欄位", type: "columns", default: [] }],
  geometric: false,
  fitted: true,
  dropsRows: false,
};
const impute: PreprocessOp = {
  ...std,
  id: "tabular.impute",
  label: "補值",
  params: [
    { name: "columns", label: "欄位", type: "columns", default: [] },
    { name: "strategy", label: "策略", type: "choice", default: "median", choices: ["median", "mean"] },
  ],
};
const dropDup: PreprocessOp = {
  ...std,
  id: "tabular.drop_duplicates",
  label: "刪除重複列",
  params: [],
  dropsRows: true,
};

describe("preprocess step helpers", () => {
  it("classifies column / row / other ops", () => {
    expect(classifyOp(std)).toBe("column");
    expect(classifyOp(dropDup)).toBe("row");
    expect(classifyOp({ ...std, params: [] })).toBe("other");
  });
  it("merges a column into the trailing step with the same op and params", () => {
    let steps = addColumnStep([], std, "x1");
    steps = addColumnStep(steps, std, "x2");
    expect(steps).toEqual([{ op: "tabular.standardize", params: { columns: ["x1", "x2"] } }]);
    // same column twice is a no-op
    expect(addColumnStep(steps, std, "x2")).toBe(steps);
    // different strategy → a new step
    steps = addColumnStep(steps, impute, "x1", { strategy: "mean" });
    steps = addColumnStep(steps, impute, "x2", { strategy: "median" });
    expect(steps.map((s) => s.params?.strategy)).toEqual([undefined, "mean", "median"]);
  });
  it("moves and removes steps", () => {
    const steps = [
      { op: "a", params: {} },
      { op: "b", params: {} },
      { op: "c", params: {} },
    ];
    expect(moveStep(steps, 2, 0).map((s) => s.op)).toEqual(["c", "a", "b"]);
    expect(moveStep(steps, 0, -1)).toBe(steps);
    expect(removeStep(steps, 1).map((s) => s.op)).toEqual(["a", "c"]);
  });
  it("describes params compactly", () => {
    expect(describeParams({ columns: ["a", "b"], strategy: "median" })).toBe("a, b · strategy=median");
    expect(describeParams({ columns: ["a", "b", "c", "d"] })).toBe("4 欄");
    expect(describeParams(undefined)).toBe("");
  });
  it("diffs cells by index only when the row count is unchanged", () => {
    const before = [
      { x: 1, y: "a" },
      { x: 2, y: null },
    ];
    const after = [
      { x: 1, y: "a" },
      { x: 2.5, y: "b" },
    ];
    expect([...changedCells(before, after, ["x", "y"])].sort()).toEqual(["1:x", "1:y"]);
    expect(changedCells(before, after.slice(0, 1), ["x"]).size).toBe(0);
  });
  it("offers column ops by dtype", () => {
    const text: PreprocessOp = { ...std, id: "text.lowercase", label: "轉小寫" };
    const encode: PreprocessOp = { ...std, id: "tabular.encode", label: "編碼" };
    expect(opAppliesTo(std, "number")).toBe(true);
    expect(opAppliesTo(std, "text")).toBe(false);
    expect(opAppliesTo(text, "text")).toBe(true);
    expect(opAppliesTo(text, "number")).toBe(false);
    expect(opAppliesTo(encode, "text")).toBe(true);
    expect(opAppliesTo(encode, "number")).toBe(false);
    expect(opAppliesTo(impute, "text")).toBe(true);
    expect(opAppliesTo(impute, undefined)).toBe(true);
  });
  it("reports added and dropped columns", () => {
    const col = (name: string) => ({
      name,
      dtype: "number" as const,
      missing: 0,
      missing_ratio: 0,
      unique: 1,
      top: [],
    });
    expect(columnDiff([col("a"), col("b")], [col("b"), col("b__x")])).toEqual({ added: ["b__x"], dropped: ["a"] });
  });
  it("turns a drag into crop ratios and upserts the crop step", () => {
    expect(normalizeCropRect(300, 50, 100, 250, 400, 300)).toEqual({
      left: 0.25,
      top: 0.167,
      right: 0.75,
      bottom: 0.833,
    });
    expect(normalizeCropRect(-20, 10, 900, 20, 400, 300)).toEqual({ left: 0, top: 0.033, right: 1, bottom: 0.067 });
    expect(normalizeCropRect(10, 10, 12, 200, 400, 300)).toBeNull();
    expect(normalizeCropRect(0, 0, 10, 10, 0, 0)).toBeNull();
    const crop: PreprocessOp = {
      ...std,
      id: "image.crop",
      label: "裁切",
      params: [
        { name: "left", label: "左", type: "float", default: 0 },
        { name: "top", label: "上", type: "float", default: 0 },
        { name: "right", label: "右", type: "float", default: 1 },
        { name: "bottom", label: "下", type: "float", default: 1 },
      ],
    };
    const rect = { left: 0.1, top: 0.2, right: 0.9, bottom: 0.8 };
    let steps = upsertStep([{ op: "image.grayscale", params: {} }], crop, rect);
    expect(steps.map((s) => s.op)).toEqual(["image.grayscale", "image.crop"]);
    expect(cropFromSteps(steps)).toEqual(rect);
    steps = upsertStep(steps, crop, { bottom: 0.5 });
    expect(steps).toHaveLength(2);
    expect(cropFromSteps(steps)).toEqual({ ...rect, bottom: 0.5 });
    expect(cropFromSteps([])).toBeNull();
  });
});
