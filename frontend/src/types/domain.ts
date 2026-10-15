// Domain types used by pages and components (camelCase). src/lib/api maps the backend's snake_case JSON.

export type DataType = "TABULAR" | "IMAGE" | "SEQUENCE" | "TEXT" | "SPECTRUM";
export type TaskType = "classification" | "regression" | "detection" | "segmentation" | "anomaly_detection";
export type ModelFamily =
  | "tabular.linear"
  | "tabular.svm"
  | "tabular.random_forest"
  | "tabular.xgboost"
  | "tabular.isolation_forest"
  | "vision.yolo"
  | "vision.dino_fewshot"
  | "vision.dino_patchcore"
  | "vision.image_quality"
  | "sequence.patch_autoencoder"
  | "spectrum.masked_autoencoder"
  | "text.bert_classifier";
export type InferenceMode =
  "predict" | "score" | "compare" | "embed" | "retrieve" | "detect" | "segment" | "measure" | "extend";
export type SystemRole = "superadmin" | "admin" | "user";
export type ProjectRole = "owner" | "maintainer" | "member" | "viewer";
export type ProjectStatus = "active" | "archived";
export type JobKind = "train" | "inference" | "preprocess" | "analysis";
export type ProjectKind = "standard" | "personal";
export type AnalysisKind = "tabular_profile" | "image_quality";
export type JobStatus = "queued" | "scheduled" | "running" | "succeeded" | "failed" | "cancelled";
export type JobMode = "manual" | "auto";
export type JobStage =
  | "starting"
  | "fetching"
  | "preparing"
  | "training"
  | "evaluating"
  | "exporting"
  | "loading"
  | "predicting"
  | "processing"
  | "done"
  | "failed"
  | "cancelled";
export type InputKind = "upload" | "data_source" | "inline";
export type RequestStatus = "submitted" | "in_review" | "approved" | "rejected" | "withdrawn";
export type DataScale = "tiny" | "small" | "medium" | "large";
export type IssueType = "question" | "bug" | "feature";
export type IssueStatus = "open" | "closed";
export type DataSourceKind = "minio" | "url";
export type DataFormat = "csv" | "parquet" | "image_folder" | "coco" | "yolo" | "npy" | "jsonl" | "spectrum_csv";
export type ArtifactKind = "model" | "weights" | "preprocessor" | "report" | "metrics";
export type CommentTarget = "issue" | "project_request";

export interface User {
  id: number;
  username: string;
  email: string;
  displayName: string;
  role: SystemRole;
  isActive: boolean;
  lastLoginAt?: string;
  authProvider?: "local" | "keycloak";
  /** Only on the current user (/me): permission names resolved by the backend. */
  permissions?: string[];
  authMode?: "local" | "keycloak";
}

export interface ProjectMember {
  user: User;
  role: ProjectRole;
  addedAt: string;
}

export interface Project {
  id: number;
  slug: string;
  name: string;
  description: string;
  /** personal = the user's workspace that hosts preprocessing / analysis tool jobs */
  kind: ProjectKind;
  dataType: DataType;
  taskType: TaskType;
  status: ProjectStatus;
  owner: User;
  gpuLimit: number;
  cpuLimit: number;
  memoryLimitMb: number;
  storageQuotaMb: number;
  storageUsedBytes: number;
  maxConcurrentJobs: number;
  defaultJobTimeoutMinutes?: number;
  members: ProjectMember[];
  createdAt: string;
  /** Live usage, computed by the backend from running jobs. */
  usage: { gpu: number; cpu: number; memoryMb: number; runningJobs: number };
}

export interface DataSource {
  id: number;
  projectId: number;
  name: string;
  kind: DataSourceKind;
  endpoint?: string;
  bucket?: string;
  objectPath?: string;
  url?: string;
  hasCredentials: boolean;
  format: DataFormat;
  defaultSpec?: Record<string, unknown>;
  lastCheckOk?: boolean;
  lastCheckMessage?: string;
  lastCheckedAt?: string;
  createdBy: User;
  createdAt: string;
}

