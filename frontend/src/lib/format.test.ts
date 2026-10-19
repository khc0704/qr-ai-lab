import { describe, expect, it } from "vitest";
import { isEdited } from "@/lib/format";

describe("isEdited", () => {
  it("is false when the timestamps match, differ by less than the tolerance, or updated_at is missing", () => {
    expect(isEdited("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")).toBe(false);
    expect(isEdited("2026-01-01T00:00:00.000Z", "2026-01-01T00:00:00.400Z")).toBe(false);
    expect(isEdited("2026-01-01T00:00:00Z", undefined)).toBe(false);
    expect(isEdited("2026-01-01T00:00:00Z", "")).toBe(false);
  });

  it("is true once updated_at is clearly later", () => {
    expect(isEdited("2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")).toBe(true);
    expect(isEdited("2026-01-01T00:00:00Z", "2026-01-01T00:00:01.500Z")).toBe(true);
  });

  it("never reports an edit for unparsable input", () => {
    expect(isEdited("nope", "2026-01-01T00:05:00Z")).toBe(false);
  });
});
