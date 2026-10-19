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
  ModelZooEntry,
  NodeStatus,
  PreprocessOp,
  Project,
  Application,
  ResourcePool,
  RunnerInfo,
  Upload,
  User,
  UserLookup,
  ZooTask,
  GpuResetResult,
  UsageHistory,
  UsageProject,
  ToolPool,
  ToolPoolStatus,
  ToolUpload,
  JobLogSnapshot,
  Page,
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
/**
 * Enum-like fields: a value the backend sends is passed through typed as the union (a new state added on the
 * backend must not silently turn into something else in the UI); only a missing / empty value gets the default.
 */
const asEnum = <T extends string>(v: unknown, d: T): T => (typeof v === "string" && v !== "" ? (v as T) : d);

/** `{items,total,page,page_size}` → Page<T> with each item mapped. */
export function toPage<T>(raw: J, map: (row: J) => T): Page<T> {
  return {
    items: ((raw.items as J[]) ?? []).map(map),
    total: num(raw.total),
    page: num(raw.page, 1),
    pageSize: num(raw.page_size, ((raw.items as J[]) ?? []).length || 20),
  };
}

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
    // least privilege on purpose: an unknown system role must never unlock admin UI
    role: x.role === "superadmin" || x.role === "admin" ? x.role : "user",
    isActive: Boolean(x.is_active),
    lastLoginAt: isoOpt(x.last_login_at),
    authProvider: x.auth_provider === "keycloak" ? "keycloak" : x.auth_provider === "local" ? "local" : undefined,
    permissions: Array.isArray(x.permissions) ? (x.permissions as string[]) : undefined,
    authMode: x.auth_mode === "keycloak" ? "keycloak" : x.auth_mode === "local" ? "local" : undefined,
  };
}

