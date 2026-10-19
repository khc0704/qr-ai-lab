// zod schemas shared by the forms (react-hook-form resolvers) and the server actions (src/lib/actions.ts),
// so a payload is validated once on the client for messages and once more on the server before it reaches the
// backend. Client-safe: no server imports. Field messages are the user-facing copy (Traditional Chinese).
import { z } from "zod";

// --- enums (mirror src/types/domain.ts; the backend is the source of truth) ---------------------------------

export const dataTypeEnum = z.enum(["TABULAR", "IMAGE", "SEQUENCE", "TEXT", "SPECTRUM"]);
export const taskTypeEnum = z.enum(["classification", "regression", "detection", "segmentation", "anomaly_detection"]);
export const dataScaleEnum = z.enum(["tiny", "small", "medium", "large"]);
export const issueTypeEnum = z.enum(["question", "bug", "feature"]);
// superadmin is exactly one account fixed by the backend (SUPERADMIN_USERNAME); the UI assigns at most admin.
export const assignableRoleEnum = z.enum(["admin", "user"]);
export const memberRoleEnum = z.enum(["maintainer", "member", "viewer"]);
export const dataFormatEnum = z.enum([
  "csv",
  "parquet",
  "image_folder",
  "coco",
  "yolo",
  "npy",
  "jsonl",
  "spectrum_csv",
]);
export const analysisKindEnum = z.enum(["tabular_profile", "image_quality"]);
export const gpuResetModeEnum = z.enum(["jobs", "all", "device"]);
export const queuePositionEnum = z.enum(["top", "up", "down", "bottom"]);

// --- primitives --------------------------------------------------------------------------------------------

export const idSchema = z.number().int().positive();
/** Project slug as the backend accepts it (lowercase-with-dashes; personal workspaces are `ws-<username>`). */
export const slugSchema = z
  .string()
  .min(1)
  .max(100)
  .regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/, "slug 只能是英數、點、底線與連字號");
export const proposedSlugSchema = z.string().regex(/^[a-z0-9][a-z0-9-]{1,62}$/, "小寫英數與連字號，2–63 字");
/** Tool upload ids are opaque hex strings issued by the backend. */
export const toolUploadIdSchema = z.string().regex(/^[A-Za-z0-9_-]{1,64}$/, "上傳 id 格式不正確");
export const weightIdSchema = z.string().min(1).max(200);
const jsonRecord = z.record(z.string(), z.unknown());

export const preprocessStepSchema = z.object({ op: z.string().min(1), params: jsonRecord.optional() });
export const preprocessStepsSchema = z.array(preprocessStepSchema).max(50);

// --- forms (values the user types; camelCase) ---------------------------------------------------------------

export const applicationFormSchema = z.object({
  title: z.string().min(4, "至少 4 個字").max(200),
  purpose: z.string().min(20, "請說明目的與背景（至少 20 個字）"),
  dataType: dataTypeEnum,
  taskType: taskTypeEnum,
  dataScale: dataScaleEnum,
  dataDescription: z.string().optional(),
  requestedGpu: z.number().int().min(0),
  requestedCpu: z.number().min(1),
  requestedMemoryMb: z.number().int().min(1024),
  requestedStorageMb: z.number().int().min(1024),
  proposedSlug: proposedSlugSchema.optional().or(z.literal("")),
  members: z.array(z.object({ email: z.string().email("email 格式不正確"), role: memberRoleEnum })),
});
export type ApplicationFormValues = z.infer<typeof applicationFormSchema>;

export const issueFormSchema = z.object({
  type: issueTypeEnum,
  title: z.string().min(4, "至少 4 個字").max(200),
  body: z.string().min(10, "請多描述一些（至少 10 個字）"),
  projectSlug: z.string().optional(),
});
export type IssueFormValues = z.infer<typeof issueFormSchema>;

// --- backend bodies (snake_case, what the actions forward) ---------------------------------------------------

export const applicationBodySchema = z.object({
  title: applicationFormSchema.shape.title,
  purpose: applicationFormSchema.shape.purpose,
  data_type: dataTypeEnum,
  task_type: taskTypeEnum,
  data_scale: dataScaleEnum,
  data_description: z.string().max(4000).nullable().optional(),
  requested_gpu: z.number().int().min(0),
  requested_cpu: z.number().min(1),
  requested_memory_mb: z.number().int().min(1024),
  requested_storage_mb: z.number().int().min(1024),
  proposed_slug: proposedSlugSchema.nullable().optional(),
  members: applicationFormSchema.shape.members,
});

export const issueBodySchema = z.object({
  type: issueTypeEnum,
  title: issueFormSchema.shape.title,
  body: issueFormSchema.shape.body,
  project_slug: slugSchema.nullable().optional(),
});

/** Author / admin edit of a thread (title, type, body). */
export const issueEditFormSchema = issueFormSchema.pick({ type: true, title: true, body: true });
export type IssueEditFormValues = z.infer<typeof issueEditFormSchema>;

/** `PATCH /issues/{id}`: every field optional, at least one present. */
export const issueUpdateBodySchema = z
  .object({
    type: issueTypeEnum.optional(),
    title: issueFormSchema.shape.title.optional(),
    body: issueFormSchema.shape.body.optional(),
  })
  .refine((v) => v.type !== undefined || v.title !== undefined || v.body !== undefined, "沒有要更新的欄位");

