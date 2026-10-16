import { describe, expect, it } from "vitest";
import {
  iso,
  toComment,
  toDataSource,
  toIssue,
  toJob,
  toLogLines,
  toLogSnapshot,
  toPage,
  toProject,
  toRequest,
  toUser,
} from "@/lib/api/mappers";

const user = { id: 7, username: "alice", email: "a@x", display_name: null, role: "user", is_active: true };

const job = (over: Record<string, unknown>) => ({
  id: 1,
  project_id: 2,
  project_slug: "ws-alice",
  project_name: "alice 的工作區",
  kind: "train",
  name: "run",
  status: "queued",
  queue_rank: 10,
  requested_gpu: 0,
  requested_cpu: 2,
  requested_memory_mb: 4096,
  timeout_minutes: 60,
  progress: 12.6,
  input: { kind: "upload", format: "csv", spec: {} },
  created_by: user,
  created_at: "2026-10-16T01:02:03",
  ...over,
});

describe("toJob", () => {
  it("keeps every job kind, including the workspace tool kinds", () => {
    expect(toJob(job({ kind: "preprocess" })).kind).toBe("preprocess");
    expect(toJob(job({ kind: "analysis" })).kind).toBe("analysis");
    expect(toJob(job({ kind: "inference" })).kind).toBe("inference");
    expect(toJob(job({ kind: "train" })).kind).toBe("train");
  });
  it("passes an unknown kind / status through instead of collapsing it", () => {
    expect(toJob(job({ kind: "export" })).kind).toBe("export");
    expect(toJob(job({ status: "paused" })).status).toBe("paused");
  });
  it("defaults only when the field is missing", () => {
    expect(toJob(job({ kind: undefined })).kind).toBe("train");
    expect(toJob(job({ input: { format: "csv", spec: {} } })).input.kind).toBe("upload");
  });
  it("rounds progress, adds Z to naive timestamps and drops private metrics", () => {
    const j = toJob(
      job({
        metrics: {
          acc: 0.9,
          _internal: 1,
          leaderboard: [{ trial: 1, family: "tabular.linear", metric: 0.5, seconds: 3 }],
        },
      }),
    );
    expect(j.progress).toBe(13);
    expect(j.createdAt).toBe("2026-10-16T01:02:03Z");
    expect(j.metrics?.acc).toBe(0.9);
    expect(j.metrics?._internal).toBeUndefined();
    expect(j.metrics?.leaderboard?.[0]).toMatchObject({
      trial: 1,
      family: "tabular.linear",
      metric: 0.5,
      durationS: 3,
    });
  });
});

describe("enum pass-through", () => {
  it("toProject keeps unknown status / kind and defaults member roles only when missing", () => {
    const base = {
      id: 1,
      slug: "p",
      name: "P",
      description: "",
      data_type: "TABULAR",
      task_type: "classification",
      owner: user,
      created_at: "2026-01-01T00:00:00",
    };
    expect(toProject({ ...base, status: "archived", kind: "personal" })).toMatchObject({
      status: "archived",
      kind: "personal",
    });
    expect(toProject({ ...base, status: "frozen", kind: "shared" })).toMatchObject({
      status: "frozen",
      kind: "shared",
    });
    expect(toProject(base)).toMatchObject({ status: "active", kind: "standard" });
    expect(
      toProject({ ...base, members: [{ user, role: "maintainer", created_at: "2026-01-01T00:00:00" }] }).members[0]
        .role,
    ).toBe("maintainer");
  });
  it("toIssue / toRequest / toComment / toDataSource", () => {
    const issue = {
      id: 1,
      type: "bug",
      title: "t",
      body: "b",
      status: "closed",
      author: user,
      comment_count: 0,
      created_at: "2026-01-01T00:00:00",
    };
    expect(toIssue(issue)).toMatchObject({ type: "bug", status: "closed" });
    expect(toIssue({ ...issue, status: "triaged", type: "incident" })).toMatchObject({
      type: "incident",
      status: "triaged",
    });
    const req = {
      id: 1,
      applicant: user,
      title: "t",
      purpose: "p",
      data_type: "IMAGE",
      task_type: "detection",
      data_scale: "small",
      status: "in_review",
      members: [{ email: "a@x" }],
      submitted_at: "2026-01-01T00:00:00",
    };
    expect(toRequest(req)).toMatchObject({ status: "in_review", members: [{ email: "a@x", role: "member" }] });
    expect(
      toComment({
        id: 1,
        target_type: "issue",
        target_id: 1,
        kind: "system",
        body: "x",
        created_at: "2026-01-01T00:00:00",
      }).kind,
    ).toBe("system");
    expect(
      toDataSource({
        id: 1,
        project_id: 1,
        name: "d",
        kind: "minio",
        format: "csv",
        created_by: user,
        created_at: "2026-01-01T00:00:00",
      }).kind,
    ).toBe("minio");
  });
  it("toUser keeps least privilege for unknown system roles", () => {
    expect(toUser({ ...user, role: "superadmin" }).role).toBe("superadmin");
    expect(toUser({ ...user, role: "root" }).role).toBe("user");
    expect(toUser(user).displayName).toBe("alice");
  });
});

describe("logs and pages", () => {
  it("toLogLines parses level and timestamp, numbering from the offset", () => {
    const lines = toLogLines(["2026-10-16T01:02:03 [WARNING] careful", "plain text"], 10);
    expect(lines[0]).toEqual({ n: 11, ts: "2026-10-16T01:02:03Z", level: "WARN", text: "careful" });
    expect(lines[1]).toEqual({ n: 12, ts: "", level: "INFO", text: "plain text" });
  });
  it("toLogSnapshot carries the SSE cursor only when present", () => {
    expect(toLogSnapshot({ lines: ["a"], offset: 0, total: 1, last_event_id: "1700-3" })).toMatchObject({
      total: 1,
      lastEventId: "1700-3",
    });
    expect(toLogSnapshot({ lines: [], offset: 0, total: 0, last_event_id: null }).lastEventId).toBeUndefined();
    expect(toLogSnapshot({ lines: ["a"], offset: 4, total: 5 }).lines[0].n).toBe(5);
  });
  it("toPage maps items and reads page / page_size", () => {
    const page = toPage({ items: [{ id: 1 }, { id: 2 }], total: 41, page: 3, page_size: 20 }, (r) => Number(r.id));
    expect(page).toEqual({ items: [1, 2], total: 41, page: 3, pageSize: 20 });
    expect(toPage({ items: [] }, (r) => r)).toEqual({ items: [], total: 0, page: 1, pageSize: 20 });
  });
  it("iso leaves zoned timestamps alone", () => {
    expect(iso("2026-01-01T00:00:00+08:00")).toBe("2026-01-01T00:00:00+08:00");
    expect(iso("2026-01-01T00:00:00Z")).toBe("2026-01-01T00:00:00Z");
    expect(iso(undefined)).toBe("");
  });
});
