"use server";

// Server actions: the only place the UI mutates backend state. Each returns {ok} | {ok:false, error}
// so client components can toast the backend's message; successful ones revalidate the affected paths.
// Every input is validated with the zod schemas in src/lib/schemas.ts before it reaches the backend, and every
// slug / id interpolated into a path is URL-encoded.
import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";
import { toGpuReset, toJob, toProject, toRequest, toUser } from "@/lib/api/mappers";
import { ApiError, apiFetch, AUTH_MODE, errorMessage, PUBLIC_URL, readSessionJwt, TOKEN_COOKIE } from "@/lib/backend";
import { safeNext } from "@/lib/safe-next";
import {
  analysisKindEnum,
  approveRequestBodySchema,
  commentBodySchema,
  dataSourceBodySchema,
  gpuResetSchema,
  idSchema,
  issueBodySchema,
  jobCreateBodySchema,
  memberAddSchema,
  memberRoleEnum,
  previewBodySchema,
  projectRequestBodySchema,
  projectUpdateBodySchema,
  queuePositionEnum,
  quotaBodySchema,
  resolutionNoteSchema,
  resourcePoolSchema,
  reviewNoteSchema,
  slugSchema,
  stopReasonSchema,
  toolAnalyzeSchema,
  toolDefaultsSchema,
  toolProcessSchema,
  toolUploadIdSchema,
  userUpdateBodySchema,
  weightIdSchema,
  weightImportSchema,
  zodMessage,
} from "@/lib/schemas";
import type {
  GpuResetMode,
  GpuResetResult,
  Job,
  PreprocessStep,
  PreviewPayload,
  Project,
  ProjectRequest,
} from "@/types/domain";

type J = Record<string, unknown>;
export type ActionResult<T = undefined> = { ok: true; data: T } | { ok: false; error: string; code?: string };

const enc = encodeURIComponent;

async function run<T>(fn: () => Promise<T>): Promise<ActionResult<T>> {
  try {
    return { ok: true, data: await fn() };
  } catch (e) {
    if (e instanceof z.ZodError) return { ok: false, error: `輸入格式不正確：${zodMessage(e)}`, code: "INVALID_INPUT" };
    return { ok: false, error: errorMessage(e), code: e instanceof ApiError ? e.code : undefined };
  }
}

// --- auth ------------------------------------------------------------------------------------------

export interface LoginState {
  error?: string;
}

const loginSchema = z.object({
  username: z.string().trim().min(1, "請輸入帳號").max(200),
  password: z.string().min(1, "請輸入密碼").max(1000),
});

export async function loginAction(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const parsed = loginSchema.safeParse({ username: formData.get("username"), password: formData.get("password") });
  if (!parsed.success) return { error: zodMessage(parsed.error) };
  const next = safeNext(formData.get("next"));
  let token: string;
  let expiresIn: number;
  try {
    const r = await apiFetch<{ access_token: string; expires_in: number }>("/auth/login", {
      method: "POST",
      body: parsed.data,
      token: null,
    });
    token = r.access_token;
    expiresIn = r.expires_in;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return { error: "帳號或密碼不正確" };
    return { error: `無法連線到後端：${errorMessage(e)}` };
  }
  (await cookies()).set(TOKEN_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production" && process.env.COOKIE_SECURE !== "0",
    path: "/",
    maxAge: expiresIn,
  });
  redirect(next);
}

export async function logoutAction(): Promise<void> {
  if (AUTH_MODE === "keycloak") {
    // Decode only (no refresh): we just need the id token for Keycloak's end-session hint.
    const jwt = await readSessionJwt();
    const { signOut } = await import("@/auth");
    await signOut({ redirect: false });
    // End the Keycloak SSO session too, otherwise the next "login" silently signs the same user back in.
    const issuer = process.env.AUTH_KEYCLOAK_ISSUER;
    if (issuer) {
      const url = new URL(`${issuer}/protocol/openid-connect/logout`);
      if (jwt?.idToken) url.searchParams.set("id_token_hint", jwt.idToken);
      url.searchParams.set("post_logout_redirect_uri", `${PUBLIC_URL}/login`);
      redirect(url.toString());
    }
    redirect("/login");
  }
  (await cookies()).delete(TOKEN_COOKIE);
  redirect("/login");
}

