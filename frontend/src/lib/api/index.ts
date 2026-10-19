// Server-only data access layer: every read the pages need, as fetches against the backend.
// Pages must only import from here (never call fetch themselves) so the mapping lives in one place.
import "server-only";

import { apiFetch } from "@/lib/backend";
import {
  toArtifact,
  toAudit,
  toCapacity,
  toComment,
  toDataSource,
  toIssue,
  toJob,
  toLogSnapshot,
  toNode,
  toPage,
  toPool,
  toPreprocessOp,
  toProject,
  toToolPool,
  toToolPoolStatus,
  toUsageHistory,
  toUser,
  toUserLookup,
  toZooEntry,
  toZooTask,
} from "@/lib/api/mappers";
import type {
  Artifact,
  AuditLog,
  Capacity,
  Catalog,
  Comment,
  CommentTarget,
  DataSource,
  DataType,
  Issue,
  Job,
  JobLogSnapshot,
  ModelZooEntry,
  NodeStatus,
  Page,
  PreprocessOp,
  Project,
  ResourcePool,
  ToolPool,
  ToolPoolStatus,
  UsageHistory,
  UsageRange,
  User,
  UserLookup,
  ZooTask,
} from "@/types/domain";

type J = Record<string, unknown>;

/** Backend list endpoints cap page_size at 100 (audit: 200). */
export const DEFAULT_PAGE_SIZE = 20;
const clampPage = (n: number | undefined) => (Number.isFinite(n) && (n as number) >= 1 ? Math.floor(n as number) : 1);

const q = (params: Record<string, string | number | boolean | undefined>) => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
};

// --- projects --------------------------------------------------------------------------------------

/** Projects the user is a member of (admins: all), pending applications included; omit `status` for everything
 * except archived. `status: ["pending"]` covers pending + in_review. */
export async function listProjects(opts?: {
  status?: (Project["status"] | "pending")[];
  q?: string;
}): Promise<Project[]> {
  return (await apiFetch<J[]>(`/projects${q({ status: opts?.status?.join(","), q: opts?.q })}`)).map(toProject);
}

// --- standalone tools (shared tool pool) -----------------------------------------------------------

export async function getToolPoolStatus(): Promise<ToolPoolStatus> {
  return toToolPoolStatus(await apiFetch<J>("/tools/pool"));
}

export async function listToolJobs(): Promise<Job[]> {
  return (await apiFetch<J[]>("/tools/jobs")).map(toJob);
}

export async function getToolPool(): Promise<ToolPool> {
  return toToolPool(await apiFetch<J>("/admin/settings/tool-pool"));
}

export async function getProject(slug: string): Promise<Project | undefined> {
  const p = await apiFetch<J | undefined>(`/projects/${encodeURIComponent(slug)}`, { swallow: [403, 404] });
  return p ? toProject(p) : undefined;
}

export async function listDataSources(slug: string): Promise<DataSource[]> {
  return (await apiFetch<J[]>(`/projects/${encodeURIComponent(slug)}/data-sources`)).map(toDataSource);
}

export async function listArtifacts(slug: string, kind?: Artifact["kind"]): Promise<Artifact[]> {
  return (await apiFetch<J[]>(`/projects/${encodeURIComponent(slug)}/artifacts${q({ kind })}`)).map(toArtifact);
}

// --- jobs ------------------------------------------------------------------------------------------

export async function listJobs(opts?: {
  slug?: string;
  status?: Job["status"][];
  kind?: Job["kind"];
  limit?: number;
}): Promise<Job[]> {
  const status = opts?.status?.join(",");
  if (opts?.slug) {
    const page = await apiFetch<J>(
      `/projects/${encodeURIComponent(opts.slug)}/jobs${q({ status, kind: opts.kind, page_size: opts.limit ?? 100 })}`,
    );
    return toPage(page, toJob).items;
  }
  return (await apiFetch<J[]>(`/jobs${q({ status, kind: opts?.kind, limit: opts?.limit ?? 20 })}`)).map(toJob);
}

/** One page of a project's jobs (`GET /projects/{slug}/jobs?page&page_size`), newest first. */
export async function listJobsPage(opts: {
  slug: string;
  page?: number;
  pageSize?: number;
  status?: Job["status"][];
  kind?: Job["kind"];
}): Promise<Page<Job>> {
  const raw = await apiFetch<J>(
    `/projects/${encodeURIComponent(opts.slug)}/jobs${q({
      status: opts.status?.join(","),
      kind: opts.kind,
      page: clampPage(opts.page),
      page_size: opts.pageSize ?? DEFAULT_PAGE_SIZE,
    })}`,
  );
  return toPage(raw, toJob);
}

export async function getJob(id: number): Promise<Job | undefined> {
  const j = await apiFetch<J | undefined>(`/jobs/${id}`, { swallow: [403, 404] });
  return j ? toJob(j) : undefined;
}

/** Admin only: running + queued with wait reasons. */
export async function getQueue(): Promise<{ running: Job[]; queued: Job[] }> {
  const r = await apiFetch<{ running: J[]; queued: J[] }>("/admin/queue");
  return { running: r.running.map(toJob), queued: r.queued.map(toJob) };
}

