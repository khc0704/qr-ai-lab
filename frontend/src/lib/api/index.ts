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
  toLogLines,
  toNode,
  toPool,
  toPreprocessOp,
  toProject,
  toRequest,
  toUser,
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
  LogLine,
  NodeStatus,
  PreprocessOp,
  Project,
  ProjectRequest,
  ResourcePool,
  User,
} from "@/types/domain";

type J = Record<string, unknown>;
interface Page<T> {
  items: T[];
  total: number;
}

const q = (params: Record<string, string | number | boolean | undefined>) => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
};

// --- projects --------------------------------------------------------------------------------------

export async function listProjects(opts?: { includeArchived?: boolean }): Promise<Project[]> {
  const rows = await apiFetch<J[]>(`/projects${q({ include_archived: opts?.includeArchived })}`);
  return rows.map(toProject);
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
    const page = await apiFetch<Page<J>>(
      `/projects/${encodeURIComponent(opts.slug)}/jobs${q({ status, kind: opts.kind, page_size: opts.limit ?? 100 })}`,
    );
    return page.items.map(toJob);
  }
  return (await apiFetch<J[]>(`/jobs${q({ status, kind: opts?.kind, limit: opts?.limit ?? 20 })}`)).map(toJob);
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

export async function getJobLog(jobId: number, limit = 2000): Promise<LogLine[]> {
  const r = await apiFetch<{ lines: string[]; offset: number; total: number }>(`/jobs/${jobId}/logs${q({ limit })}`);
  return toLogLines(r.lines, r.offset);
}

export async function listArtifactsForJob(jobId: number): Promise<Artifact[]> {
  return (await apiFetch<J[]>(`/jobs/${jobId}/artifacts`)).map(toArtifact);
}

export async function getArtifact(id: number): Promise<Artifact | undefined> {
  const a = await apiFetch<J | undefined>(`/artifacts/${id}`, { swallow: [403, 404] });
  return a ? toArtifact(a) : undefined;
}

// --- requests / issues / comments ------------------------------------------------------------------

export async function listProjectRequests(opts?: {
  applicantId?: number;
  status?: ProjectRequest["status"][];
}): Promise<ProjectRequest[]> {
  const page = await apiFetch<Page<J>>(`/project-requests${q({ status: opts?.status?.join(","), page_size: 100 })}`);
  const rows = page.items.map(toRequest);
  return opts?.applicantId ? rows.filter((r) => r.applicant.id === opts.applicantId) : rows;
}

export async function getProjectRequest(id: number): Promise<ProjectRequest | undefined> {
  const r = await apiFetch<J | undefined>(`/project-requests/${id}`, { swallow: [403, 404] });
  return r ? toRequest(r) : undefined;
}

export async function listIssues(opts?: { status?: Issue["status"]; type?: Issue["type"] }): Promise<Issue[]> {
  const page = await apiFetch<Page<J>>(`/issues${q({ status: opts?.status, type: opts?.type, page_size: 100 })}`);
  return page.items.map(toIssue);
}

export async function getIssue(id: number): Promise<Issue | undefined> {
  const i = await apiFetch<J | undefined>(`/issues/${id}`, { swallow: [403, 404] });
  return i ? toIssue(i) : undefined;
}

export async function listComments(targetType: CommentTarget, targetId: number): Promise<Comment[]> {
  const base = targetType === "issue" ? "/issues" : "/project-requests";
  return (await apiFetch<J[]>(`${base}/${targetId}/comments`)).map(toComment);
}

// --- users / admin ---------------------------------------------------------------------------------

export async function listUsers(): Promise<User[]> {
  return (await apiFetch<Page<J>>("/users?page_size=100")).items.map(toUser);
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

export async function listAuditLogs(limit = 50): Promise<AuditLog[]> {
  return (await apiFetch<Page<J>>(`/admin/audit${q({ page_size: limit })}`)).items.map(toAudit);
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

export async function getModelZoo() {
  return apiFetch<
    { id: string; family: string; file: string; license?: string; kind: string; present: boolean; size_bytes?: number }[]
  >("/admin/model-zoo");
}

// --- catalog ---------------------------------------------------------------------------------------

export async function getCatalog(): Promise<Catalog> {
  return apiFetch<Catalog>("/catalog");
}

export async function listPreprocessOps(dataType?: DataType): Promise<PreprocessOp[]> {
  return (await apiFetch<J[]>(`/catalog/preprocess${q({ data_type: dataType })}`)).map(toPreprocessOp);
}

export { toPool };