// --- project requests ------------------------------------------------------------------------------

export async function createProjectRequestAction(body: J): Promise<ActionResult<ProjectRequest>> {
  const r = await run(async () =>
    toRequest(await apiFetch<J>("/project-requests", { method: "POST", body: projectRequestBodySchema.parse(body) })),
  );
  if (r.ok) revalidatePath("/project-requests");
  return r;
}

export async function withdrawRequestAction(id: number): Promise<ActionResult<ProjectRequest>> {
  const r = await run(async () => {
    const rid = idSchema.parse(id);
    return toRequest(await apiFetch<J>(`/project-requests/${rid}/withdraw`, { method: "POST" }));
  });
  if (r.ok) revalidatePath(`/project-requests/${id}`);
  return r;
}

export async function reviewRequestAction(id: number): Promise<ActionResult<ProjectRequest>> {
  const r = await run(async () => {
    const rid = idSchema.parse(id);
    return toRequest(await apiFetch<J>(`/project-requests/${rid}/review`, { method: "POST" }));
  });
  if (r.ok) revalidatePath(`/project-requests/${id}`);
  return r;
}

export async function approveRequestAction(id: number, body: J): Promise<ActionResult<Project>> {
  const r = await run(async () => {
    const rid = idSchema.parse(id);
    const payload = approveRequestBodySchema.parse(body);
    return toProject(await apiFetch<J>(`/project-requests/${rid}/approve`, { method: "POST", body: payload }));
  });
  if (r.ok) {
    revalidatePath(`/project-requests/${id}`);
    revalidatePath("/projects");
    revalidatePath("/admin/requests");
  }
  return r;
}

export async function rejectRequestAction(id: number, reviewNote: string): Promise<ActionResult<ProjectRequest>> {
  const r = await run(async () => {
    const rid = idSchema.parse(id);
    const review_note = reviewNoteSchema.parse(reviewNote);
    return toRequest(await apiFetch<J>(`/project-requests/${rid}/reject`, { method: "POST", body: { review_note } }));
  });
  if (r.ok) revalidatePath(`/project-requests/${id}`);
  return r;
}

const commentTargetEnum = z.enum(["issue", "project_request"]);

export async function addCommentAction(
  target: "issue" | "project_request",
  id: number,
  body: string,
): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const t = commentTargetEnum.parse(target);
    const tid = idSchema.parse(id);
    const text = commentBodySchema.parse(body);
    const base = t === "issue" ? "/issues" : "/project-requests";
    await apiFetch<J>(`${base}/${tid}/comments`, { method: "POST", body: { body: text } });
    return undefined;
  });
  if (r.ok) revalidatePath(target === "issue" ? `/discussions/${id}` : `/project-requests/${id}`);
  return r;
}

// --- issues ----------------------------------------------------------------------------------------

export async function createIssueAction(body: J): Promise<ActionResult<{ id: number }>> {
  const r = await run(async () => {
    const i = await apiFetch<J>("/issues", { method: "POST", body: issueBodySchema.parse(body) });
    return { id: Number(i.id) };
  });
  if (r.ok) revalidatePath("/discussions");
  return r;
}

export async function closeIssueAction(id: number, note: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const iid = idSchema.parse(id);
    const resolution_note = resolutionNoteSchema.parse(note);
    await apiFetch<J>(`/issues/${iid}/close`, { method: "POST", body: { resolution_note } });
    return undefined;
  });
  if (r.ok) revalidatePath(`/discussions/${id}`);
  return r;
}

export async function reopenIssueAction(id: number): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/issues/${idSchema.parse(id)}/reopen`, { method: "POST" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/discussions/${id}`);
  return r;
}