export const approveBodySchema = z.object({
  name: z.string().trim().min(1).max(120).optional(),
  gpu_limit: z.number().int().min(0),
  cpu_limit: z.number().min(1),
  memory_limit_mb: z.number().int().min(1),
  storage_quota_mb: z.number().int().min(1),
  max_concurrent_jobs: z.number().int().min(1).max(64),
  members: z.array(z.object({ email: z.string().email(), role: memberRoleEnum })),
  review_note: z.string().trim().max(2000).optional(),
});

export const reviewNoteSchema = z.string().trim().min(1, "請填寫理由").max(2000);
export const commentBodySchema = z.string().trim().min(1, "留言不能是空的").max(5000);
export const resolutionNoteSchema = z.string().trim().max(2000);
export const stopReasonSchema = z.string().trim().min(2, "理由至少 2 個字").max(255);

export const projectUpdateBodySchema = z.object({
  name: z.string().trim().min(1, "名稱不能是空的").max(200).optional(),
  description: z.string().max(4000).optional(),
});

export const quotaBodySchema = z.object({
  gpu_limit: z.number().int().min(0),
  cpu_limit: z.number().min(0),
  memory_limit_mb: z.number().int().min(0),
  storage_quota_mb: z.number().int().min(0),
  max_concurrent_jobs: z.number().int().min(1).max(64),
});

export const userUpdateBodySchema = z
  .object({ role: assignableRoleEnum.optional(), is_active: z.boolean().optional() })
  .refine((v) => v.role !== undefined || v.is_active !== undefined, "沒有要更新的欄位");

/** Either `user_id` (UserPicker) or the legacy `username_or_email`; the backend requires one of them. */
export const memberAddSchema = z
  .object({
    user_id: idSchema.optional(),
    username_or_email: z.string().trim().min(1, "請輸入帳號或 email").max(200).optional(),
    role: memberRoleEnum,
  })
  .refine((v) => v.user_id !== undefined || v.username_or_email !== undefined, "請選擇使用者");

export const dataSourceBodySchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("minio"),
    name: z.string().trim().min(1).max(200),
    endpoint: z.string().trim().min(1).max(500),
    bucket: z.string().trim().min(1).max(200),
    object_path: z.string().trim().min(1).max(1000),
    access_key: z.string().max(500).nullable().optional(),
    secret_key: z.string().max(500).nullable().optional(),
    format: dataFormatEnum,
  }),
  z.object({
    kind: z.literal("url"),
    name: z.string().trim().min(1).max(200),
    url: z.string().trim().url("URL 格式不正確").max(2000),
    headers: z.record(z.string(), z.string()).nullable().optional(),
    format: dataFormatEnum,
  }),
]);

export const previewBodySchema = z.object({
  steps: preprocessStepsSchema,
  spec: jsonRecord,
  sample: z.number().int().min(1).max(500),
});

export const jobCreateBodySchema = z.object({
  kind: z.enum(["train", "inference"]),
  name: z.string().trim().min(1).max(200),
  input: z.object({
    kind: z.enum(["upload", "data_source", "inline"]),
    upload_id: idSchema.optional(),
    data_source_id: idSchema.nullable().optional(),
    rows: z.array(z.unknown()).max(10000).optional(),
    spec: jsonRecord,
  }),
  task_type: taskTypeEnum,
  mode: z.enum(["manual", "auto"]).optional(),
  model_family: z.string().max(100).optional(),
  config: jsonRecord.optional(),
  artifact_id: idSchema.nullable().optional(),
  requested_gpu: z.number().int().min(0),
  requested_cpu: z.number().positive(),
  requested_memory_mb: z.number().int().positive(),
  requested_gpu_memory_mb: z.number().int().positive().nullable().optional(),
  timeout_minutes: z.number().int().positive(),
});

export const toolProcessSchema = z.object({
  steps: preprocessStepsSchema,
  spec: jsonRecord,
  name: z.string().trim().max(200).optional(),
});

export const toolAnalyzeSchema = z.object({
  analysis: analysisKindEnum,
  params: jsonRecord,
  name: z.string().trim().max(200).optional(),
});

export const toolPoolSchema = z.object({
  gpuLimit: z.number().int().min(0),
  cpuLimit: z.number().min(0.5),
  memoryLimitMb: z.number().int().min(256),
  storageQuotaMb: z.number().int().min(64),
  maxConcurrentJobs: z.number().int().min(1).max(32),
  maxJobsPerUser: z.number().int().min(1).max(32),
  resultTtlHours: z.number().int().min(1),
});

export const resourcePoolSchema = z.object({
  gpuIndices: z.array(z.number().int().min(0)),
  cpuCores: z.number().int().min(1),
  memoryMb: z.number().int().min(1024),
  maxRunningJobs: z.number().int().min(1).max(64),
  allowBackfill: z.boolean(),
  gpuShare: z.boolean(),
});

export const gpuResetSchema = z.object({
  index: z.number().int().min(0),
  mode: gpuResetModeEnum,
  reason: z.string().trim().min(1, "請填寫理由").max(255),
});

export const weightImportSchema = z
  .object({
    source: z.enum(["url", "path"]),
    url: z.string().trim().url().max(2000).optional(),
    path: z.string().trim().min(1).max(1000).optional(),
  })
  .refine((v) => (v.source === "url" ? Boolean(v.url) : Boolean(v.path)), "請填寫 URL 或路徑");

/** One line for toasts: the first issue's path and message. */
export function zodMessage(e: z.ZodError): string {
  const issue = e.issues[0];
  if (!issue) return "輸入格式不正確";
  const path = issue.path.map(String).join(".");
  return path ? `${path}: ${issue.message}` : issue.message;
}