/** GET /users/lookup row (autocomplete): identity only; display name falls back to the username like toUser. */
export function toUserLookup(u: J): UserLookup {
  return {
    id: num(u.id),
    username: str(u.username),
    displayName: str(u.display_name) || str(u.username),
    email: str(u.email),
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
    status: asEnum<Project["status"]>(p.status, "active"),
    kind: asEnum<Project["kind"]>(p.kind, "standard"),
    owner: toUser(p.owner as J),
    application: p.application ? toApplication(p.application as J) : undefined,
    gpuLimit: num(p.gpu_limit),
    cpuLimit: num(p.cpu_limit),
    memoryLimitMb: num(p.memory_limit_mb),
    storageQuotaMb: num(p.storage_quota_mb),
    storageUsedBytes: num(p.storage_used_bytes),
    maxConcurrentJobs: num(p.max_concurrent_jobs, 1),
    defaultJobTimeoutMinutes: opt<number>(p.default_job_timeout_minutes),
    members: ((p.members as J[]) ?? []).map((m) => ({
      user: toUser(m.user as J),
      role: asEnum<Project["members"][number]["role"]>(m.role, "viewer"),
      addedAt: iso(m.created_at),
    })),
    createdAt: iso(p.created_at),
    approvedAt: isoOpt(p.approved_at),
    completedAt: isoOpt(p.completed_at),
    archivedAt: isoOpt(p.archived_at),
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
    kind: asEnum<DataSource["kind"]>(d.kind, "url"),
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
    kind: asEnum<Job["kind"]>(j.kind, "train"),
    name: str(j.name),
    status: asEnum<Job["status"]>(j.status, "queued"),
    queueRank: num(j.queue_rank),
    queuePosition: opt<number>(j.queue_position),
    requestedGpu: num(j.requested_gpu),
    requestedCpu: num(j.requested_cpu),
    requestedMemoryMb: num(j.requested_memory_mb),
    requestedGpuMemoryMb: opt<number>(j.requested_gpu_memory_mb),
    timeoutMinutes: num(j.timeout_minutes),
    assignedGpus: opt<number[]>(j.assigned_gpus),
    assignedCpus: opt<number[]>(j.assigned_cpus),
    progress: Math.round(num(j.progress)),
    currentStage: opt<Job["currentStage"]>(j.current_stage),
    taskType: opt<Job["taskType"]>(j.task_type),
    mode: opt<Job["mode"]>(j.mode),
    modelFamily: opt<Job["modelFamily"]>(j.model_family),
    dataSourceId: opt<number>(j.data_source_id),
    artifactId: opt<number>(j.artifact_id),
    input: {
      kind: asEnum<Job["input"]["kind"]>(input.kind, "upload"),
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
    kind: asEnum<Artifact["kind"]>(a.kind, "model"),
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

export function toApplication(r: J): Application {
  return {
    id: num(r.id),
    purpose: str(r.purpose),
    dataScale: r.data_scale as Application["dataScale"],
    dataDescription: opt<string>(r.data_description),
    requestedGpu: num(r.requested_gpu),
    requestedCpu: num(r.requested_cpu),
    requestedMemoryMb: num(r.requested_memory_mb),
    requestedStorageMb: num(r.requested_storage_mb),
    members: ((r.members as J[]) ?? []).map((m) => ({
      email: str(m.email),
      role: asEnum<Application["members"][number]["role"]>(m.role, "member"),
    })),
    reviewer: r.reviewer ? toUser(r.reviewer as J) : undefined,
    reviewNote: opt<string>(r.review_note),
    reviewedAt: isoOpt(r.reviewed_at),
    submittedAt: iso(r.submitted_at ?? r.created_at),
    commentCount: num(r.comment_count),
  };
}

export function toIssue(i: J): Issue {
  return {
    id: num(i.id),
    type: asEnum<Issue["type"]>(i.type, "question"),
    title: str(i.title),
    body: str(i.body),
    status: asEnum<Issue["status"]>(i.status, "open"),
    author: toUser(i.author as J),
    assignee: i.assignee ? toUser(i.assignee as J) : undefined,
    projectSlug: opt<string>(i.project_slug),
    resolutionNote: opt<string>(i.resolution_note),
    commentCount: num(i.comment_count),
    createdAt: iso(i.created_at),
    updatedAt: iso(i.updated_at ?? i.created_at),
    closedAt: isoOpt(i.closed_at),
  };
}

export function toComment(c: J): Comment {
  return {
    id: num(c.id),
    targetType: c.target_type as Comment["targetType"],
    targetId: num(c.target_id),
    author: c.author ? toUser(c.author as J) : undefined,
    kind: asEnum<Comment["kind"]>(c.kind, "comment"),
    body: str(c.body),
    createdAt: iso(c.created_at),
    updatedAt: isoOpt(c.updated_at),
  };
}

export function toPool(p: J): ResourcePool {
  return {
    gpuIndices: (p.gpu_indices as number[]) ?? [],
    cpuCores: num(p.cpu_cores),
    memoryMb: num(p.memory_mb),
    maxRunningJobs: num(p.max_running_jobs, 1),
    allowBackfill: Boolean(p.allow_backfill),
    gpuShare: p.gpu_share === undefined ? true : Boolean(p.gpu_share),
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
      jobIds: ((g.job_ids as number[]) ?? []).map(Number),
      jobs: ((g.jobs as J[]) ?? []).map((x) => ({
        jobId: num(x.job_id),
        requestedMb: opt<number>(x.requested_mb),
        measuredMb: num(x.measured_mb),
      })),
      measuredMb: opt<number>(g.measured_mb),
      reservedMb: opt<number>(g.reserved_mb),
      processes: opt<number>(g.processes),
    })),
    cpuCores: num(n.cpu_cores),
    cpuUsedCores: num(n.cpu_used_cores),
    platform: opt<string>(n.platform),
    memoryMb: num(n.memory_mb),
    memoryUsedMb: num(n.memory_used_mb),
    diskTotalGb: num(n.disk_total_gb),
    diskFreeGb: num(n.disk_free_gb),
    allocated: toAllocated(n.allocated as J),
    runner: n.runner ? toRunner(n.runner as J) : undefined,
  };
}