export async function deleteIssueAction(id: number): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/issues/${idSchema.parse(id)}`, { method: "DELETE" });
    return undefined;
  });
  if (r.ok) revalidatePath("/discussions");
  return r;
}

// --- projects --------------------------------------------------------------------------------------

export async function updateProjectAction(slug: string, body: J): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    await apiFetch<J>(`/projects/${enc(s)}`, { method: "PATCH", body: projectUpdateBodySchema.parse(body) });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function archiveProjectAction(slug: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/projects/${enc(slugSchema.parse(slug))}/archive`, { method: "POST" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function deleteProjectAction(slug: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/projects/${enc(slugSchema.parse(slug))}`, { method: "DELETE" });
    return undefined;
  });
  if (r.ok) {
    revalidatePath("/projects");
    revalidatePath("/admin/quotas");
  }
  return r;
}

export async function updateQuotaAction(slug: string, body: J): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    await apiFetch<J>(`/projects/${enc(s)}/quota`, { method: "PATCH", body: quotaBodySchema.parse(body) });
    return undefined;
  });
  if (r.ok) revalidatePath("/admin/quotas");
  return r;
}

export async function addMemberAction(
  slug: string,
  usernameOrEmail: string,
  role: string,
): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    const payload = memberAddSchema.parse({ username_or_email: usernameOrEmail, role });
    await apiFetch<J>(`/projects/${enc(s)}/members`, { method: "POST", body: payload });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function updateMemberAction(slug: string, userId: number, role: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    const uid = idSchema.parse(userId);
    const payload = { role: memberRoleEnum.parse(role) };
    await apiFetch<J>(`/projects/${enc(s)}/members/${uid}`, { method: "PATCH", body: payload });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function removeMemberAction(slug: string, userId: number): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    await apiFetch<J>(`/projects/${enc(s)}/members/${idSchema.parse(userId)}`, { method: "DELETE" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

// --- data sources / uploads ------------------------------------------------------------------------

export async function createDataSourceAction(slug: string, body: J): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    const payload = dataSourceBodySchema.parse(body);
    const ds = await apiFetch<J>(`/projects/${enc(s)}/data-sources`, { method: "POST", body: payload });
    await apiFetch<J>(`/projects/${enc(s)}/data-sources/${idSchema.parse(Number(ds.id))}/check`, { method: "POST" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}/data-sources`);
  return r;
}

export async function checkDataSourceAction(slug: string, id: number): Promise<ActionResult<boolean>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    const ds = await apiFetch<J>(`/projects/${enc(s)}/data-sources/${idSchema.parse(id)}/check`, { method: "POST" });
    return Boolean(ds.last_check_ok);
  });
  if (r.ok) revalidatePath(`/projects/${slug}/data-sources`);
  return r;
}