/** The last `limit` log lines plus the SSE cursor (`last_event_id`) to resume the live stream without replay. */
export async function getJobLog(jobId: number, limit = 2000): Promise<JobLogSnapshot> {
  return toLogSnapshot(await apiFetch<J>(`/jobs/${encodeURIComponent(String(jobId))}/logs${q({ limit })}`));
}

export async function listArtifactsForJob(jobId: number): Promise<Artifact[]> {
  return (await apiFetch<J[]>(`/jobs/${jobId}/artifacts`)).map(toArtifact);
}

export async function getArtifact(id: number): Promise<Artifact | undefined> {
  const a = await apiFetch<J | undefined>(`/artifacts/${id}`, { swallow: [403, 404] });
  return a ? toArtifact(a) : undefined;
}

// --- requests / issues / comments ------------------------------------------------------------------

export async function listIssues(opts?: { status?: Issue["status"]; type?: Issue["type"] }): Promise<Issue[]> {
  const page = await apiFetch<J>(`/issues${q({ status: opts?.status, type: opts?.type, page_size: 100 })}`);
  return toPage(page, toIssue).items;
}

export async function listIssuesPage(opts?: {
  status?: Issue["status"];
  type?: Issue["type"];
  page?: number;
  pageSize?: number;
}): Promise<Page<Issue>> {
  const raw = await apiFetch<J>(
    `/issues${q({
      status: opts?.status,
      type: opts?.type,
      page: clampPage(opts?.page),
      page_size: opts?.pageSize ?? DEFAULT_PAGE_SIZE,
    })}`,
  );
  return toPage(raw, toIssue);
}

export async function getIssue(id: number): Promise<Issue | undefined> {
  const i = await apiFetch<J | undefined>(`/issues/${id}`, { swallow: [403, 404] });
  return i ? toIssue(i) : undefined;
}

/** Comments on an issue (by id) or the review thread of a project's application (by slug). */
export async function listComments(targetType: CommentTarget, target: number | string): Promise<Comment[]> {
  const path =
    targetType === "issue"
      ? `/issues/${target}/comments`
      : `/projects/${encodeURIComponent(String(target))}/application/comments`;
  return (await apiFetch<J[]>(path)).map(toComment);
}

// --- users / admin ---------------------------------------------------------------------------------

export async function listUsers(): Promise<User[]> {
  return toPage(await apiFetch<J>("/users?page_size=100"), toUser).items;
}

export async function listUsersPage(opts?: { page?: number; pageSize?: number; q?: string }): Promise<Page<User>> {
  const raw = await apiFetch<J>(
    `/users${q({ q: opts?.q, page: clampPage(opts?.page), page_size: opts?.pageSize ?? 50 })}`,
  );
  return toPage(raw, toUser);
}

/**
 * Autocomplete rows for pickers (any logged-in user; identity only). Client components go through the
 * /api/users/lookup route handler instead (see components/features/user-picker.tsx).
 */
export async function lookupUsers(query: string): Promise<UserLookup[]> {
  const term = query.trim();
  if (term.length < 2) return [];
  return (await apiFetch<J[]>(`/users/lookup${q({ q: term })}`)).map(toUserLookup);
}

/** Pool + current allocation; readable by every user (request form, home page). */
export async function getCapacity(): Promise<Capacity> {
  return toCapacity(await apiFetch<J>("/capacity"));
}

export async function getResourcePool(): Promise<ResourcePool> {
  return (await getCapacity()).pool;
}

export async function getNodeStatus(): Promise<NodeStatus> {
  return toNode(await apiFetch<J>("/admin/node"));
}

/** Sampled node / pool / per-project usage for the admin history page. */
export async function getUsageHistory(range: UsageRange = "24h"): Promise<UsageHistory> {
  return toUsageHistory(await apiFetch<J>(`/admin/usage${q({ range })}`));
}

export async function listAuditLogsPage(opts?: { page?: number; pageSize?: number }): Promise<Page<AuditLog>> {
  const raw = await apiFetch<J>(`/admin/audit${q({ page: clampPage(opts?.page), page_size: opts?.pageSize ?? 50 })}`);
  return toPage(raw, toAudit);
}

export async function getAdminOverview() {
  const o = await apiFetch<J>("/admin/overview");
  return {
    pendingRequests: Number(o.pending_requests ?? 0),
    queued: Number(o.queued ?? 0),
    running: Number(o.running ?? 0),
    poolGpuUsed: Number(o.pool_gpu_used ?? 0),
    poolGpuTotal: Number(o.pool_gpu_total ?? 0),
    poolUtilization: Number(o.pool_utilization ?? 0),
  };
}

export async function getModelZoo(verify = false): Promise<ModelZooEntry[]> {
  return (await apiFetch<J[]>(`/admin/model-zoo${q({ verify: verify ? "true" : undefined })}`)).map(toZooEntry);
}

export async function getModelZooTasks(): Promise<ZooTask[]> {
  return (await apiFetch<J[]>("/admin/model-zoo/tasks")).map(toZooTask);
}

// --- catalog ---------------------------------------------------------------------------------------

export async function getCatalog(): Promise<Catalog> {
  return apiFetch<Catalog>("/catalog");
}

export async function listPreprocessOps(dataType?: DataType): Promise<PreprocessOp[]> {
  return (await apiFetch<J[]>(`/catalog/preprocess${q({ data_type: dataType })}`)).map(toPreprocessOp);
}

export { toPool };