export function toRunner(r: J): RunnerInfo {
  const enf = (r.enforces as J | undefined) ?? {};
  return {
    kind: str(r.kind),
    enforces: { memory: Boolean(enf.memory), cpu: Boolean(enf.cpu), cpuset: Boolean(enf.cpuset) },
    memoryWatchdog: Boolean(r.memory_watchdog),
    trainerPython: str(r.trainer_python),
    trainerDir: str(r.trainer_dir),
    offline: r.offline !== false,
    note: str(r.note ?? ""),
  };
}

export function toZooTask(t: J): ZooTask {
  return {
    weightId: str(t.weight_id),
    source: str(t.source),
    state: str(t.state) as ZooTask["state"],
    progress: num(t.progress),
    downloadedMb: num(t.downloaded_mb),
    totalMb: opt<number>(t.total_mb),
    message: opt<string>(t.message),
    startedAt: iso(str(t.started_at)),
    finishedAt: t.finished_at ? iso(str(t.finished_at)) : undefined,
  };
}

export function toZooEntry(e: J): ModelZooEntry {
  return {
    id: str(e.id),
    family: str(e.family),
    families: (e.families as string[] | undefined) ?? [str(e.family)],
    file: str(e.file),
    license: opt<string>(e.license),
    source: opt<string>(e.source),
    kind: str(e.kind ?? "file"),
    present: Boolean(e.present),
    status: str(e.status ?? (e.present ? "present" : "missing")) as ModelZooEntry["status"],
    sizeBytes: opt<number>(e.size_bytes),
    sha256Expected: opt<string>(e.sha256_expected),
    sha256Actual: opt<string>(e.sha256_actual),
    importedAt: e.imported_at ? iso(str(e.imported_at)) : undefined,
    importedFrom: opt<string>(e.imported_from),
    task: e.task ? toZooTask(e.task as J) : undefined,
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

export function toGpuReset(r: J): GpuResetResult {
  return {
    index: num(r.index),
    mode: asEnum<GpuResetResult["mode"]>(r.mode, "jobs"),
    stoppedJobs: ((r.stopped_jobs as number[]) ?? []).map(Number),
    killedPids: ((r.killed_pids as number[]) ?? []).map(Number),
    skippedPids: ((r.skipped_pids as number[]) ?? []).map(Number),
    command: opt<string>(r.command),
    commandOk: opt<boolean>(r.command_ok),
    commandOutput: opt<string>(r.command_output),
    memoryUsedMbBefore: opt<number>(r.memory_used_mb_before),
    memoryUsedMbAfter: opt<number>(r.memory_used_mb_after),
  };
}

export function toUsageHistory(h: J): UsageHistory {
  const totals = (h.totals as J) ?? {};
  const share = (h.project_share as Record<string, J>) ?? {};
  return {
    range: (h.range as UsageHistory["range"]) ?? "24h",
    bucketS: num(h.bucket_s, 60),
    sampleIntervalS: num(h.sample_interval_s, 30),
    points: ((h.points as J[]) ?? []).map((p) => ({
      t: str(p.t),
      cpuPct: opt<number>(p.cpu_pct),
      memUsedMb: opt<number>(p.mem_used_mb),
      gpuUtil: opt<number>(p.gpu_util),
      gpuMemUsedMb: opt<number>(p.gpu_mem_used_mb),
      allocGpu: opt<number>(p.alloc_gpu),
      allocCpu: opt<number>(p.alloc_cpu),
      allocMemoryMb: opt<number>(p.alloc_memory_mb),
      runningJobs: opt<number>(p.running_jobs),
      projects: Object.fromEntries(
        Object.entries((p.projects as Record<string, J>) ?? {}).map(([id, v]) => [
          id,
          {
            gpu: num(v.gpu),
            cpu: num(v.cpu),
            memoryMb: num(v.memory_mb),
            runningJobs: num(v.running_jobs),
            cpuActual: num(v.cpu_actual),
            memActualMb: num(v.mem_actual_mb),
          },
        ]),
      ),
    })),
    totals: {
      cpuCores: num(totals.cpu_cores),
      memoryMb: num(totals.memory_mb),
      gpuCount: num(totals.gpu_count),
      gpuMemoryMb: num(totals.gpu_memory_mb),
      poolGpu: num(totals.pool_gpu),
      poolCpu: num(totals.pool_cpu),
      poolMemoryMb: num(totals.pool_memory_mb),
    },
    projects: ((h.projects as J[]) ?? []).map((p) => ({
      id: num(p.id),
      slug: str(p.slug),
      name: str(p.name),
      gpuLimit: num(p.gpu_limit),
      cpuLimit: num(p.cpu_limit),
      memoryLimitMb: num(p.memory_limit_mb),
      status: (p.status as UsageProject["status"]) ?? "active",
    })),
    projectShare: Object.fromEntries(
      Object.entries(share).map(([id, v]) => [
        id,
        {
          gpuAvg: num(v.gpu_avg),
          cpuAvg: num(v.cpu_avg),
          memoryMbAvg: num(v.memory_mb_avg),
          gpuOfQuota: num(v.gpu_of_quota),
          cpuOfQuota: num(v.cpu_of_quota),
          memoryMbOfQuota: num(v.memory_mb_of_quota),
          gpuOfPool: num(v.gpu_of_pool),
          cpuOfPool: num(v.cpu_of_pool),
          memoryMbOfPool: num(v.memory_mb_of_pool),
          gpuOfNode: num(v.gpu_of_node),
          cpuOfNode: num(v.cpu_of_node),
          memoryMbOfNode: num(v.memory_mb_of_node),
          cpuActualAvg: num(v.cpu_actual_avg),
          memActualAvgMb: num(v.mem_actual_avg_mb),
          jobSeconds: num(v.job_seconds),
        },
      ]),
    ),
  };
}

export function toToolUpload(u: J): ToolUpload {
  return {
    id: str(u.id),
    dataType: u.data_type as ToolUpload["dataType"],
    originalFilename: str(u.original_filename),
    sizeBytes: num(u.size_bytes),
    format: str(u.format),
    detectedSpec: opt<Record<string, unknown>>(u.detected_spec),
    expiresAt: iso(u.expires_at),
    createdAt: iso(u.created_at),
  };
}

export function toToolPool(d: J): ToolPool {
  return {
    gpuLimit: num(d.gpu_limit),
    cpuLimit: num(d.cpu_limit, 4),
    memoryLimitMb: num(d.memory_limit_mb, 8192),
    storageQuotaMb: num(d.storage_quota_mb, 4096),
    maxConcurrentJobs: num(d.max_concurrent_jobs, 2),
    maxJobsPerUser: num(d.max_jobs_per_user, 2),
    resultTtlHours: num(d.result_ttl_hours, 24),
  };
}

export function toToolPoolStatus(d: J): ToolPoolStatus {
  return { ...toToolPool(d), slug: str(d.slug, "tools"), myActiveJobs: num(d.my_active_jobs) };
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

/** GET /jobs/{id}/logs → lines + the SSE cursor (`last_event_id`, null when the job has not emitted events). */
export function toLogSnapshot(r: J): JobLogSnapshot {
  const lines = Array.isArray(r.lines) ? (r.lines as string[]) : [];
  return {
    lines: toLogLines(lines, num(r.offset)),
    total: num(r.total, lines.length),
    lastEventId: typeof r.last_event_id === "string" && r.last_event_id ? r.last_event_id : undefined,
  };
}
