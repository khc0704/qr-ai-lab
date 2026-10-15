// snake_case backend JSON → camelCase domain types. Backend datetimes are naive UTC; add "Z".
import type {
  Allocated,
  Artifact,
  AuditLog,
  Capacity,
  Comment,
  DataSource,
  Issue,
  Job,
  LeaderboardRow,
  LogLine,
  NodeStatus,
  PreprocessOp,
  Project,
  ProjectRequest,
  ResourcePool,
  Upload,
  User,
} from "@/types/domain";

type J = Record<string, unknown>;

export const iso = (v: unknown): string => {
  if (typeof v !== "string") return "";
  return /[zZ]|[+-]\d\d:\d\d$/.test(v) ? v : `${v}Z`;
};
const isoOpt = (v: unknown): string | undefined => (v ? iso(v) : undefined);
const num = (v: unknown, d = 0): number => (typeof v === "number" ? v : v == null ? d : Number(v));
const str = (v: unknown, d = ""): string => (v == null ? d : String(v));
const opt = <T>(v: unknown): T | undefined => (v == null ? undefined : (v as T));

export interface UserRead {
  id: number;
  username: string;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  last_login_at?: string | null;
}

export function toUser(u: UserRead | J): User {
  const x = u as J;
  return {
    id: num(x.id),
    username: str(x.username),
    email: str(x.email),
    displayName: str(x.display_name) || str(x.username),
    role: x.role === "admin" ? "admin" : "user",
    isActive: Boolean(x.is_active),
    lastLoginAt: isoOpt(x.last_login_at),
  };
}

export function toProject(p: J): Project {
  const usage = (p.usage as J) ?? {};
  return {
    id: num(p.id),
    slug: str(p.slug),
    name: str(p.name),
    description: str(p.description),
    dataType: p.data_type as Project["dataType"],
    taskType: p.task_type as Project["taskType"],
    status: p.status === "archived" ? "archived" : "active",
    owner: toUser(p.owner as J),
    gpuLimit: num(p.gpu_limit),
    cpuLimit: num(p.cpu_limit),
    memoryLimitMb: num(p.memory_limit_mb),
    storageQuotaMb: num(p.storage_quota_mb),
    storageUsedBytes: num(p.storage_used_bytes),
    maxConcurrentJobs: num(p.max_concurrent_jobs, 1),
    defaultJobTimeoutMinutes: opt<number>(p.default_job_timeout_minutes),
    members: ((p.members as J[]) ?? []).map((m) => ({
      user: toUser(m.user as J),
      role: m.role as Project["members"][number]["role"],
      addedAt: iso(m.created_at),
    })),
    createdAt: iso(p.created_at),
    usage: {
      gpu: num(usage.gpu),
      cpu: num(usage.cpu),
      memoryMb: num(usage.memory_mb),
      runningJobs: num(usage.running_jobs),
    },
  };
}

export function toDataSource(d: J): DataSource {
  return {
    id: num(d.id),
    projectId: num(d.project_id),
    name: str(d.name),
    kind: d.kind === "minio" ? "minio" : "url",
    endpoint: opt<string>(d.endpoint),
    bucket: opt<string>(d.bucket),
    objectPath: opt<string>(d.object_path),
    url: opt<string>(d.url),
    hasCredentials: Boolean(d.has_credentials),
    format: d.format as DataSource["format"],
    defaultSpec: opt<Record<string, unknown>>(d.default_spec),
    lastCheckOk: opt<boolean>(d.last_check_ok),
    lastCheckMessage: opt<string>(d.last_check_message),
    lastCheckedAt: isoOpt(d.last_checked_at),
    createdBy: toUser(d.created_by as J),
    createdAt: iso(d.created_at),
  };
}

function toLeaderboard(rows: unknown): LeaderboardRow[] | undefined {
  if (!Array.isArray(rows)) return undefined;
  return rows.map((r) => {
    const x = r as J;
    return {
      trial: num(x.trial),
      family: str(x.family) as LeaderboardRow["family"],
      params: (x.params as LeaderboardRow["params"]) ?? {},
      metric: num(x.metric),
      metrics: opt<Record<string, number>>(x.metrics),
      durationS: num(x.seconds ?? x.duration_s),
    };
  });
}