export interface PreprocessStep {
  op: string;
  params?: Record<string, unknown>;
}

export interface JobInput {
  kind: InputKind;
  originalFilename?: string;
  sizeBytes?: number;
  dataSourceName?: string;
  format: DataFormat | "json" | string;
  spec: Record<string, unknown> & { preprocess?: PreprocessStep[] };
  rows?: Record<string, unknown>[];
}

export interface LeaderboardRow {
  trial: number;
  family: ModelFamily;
  params: Record<string, number | string | boolean | null>;
  metric: number;
  metrics?: Record<string, number>;
  durationS: number;
}

export interface JobMetrics {
  [key: string]: number | string | LeaderboardRow[] | undefined;
  leaderboard?: LeaderboardRow[];
}

export interface Job {
  id: number;
  projectId: number;
  projectSlug: string;
  projectName: string;
  kind: JobKind;
  name: string;
  status: JobStatus;
  queueRank: number;
  queuePosition?: number;
  requestedGpu: number;
  requestedCpu: number;
  requestedMemoryMb: number;
  /** VRAM the job asked for (shared-GPU placement); undefined = whole GPUs. */
  requestedGpuMemoryMb?: number;
  timeoutMinutes: number;
  assignedGpus?: number[];
  assignedCpus?: number[];
  progress: number;
  currentStage?: JobStage;
  taskType?: TaskType;
  mode?: JobMode;
  modelFamily?: ModelFamily;
  dataSourceId?: number;
  artifactId?: number;
  input: JobInput;
  config?: Record<string, unknown>;
  metrics?: JobMetrics;
  result?: Record<string, unknown>;
  errorMessage?: string;
  cancelReason?: string;
  cancelRequestedBy?: User;
  waitReason?: string;
  startedAt?: string;
  finishedAt?: string;
  createdBy: User;
  createdAt: string;
}

export interface Artifact {
  id: number;
  projectId: number;
  jobId: number;
  name: string;
  version: number;
  kind: ArtifactKind;
  modelFamily: ModelFamily;
  framework: string;
  path: string;
  sizeBytes: number;
  metrics?: Record<string, number>;
  metadata?: Record<string, unknown>;
  isDefault: boolean;
  createdAt: string;
}

export interface ProjectRequest {
  id: number;
  applicant: User;
  title: string;
  purpose: string;
  dataType: DataType;
  taskType: TaskType;
  dataScale: DataScale;
  dataDescription?: string;
  requestedGpu: number;
  requestedCpu: number;
  requestedMemoryMb: number;
  requestedStorageMb: number;
  proposedSlug?: string;
  members: { email: string; role: ProjectRole }[];
  status: RequestStatus;
  reviewer?: User;
  reviewNote?: string;
  reviewedAt?: string;
  projectSlug?: string;
  commentCount: number;
  submittedAt: string;
}

export interface Issue {
  id: number;
  type: IssueType;
  title: string;
  body: string;
  status: IssueStatus;
  author: User;
  assignee?: User;
  projectSlug?: string;
  resolutionNote?: string;
  commentCount: number;
  createdAt: string;
  closedAt?: string;
}

export interface Comment {
  id: number;
  targetType: CommentTarget;
  targetId: number;
  author?: User;
  kind: "comment" | "system";
  body: string;
  createdAt: string;
}

export interface ResourcePool {
  gpuIndices: number[];
  cpuCores: number;
  memoryMb: number;
  maxRunningJobs: number;
  allowBackfill: boolean;
  /** Several jobs may share one GPU when they declare the VRAM they need. */
  gpuShare: boolean;
}

export interface Allocated {
  gpu: number;
  cpu: number;
  memoryMb: number;
  runningJobs: number;
}

export interface GpuJobUsage {
  jobId: number;
  requestedMb?: number;
  measuredMb: number;
}

