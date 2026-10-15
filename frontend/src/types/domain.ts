// Domain types mirroring docs/DATABASE.md. Keep field names in camelCase on the frontend;
// the API layer (src/lib/api) is responsible for mapping snake_case responses.

export type DataType = "TABULAR" | "IMAGE" | "SEQUENCE" | "TEXT" | "SPECTRUM";
export type TaskType = "classification" | "regression" | "detection" | "segmentation" | "anomaly_detection";
export type ModelFamily =
  | "tabular.linear"
  | "tabular.svm"
  | "tabular.random_forest"
  | "tabular.xgboost"
  | "vision.yolo"
  | "vision.dino"
  | "sequence.patch_autoencoder"
  | "text.bert_classifier";
export type SystemRole = "admin" | "user";
export type ProjectRole = "owner" | "maintainer" | "member" | "viewer";
export type ProjectStatus = "active" | "archived";
export type JobKind = "train" | "inference";
export type JobStatus = "queued" | "scheduled" | "running" | "succeeded" | "failed" | "cancelled";
export type JobMode = "manual" | "auto";
export type JobStage = "fetching" | "preparing" | "training" | "evaluating" | "exporting" | "predicting";
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
  lastCheckOk?: boolean;
  lastCheckMessage?: string;
  lastCheckedAt?: string;
  createdBy: User;
  createdAt: string;
}

export interface JobInput {
  kind: InputKind;
  originalFilename?: string;
  sizeBytes?: number;
  dataSourceName?: string;
  format: DataFormat | "json";
  spec: Record<string, unknown>;
}

export interface LeaderboardRow {
  trial: number;
  family: ModelFamily;
  params: Record<string, number | string>;
  metric: number;
  durationS: number;
}

export interface JobMetrics {
  [key: string]: number | LeaderboardRow[] | undefined;
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
  requestedGpu: number;
  requestedCpu: number;
  requestedMemoryMb: number;
  timeoutMinutes: number;
  assignedGpus?: number[];
  progress: number;
  currentStage?: JobStage;
  taskType?: TaskType;
  mode?: JobMode;
  modelFamily?: ModelFamily;
  artifactId?: number;
  input: JobInput;
  config?: Record<string, unknown>;
  metrics?: JobMetrics;
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
}

export interface NodeGpu {
  index: number;
  name: string;
  memoryTotalMb: number;
  memoryUsedMb: number;
  utilization: number;
  jobId?: number;
}

export interface NodeStatus {
  gpus: NodeGpu[];
  cpuCores: number;
  cpuUsedCores: number;
  memoryMb: number;
  memoryUsedMb: number;
  diskTotalGb: number;
  diskFreeGb: number;
  /** Sum of resources currently allocated to scheduled/running jobs. */
  allocated: { gpu: number; cpu: number; memoryMb: number; runningJobs: number };
}

export interface AuditLog {
  id: number;
  actor?: User;
  action: string;
  targetType: string;
  targetId?: number;
  reason?: string;
  createdAt: string;
}

export type LogLevel = "INFO" | "WARN" | "ERROR" | "DEBUG" | "SYSTEM";

export interface LogLine {
  n: number;
  ts: string;
  level: LogLevel;
  text: string;
}