export function toJob(j: J): Job {
  const rawMetrics = (j.metrics as J | null) ?? undefined;
  const metrics: Job["metrics"] = rawMetrics
    ? Object.fromEntries(
        Object.entries(rawMetrics)
          .filter(([k]) => !k.startsWith("_"))
          .map(([k, v]) => [k, k === "leaderboard" ? toLeaderboard(v) : (v as number | string)]),
      )
    : undefined;
  const input = (j.input as J) ?? {};
  return {
    id: num(j.id),
    projectId: num(j.project_id),
    projectSlug: str(j.project_slug),
    projectName: str(j.project_name),
    kind: j.kind === "inference" ? "inference" : "train",
    name: str(j.name),
    status: j.status as Job["status"],
    queueRank: num(j.queue_rank),
    queuePosition: opt<number>(j.queue_position),
    requestedGpu: num(j.requested_gpu),
    requestedCpu: num(j.requested_cpu),
    requestedMemoryMb: num(j.requested_memory_mb),
    timeoutMinutes: num(j.timeout_minutes),
    assignedGpus: opt<number[]>(j.assigned_gpus),
    progress: Math.round(num(j.progress)),
    currentStage: opt<Job["currentStage"]>(j.current_stage),
    taskType: opt<Job["taskType"]>(j.task_type),
    mode: opt<Job["mode"]>(j.mode),
    modelFamily: opt<Job["modelFamily"]>(j.model_family),
    dataSourceId: opt<number>(j.data_source_id),
    artifactId: opt<number>(j.artifact_id),
    input: {
      kind: (input.kind as Job["input"]["kind"]) ?? "upload",
      originalFilename: opt<string>(input.original_filename),
      sizeBytes: opt<number>(input.size_bytes),
      dataSourceName: opt<string>(input.data_source_name),
      format: str(input.format, "csv"),
      spec: (input.spec as Job["input"]["spec"]) ?? {},
      rows: opt<Record<string, unknown>[]>(input.rows),
    },
    config: opt<Record<string, unknown>>(j.config),
    metrics,
    result: opt<Record<string, unknown>>(j.result),
    errorMessage: opt<string>(j.error_message),
    cancelReason: opt<string>(j.cancel_reason),
    cancelRequestedBy: j.cancel_requested_by ? toUser(j.cancel_requested_by as J) : undefined,
    waitReason: opt<string>(j.wait_reason),
    startedAt: isoOpt(j.started_at),
    finishedAt: isoOpt(j.finished_at),
    createdBy: toUser(j.created_by as J),
    createdAt: iso(j.created_at),
  };
}

export function toArtifact(a: J): Artifact {
  return {
    id: num(a.id),
    projectId: num(a.project_id),
    jobId: num(a.job_id),
    name: str(a.name),
    version: num(a.version, 1),
    kind: a.kind as Artifact["kind"],
    modelFamily: str(a.model_family) as Artifact["modelFamily"],
    framework: str(a.framework),
    path: str(a.path),
    sizeBytes: num(a.size_bytes),
    metrics: opt<Record<string, number>>(a.metrics),
    metadata: opt<Record<string, unknown>>(a.metadata),
    isDefault: Boolean(a.is_default),
    createdAt: iso(a.created_at),
  };
}

export function toRequest(r: J): ProjectRequest {
  return {
    id: num(r.id),
    applicant: toUser(r.applicant as J),
    title: str(r.title),
    purpose: str(r.purpose),
    dataType: r.data_type as ProjectRequest["dataType"],
    taskType: r.task_type as ProjectRequest["taskType"],
    dataScale: r.data_scale as ProjectRequest["dataScale"],
    dataDescription: opt<string>(r.data_description),
    requestedGpu: num(r.requested_gpu),
    requestedCpu: num(r.requested_cpu),
    requestedMemoryMb: num(r.requested_memory_mb),
    requestedStorageMb: num(r.requested_storage_mb),
    proposedSlug: opt<string>(r.proposed_slug),
    members: ((r.members as J[]) ?? []).map((m) => ({
      email: str(m.email),
      role: (m.role as ProjectRequest["members"][number]["role"]) ?? "member",
    })),
    status: r.status as ProjectRequest["status"],
    reviewer: r.reviewer ? toUser(r.reviewer as J) : undefined,
    reviewNote: opt<string>(r.review_note),
    reviewedAt: isoOpt(r.reviewed_at),
    projectSlug: opt<string>(r.project_slug),
    commentCount: num(r.comment_count),
    submittedAt: iso(r.submitted_at ?? r.created_at),
  };
}