export interface NodeGpu {
  index: number;
  name: string;
  memoryTotalMb: number;
  memoryUsedMb: number;
  utilization: number;
  jobId?: number;
  jobIds: number[];
  jobs: GpuJobUsage[];
  /** Σ VRAM the driver attributes to our jobs' processes */
  measuredMb?: number;
  /** Σ VRAM reserved by the jobs placed here; equals the total when one of them holds the GPU exclusively. */
  reservedMb?: number;
  /** Compute processes the driver sees on this GPU (any user). */
  processes?: number;
}

export type GpuResetMode = "jobs" | "all" | "device";

export interface GpuResetResult {
  index: number;
  mode: GpuResetMode;
  stoppedJobs: number[];
  killedPids: number[];
  skippedPids: number[];
  command?: string;
  commandOk?: boolean;
  commandOutput?: string;
  memoryUsedMbBefore?: number;
  memoryUsedMbAfter?: number;
}

export type UsageRange = "1h" | "6h" | "24h" | "7d" | "30d";

export interface UsagePoint {
  t: string;
  cpuPct?: number;
  memUsedMb?: number;
  gpuUtil?: number;
  gpuMemUsedMb?: number;
  allocGpu?: number;
  allocCpu?: number;
  allocMemoryMb?: number;
  runningJobs?: number;
  projects: Record<
    string,
    { gpu: number; cpu: number; memoryMb: number; runningJobs: number; cpuActual: number; memActualMb: number }
  >;
}

export interface UsageProject {
  id: number;
  slug: string;
  name: string;
  gpuLimit: number;
  cpuLimit: number;
  memoryLimitMb: number;
  status: ProjectStatus;
}

export interface UsageProjectShare {
  gpuAvg: number;
  cpuAvg: number;
  memoryMbAvg: number;
  gpuOfQuota: number;
  cpuOfQuota: number;
  memoryMbOfQuota: number;
  gpuOfPool: number;
  cpuOfPool: number;
  memoryMbOfPool: number;
  gpuOfNode: number;
  cpuOfNode: number;
  memoryMbOfNode: number;
  cpuActualAvg: number;
  memActualAvgMb: number;
  jobSeconds: number;
}

export interface UsageHistory {
  range: UsageRange;
  bucketS: number;
  sampleIntervalS: number;
  points: UsagePoint[];
  totals: {
    cpuCores: number;
    memoryMb: number;
    gpuCount: number;
    gpuMemoryMb: number;
    poolGpu: number;
    poolCpu: number;
    poolMemoryMb: number;
  };
  projects: UsageProject[];
  projectShare: Record<string, UsageProjectShare>;
}

export interface RunnerInfo {
  kind: "systemd" | "subprocess" | string;
  enforces: { memory: boolean; cpu: boolean; cpuset: boolean };
  memoryWatchdog: boolean;
  trainerPython: string;
  trainerDir: string;
  offline: boolean;
  note: string;
}

export interface NodeStatus {
  gpus: NodeGpu[];
  cpuCores: number;
  cpuUsedCores: number;
  memoryMb: number;
  memoryUsedMb: number;
  diskTotalGb: number;
  diskFreeGb: number;
  allocated: Allocated;
  runner?: RunnerInfo;
}

export type ZooStatus = "present" | "missing" | "mismatch" | "importing" | "error";

export interface ZooTask {
  weightId: string;
  source: string;
  state: "running" | "done" | "error";
  progress: number;
  downloadedMb: number;
  totalMb?: number;
  message?: string;
  startedAt: string;
  finishedAt?: string;
}

export interface ModelZooEntry {
  id: string;
  family: string;
  families: string[];
  file: string;
  license?: string;
  source?: string;
  kind: "file" | "hf_repo" | string;
  present: boolean;
  status: ZooStatus;
  sizeBytes?: number;
  sha256Expected?: string;
  sha256Actual?: string;
  importedAt?: string;
  importedFrom?: string;
  task?: ZooTask;
}