export async function deleteDataSourceAction(slug: string, id: number): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    await apiFetch<J>(`/projects/${enc(s)}/data-sources/${idSchema.parse(id)}`, { method: "DELETE" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}/data-sources`);
  return r;
}

export async function previewPreprocessAction(
  slug: string,
  uploadId: number,
  steps: PreprocessStep[],
  spec: J,
  sample = 5,
): Promise<ActionResult<PreviewPayload>> {
  return run(() => {
    const s = slugSchema.parse(slug);
    const uid = idSchema.parse(uploadId);
    const payload = previewBodySchema.parse({ steps, spec, sample });
    return apiFetch<PreviewPayload>(`/projects/${enc(s)}/uploads/${uid}/preview`, { method: "POST", body: payload });
  });
}

// --- standalone preprocessing tool -----------------------------------------------------------------

export async function previewToolAction(
  id: string,
  steps: PreprocessStep[],
  spec: J,
  sample = 5,
): Promise<ActionResult<PreviewPayload>> {
  return run(() => {
    const uid = toolUploadIdSchema.parse(id);
    const payload = previewBodySchema.parse({ steps, spec, sample });
    return apiFetch<PreviewPayload>(`/tools/uploads/${enc(uid)}/preview`, { method: "POST", body: payload });
  });
}

/** Whole-file preprocessing as a job in the personal workspace (202 → queued job). */
export async function processToolAction(
  id: string,
  steps: PreprocessStep[],
  spec: J,
  name?: string,
): Promise<ActionResult<Job>> {
  const r = await run(async () => {
    const uid = toolUploadIdSchema.parse(id);
    const payload = toolProcessSchema.parse({ steps, spec, name });
    return toJob(await apiFetch<J>(`/tools/uploads/${enc(uid)}/process`, { method: "POST", body: payload }));
  });
  if (r.ok) revalidatePath("/tools", "layout");
  return r;
}

/** Data exploration job (tabular profile / image quality) on a tool upload. */
export async function analyzeToolAction(
  id: string,
  analysis: "tabular_profile" | "image_quality",
  params: J,
  name?: string,
): Promise<ActionResult<Job>> {
  const r = await run(async () => {
    const uid = toolUploadIdSchema.parse(id);
    const payload = toolAnalyzeSchema.parse({ analysis: analysisKindEnum.parse(analysis), params, name });
    return toJob(await apiFetch<J>(`/tools/uploads/${enc(uid)}/analyze`, { method: "POST", body: payload }));
  });
  if (r.ok) revalidatePath("/tools", "layout");
  return r;
}

export async function updateToolDefaultsAction(d: {
  gpuLimit: number;
  cpuLimit: number;
  memoryLimitMb: number;
  storageQuotaMb: number;
  maxConcurrentJobs: number;
  resultTtlHours: number;
}): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const v = toolDefaultsSchema.parse(d);
    await apiFetch<J>("/admin/settings/tool-defaults", {
      method: "PUT",
      body: {
        gpu_limit: v.gpuLimit,
        cpu_limit: v.cpuLimit,
        memory_limit_mb: v.memoryLimitMb,
        storage_quota_mb: v.storageQuotaMb,
        max_concurrent_jobs: v.maxConcurrentJobs,
        result_ttl_hours: v.resultTtlHours,
      },
    });
    return undefined;
  });
  if (r.ok) revalidatePath("/admin");
  return r;
}

export async function deleteToolUploadAction(id: string): Promise<ActionResult<undefined>> {
  return run(async () => {
    await apiFetch<J>(`/tools/uploads/${enc(toolUploadIdSchema.parse(id))}`, { method: "DELETE" });
    return undefined;
  });
}

// --- jobs ------------------------------------------------------------------------------------------

export async function createJobAction(slug: string, body: J): Promise<ActionResult<Job>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    const payload = jobCreateBodySchema.parse(body);
    return toJob(await apiFetch<J>(`/projects/${enc(s)}/jobs`, { method: "POST", body: payload }));
  });
  if (r.ok) {
    revalidatePath(`/projects/${slug}/jobs`);
    revalidatePath("/");
  }
  return r;
}

export async function cancelJobAction(id: number, slug: string): Promise<ActionResult<Job>> {
  const r = await run(async () => toJob(await apiFetch<J>(`/jobs/${idSchema.parse(id)}/cancel`, { method: "POST" })));
  if (r.ok) {
    revalidatePath(`/projects/${slug}/jobs/${id}`);
    revalidatePath(`/projects/${slug}/jobs`);
  }
  return r;
}

export async function setDefaultArtifactAction(
  id: number,
  slug: string,
  value = true,
): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const aid = idSchema.parse(id);
    await apiFetch<J>(`/artifacts/${aid}`, { method: "PATCH", body: { is_default: z.boolean().parse(value) } });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function deleteArtifactAction(id: number, slug: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/artifacts/${idSchema.parse(id)}`, { method: "DELETE" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

// --- admin -----------------------------------------------------------------------------------------

export async function updateUserAction(id: number, body: J): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const uid = idSchema.parse(id);
    toUser(await apiFetch<J>(`/users/${uid}`, { method: "PATCH", body: userUpdateBodySchema.parse(body) }));
    return undefined;
  });
  if (r.ok) revalidatePath("/admin/users");
  return r;
}

