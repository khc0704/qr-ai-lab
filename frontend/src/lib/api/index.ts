// Server-only data access layer. Today it reads mock data; later each function becomes a
// fetch(`${BACKEND_URL}/api/v1/...`) with the Keycloak access token. Pages must only import
// from here, never from mock-data directly, so the swap is a one-file change.
import "server-only";

import * as mock from "@/lib/mock-data";
import type {
  Artifact,
  AuditLog,
  Comment,
  CommentTarget,
  DataSource,
  Issue,
  Job,
  LogLine,
  NodeStatus,
  Project,
  ProjectRequest,
  ResourcePool,
  User,
} from "@/types/domain";

const sortByRank = (a: Job, b: Job) => a.queueRank - b.queueRank || a.createdAt.localeCompare(b.createdAt);
const newestFirst = <T extends { createdAt: string }>(a: T, b: T) => b.createdAt.localeCompare(a.createdAt);

export async function listProjects(opts?: { memberOf?: number; includeArchived?: boolean }): Promise<Project[]> {
  return mock.projects.filter(
    (p) =>
      (opts?.includeArchived || p.status === "active") &&
      (!opts?.memberOf || p.members.some((m) => m.user.id === opts.memberOf)),
  );
}

export async function getProject(slug: string): Promise<Project | undefined> {
  return mock.projects.find((p) => p.slug === slug);
}

export async function listDataSources(projectId: number): Promise<DataSource[]> {
  return mock.dataSources.filter((d) => d.projectId === projectId);
}

export async function listJobs(opts?: {
  projectId?: number;
  status?: Job["status"][];
  limit?: number;
}): Promise<Job[]> {
  const rows = mock.jobs
    .filter(
      (j) => (!opts?.projectId || j.projectId === opts.projectId) && (!opts?.status || opts.status.includes(j.status)),
    )
    .sort(newestFirst);
  return opts?.limit ? rows.slice(0, opts.limit) : rows;
}

export async function getJob(id: number): Promise<Job | undefined> {
  return mock.jobs.find((j) => j.id === id);
}

/** Global queue: running first (by start time), then queued by rank. */
export async function getQueue(): Promise<{ running: Job[]; queued: Job[] }> {
  const running = mock.jobs
    .filter((j) => j.status === "running" || j.status === "scheduled")
    .sort((a, b) => (a.startedAt ?? "").localeCompare(b.startedAt ?? ""));
  const queued = mock.jobs.filter((j) => j.status === "queued").sort(sortByRank);
  return { running, queued };
}

export async function getQueuePosition(jobId: number): Promise<number | undefined> {
  const { queued } = await getQueue();
  const i = queued.findIndex((j) => j.id === jobId);
  return i >= 0 ? i + 1 : undefined;
}

export async function getJobLog(jobId: number): Promise<LogLine[]> {
  return mock.jobLogs[jobId] ?? [];
}

export async function listArtifacts(projectId: number, kind?: Artifact["kind"]): Promise<Artifact[]> {
  return mock.artifacts.filter((a) => a.projectId === projectId && (!kind || a.kind === kind)).sort(newestFirst);
}

export async function listArtifactsForJob(jobId: number): Promise<Artifact[]> {
  return mock.artifacts.filter((a) => a.jobId === jobId);
}

export async function getArtifact(id: number): Promise<Artifact | undefined> {
  return mock.artifacts.find((a) => a.id === id);
}

export async function listProjectRequests(opts?: {
  applicantId?: number;
  status?: ProjectRequest["status"][];
}): Promise<ProjectRequest[]> {
  return mock.projectRequests
    .filter(
      (r) =>
        (!opts?.applicantId || r.applicant.id === opts.applicantId) &&
        (!opts?.status || opts.status.includes(r.status)),
    )
    .sort((a, b) => b.submittedAt.localeCompare(a.submittedAt));
}

export async function getProjectRequest(id: number): Promise<ProjectRequest | undefined> {
  return mock.projectRequests.find((r) => r.id === id);
}

export async function listIssues(opts?: { status?: Issue["status"]; type?: Issue["type"] }): Promise<Issue[]> {
  return mock.issues
    .filter((i) => (!opts?.status || i.status === opts.status) && (!opts?.type || i.type === opts.type))
    .sort(newestFirst);
}

export async function getIssue(id: number): Promise<Issue | undefined> {
  return mock.issues.find((i) => i.id === id);
}

export async function listComments(targetType: CommentTarget, targetId: number): Promise<Comment[]> {
  return mock.comments
    .filter((c) => c.targetType === targetType && c.targetId === targetId)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export async function listUsers(): Promise<User[]> {
  return [...mock.users];
}

export async function getResourcePool(): Promise<ResourcePool> {
  return mock.resourcePool;
}

export async function getNodeStatus(): Promise<NodeStatus> {
  return mock.nodeStatus;
}

export async function listAuditLogs(limit = 50): Promise<AuditLog[]> {
  return [...mock.auditLogs].sort(newestFirst).slice(0, limit);
}

export async function getAdminOverview() {
  const { running, queued } = await getQueue();
  const pending = (await listProjectRequests({ status: ["submitted", "in_review"] })).length;
  const pool = await getResourcePool();
  const node = await getNodeStatus();
  return {
    pendingRequests: pending,
    queued: queued.length,
    running: running.length,
    poolGpuUsed: node.allocated.gpu,
    poolGpuTotal: pool.gpuIndices.length,
    poolUtilization: pool.gpuIndices.length ? Math.round((node.allocated.gpu / pool.gpuIndices.length) * 100) : 0,
  };
}