export interface AuditLog {
  id: number;
  actor?: User;
  action: string;
  targetType: string;
  targetId?: number;
  reason?: string;
  payload?: Record<string, unknown>;
  createdAt: string;
}

export type LogLevel = "INFO" | "WARN" | "ERROR" | "DEBUG" | "SYSTEM";

export interface LogLine {
  n: number;
  ts: string;
  level: LogLevel;
  text: string;
}

/** GET /catalog — kept close to the yaml (snake_case keys) because it is configuration, not a record. */
export interface CatalogFamily {
  label: string;
  group: string;
  framework: string;
  supports: Partial<Record<DataType, TaskType[]>>;
  inference_modes: InferenceMode[];
  resources: { gpu: "none" | "optional" | "required"; cpu_min: number; memory_mb_min: number };
  min_rows?: number;
  max_rows?: number;
  defaults: Record<string, unknown>;
  search_space: Record<string, { type: string; low?: number; high?: number; log?: boolean; choices?: unknown[] }>;
  weights: string[];
  weights_ready?: boolean;
  sop: string;
}

export interface Catalog {
  version: number;
  data_types: Record<DataType, { label: string; formats: string[] }>;
  tasks: Record<
    TaskType,
    { label: string; metrics: string[]; direction: "maximize" | "minimize"; needs_labels: boolean }
  >;
  families: Record<string, CatalogFamily>;
  automl: {
    data_type: DataType;
    tasks: TaskType[];
    candidates: string[];
    rules?: { if: string; drop?: string[]; prefer?: string[] }[];
    budget: { max_trials: number; time_budget_minutes: number };
  }[];
}

export interface PreprocessParam {
  name: string;
  label: string;
  type: "int" | "float" | "str" | "bool" | "choice" | "columns";
  default?: unknown;
  min?: number;
  max?: number;
  choices?: unknown[];
  help?: string;
}

export interface PreprocessOp {
  id: string;
  label: string;
  description: string;
  dataTypes: DataType[];
  params: PreprocessParam[];
  geometric: boolean;
  fitted: boolean;
  dropsRows: boolean;
}

export interface Upload {
  id: number;
  projectId: number;
  originalFilename: string;
  sizeBytes: number;
  format: string;
  detectedSpec?: Record<string, unknown>;
  status: string;
  expiresAt: string;
}

/** POST /projects/{slug}/uploads/{id}/preview — payload keys mirror the backend (snake_case). */
export interface PreviewPayload {
  data_type: DataType;
  steps: string[];
  before: PreviewSide;
  after: PreviewSide;
}
export interface PreviewSide {
  row_count?: number;
  columns?: string[];
  rows?: Record<string, unknown>[];
  /** Tabular / text previews: one entry per column. Sequence / spectrum / image previews: one summary object. */
  stats?: ColumnStat[] | ArrayStat;
  images?: { id: string; width: number; height: number; mode: string; mean: number; std: number; png_base64: string }[];
  curves?: { id: string; values: number[][] }[];
  points_step?: number;
}

export interface ColumnStat {
  column: string;
  dtype: string;
  missing: number;
  mean?: number;
  std?: number;
  min?: number;
  max?: number;
  unique?: number;
}

export interface ArrayStat {
  shape: number[];
  mean: number;
  std: number;
  min: number;
  max: number;
  nan_ratio?: number;
}

/** Standalone preprocessing tool: a temp file on the backend (no database row), gone after download / TTL. */
export interface ToolUpload {
  id: string;
  dataType: DataType;
  originalFilename: string;
  sizeBytes: number;
  format: string;
  detectedSpec?: Record<string, unknown>;
  expiresAt: string;
  createdAt: string;
}

export interface ToolDefaults {
  gpuLimit: number;
  cpuLimit: number;
  memoryLimitMb: number;
  storageQuotaMb: number;
  maxConcurrentJobs: number;
  resultTtlHours: number;
}

export interface Capacity {
  pool: ResourcePool;
  allocated: Allocated;
}