export async function updateResourcePoolAction(pool: {
  gpuIndices: number[];
  cpuCores: number;
  memoryMb: number;
  maxRunningJobs: number;
  allowBackfill: boolean;
  gpuShare: boolean;
}): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const v = resourcePoolSchema.parse(pool);
    await apiFetch<J>("/admin/settings/resource-pool", {
      method: "PUT",
      body: {
        gpu_indices: v.gpuIndices,
        cpu_cores: v.cpuCores,
        memory_mb: v.memoryMb,
        max_running_jobs: v.maxRunningJobs,
        allow_backfill: v.allowBackfill,
        gpu_share: v.gpuShare,
      },
    });
    return undefined;
  });
  if (r.ok) revalidatePath("/admin", "layout");
  return r;
}

/** superadmin: free a GPU (stop our jobs / kill every process / device reset). Audited by the backend. */
export async function resetGpuAction(
  index: number,
  mode: GpuResetMode,
  reason: string,
): Promise<ActionResult<GpuResetResult>> {
  const r = await run(async () => {
    const v = gpuResetSchema.parse({ index, mode, reason });
    return toGpuReset(
      await apiFetch<J>(`/admin/gpus/${v.index}/reset`, { method: "POST", body: { mode: v.mode, reason: v.reason } }),
    );
  });
  if (r.ok) {
    revalidatePath("/admin");
    revalidatePath("/admin/queue");
  }
  return r;
}

export async function moveQueueAction(
  jobId: number,
  position: "top" | "up" | "down" | "bottom",
): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const jid = idSchema.parse(jobId);
    const body = { position: queuePositionEnum.parse(position) };
    await apiFetch<J[]>(`/admin/queue/${jid}/move`, { method: "POST", body });
    return undefined;
  });
  if (r.ok) revalidatePath("/admin/queue");
  return r;
}

export async function stopJobAction(jobId: number, reason: string, slug?: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const jid = idSchema.parse(jobId);
    await apiFetch<J>(`/admin/jobs/${jid}/stop`, { method: "POST", body: { reason: stopReasonSchema.parse(reason) } });
    return undefined;
  });
  if (r.ok) {
    revalidatePath("/admin/queue");
    if (slug) revalidatePath(`/projects/${slug}/jobs/${jobId}`);
  }
  return r;
}

/** admin: re-queue a finished job as a new job with the same input and settings. */
export async function restartJobAction(jobId: number, slug: string): Promise<ActionResult<Job>> {
  const r = await run(async () =>
    toJob(await apiFetch<J>(`/admin/jobs/${idSchema.parse(jobId)}/restart`, { method: "POST" })),
  );
  if (r.ok) {
    revalidatePath(`/projects/${slug}/jobs`);
    revalidatePath("/admin/queue");
  }
  return r;
}

/** admin: delete a finished job together with its log / output folder. */
export async function deleteJobAction(jobId: number, slug: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/admin/jobs/${idSchema.parse(jobId)}`, { method: "DELETE" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}/jobs`);
  return r;
}

// --- model zoo (admin) ----------------------------------------------------------------------------

export async function importWeightAction(
  weightId: string,
  body: { source: "url" | "path"; url?: string; path?: string },
): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const wid = weightIdSchema.parse(weightId);
    await apiFetch<J>(`/admin/model-zoo/${enc(wid)}/import`, { method: "POST", body: weightImportSchema.parse(body) });
    return undefined;
  });
  if (r.ok) revalidatePath("/admin/model-zoo");
  return r;
}

export async function deleteWeightAction(weightId: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/admin/model-zoo/${enc(weightIdSchema.parse(weightId))}`, { method: "DELETE" });
    return undefined;
  });
  if (r.ok) revalidatePath("/admin/model-zoo");
  return r;
}