export function toIssue(i: J): Issue {
  return {
    id: num(i.id),
    type: i.type as Issue["type"],
    title: str(i.title),
    body: str(i.body),
    status: i.status === "closed" ? "closed" : "open",
    author: toUser(i.author as J),
    assignee: i.assignee ? toUser(i.assignee as J) : undefined,
    projectSlug: opt<string>(i.project_slug),
    resolutionNote: opt<string>(i.resolution_note),
    commentCount: num(i.comment_count),
    createdAt: iso(i.created_at),
    closedAt: isoOpt(i.closed_at),
  };
}

export function toComment(c: J): Comment {
  return {
    id: num(c.id),
    targetType: c.target_type as Comment["targetType"],
    targetId: num(c.target_id),
    author: c.author ? toUser(c.author as J) : undefined,
    kind: c.kind === "system" ? "system" : "comment",
    body: str(c.body),
    createdAt: iso(c.created_at),
  };
}

export function toPool(p: J): ResourcePool {
  return {
    gpuIndices: (p.gpu_indices as number[]) ?? [],
    cpuCores: num(p.cpu_cores),
    memoryMb: num(p.memory_mb),
    maxRunningJobs: num(p.max_running_jobs, 1),
    allowBackfill: Boolean(p.allow_backfill),
  };
}

export function toAllocated(a: J | undefined): Allocated {
  const x = a ?? {};
  return { gpu: num(x.gpu), cpu: num(x.cpu), memoryMb: num(x.memory_mb), runningJobs: num(x.running_jobs) };
}

export function toCapacity(c: J): Capacity {
  return { pool: toPool(c.pool as J), allocated: toAllocated(c.allocated as J) };
}

export function toNode(n: J): NodeStatus {
  return {
    gpus: ((n.gpus as J[]) ?? []).map((g) => ({
      index: num(g.index),
      name: str(g.name),
      memoryTotalMb: num(g.memory_total_mb),
      memoryUsedMb: num(g.memory_used_mb),
      utilization: num(g.utilization),
      jobId: opt<number>(g.job_id),
    })),
    cpuCores: num(n.cpu_cores),
    cpuUsedCores: num(n.cpu_used_cores),
    memoryMb: num(n.memory_mb),
    memoryUsedMb: num(n.memory_used_mb),
    diskTotalGb: num(n.disk_total_gb),
    diskFreeGb: num(n.disk_free_gb),
    allocated: toAllocated(n.allocated as J),
  };
}

export function toAudit(l: J): AuditLog {
  const payload = (l.payload as J | null) ?? undefined;
  const reason = payload?.reason ?? payload?.error ?? payload?.review_note;
  return {
    id: num(l.id),
    actor: l.actor ? toUser(l.actor as J) : undefined,
    action: str(l.action),
    targetType: str(l.target_type),
    targetId: opt<number>(l.target_id),
    reason: reason == null ? undefined : String(reason),
    payload,
    createdAt: iso(l.created_at),
  };
}

export function toUpload(u: J): Upload {
  return {
    id: num(u.id),
    projectId: num(u.project_id),
    originalFilename: str(u.original_filename),
    sizeBytes: num(u.size_bytes),
    format: str(u.format),
    detectedSpec: opt<Record<string, unknown>>(u.detected_spec),
    status: str(u.status),
    expiresAt: iso(u.expires_at),
  };
}

export function toPreprocessOp(o: J): PreprocessOp {
  return {
    id: str(o.id),
    label: str(o.label),
    description: str(o.description),
    dataTypes: (o.data_types as PreprocessOp["dataTypes"]) ?? [],
    params: ((o.params as J[]) ?? []).map((p) => ({
      name: str(p.name),
      label: str(p.label),
      type: p.type as PreprocessOp["params"][number]["type"],
      default: p.default,
      min: opt<number>(p.min),
      max: opt<number>(p.max),
      choices: opt<unknown[]>(p.choices),
      help: opt<string>(p.help),
    })),
    geometric: Boolean(o.geometric),
    fitted: Boolean(o.fitted),
    dropsRows: Boolean(o.drops_rows),
  };
}

const LINE_RE = /^(\S+)\s+\[(INFO|WARN|WARNING|ERROR|DEBUG|SYSTEM)\]\s?(.*)$/;

export function toLogLines(lines: string[], offset: number): LogLine[] {
  return lines.map((raw, i) => {
    const m = LINE_RE.exec(raw);
    const level = (m?.[2] === "WARNING" ? "WARN" : (m?.[2] ?? "INFO")) as LogLine["level"];
    return { n: offset + i + 1, ts: m ? iso(m[1]) : "", level, text: m ? m[3] : raw };
  });
}
