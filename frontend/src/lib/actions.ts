"use server";

// Server actions: the only place the UI mutates backend state. Each returns {ok} | {ok:false, error}
// so client components can toast the backend's message; successful ones revalidate the affected paths.
// Every input is validated with the zod schemas in src/lib/schemas.ts before it reaches the backend, and every
// slug / id interpolated into a path is URL-encoded.
import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";
import { toGpuReset, toJob, toProject, toUser } from "@/lib/api/mappers";
import { ApiError, apiFetch, AUTH_MODE, errorMessage, PUBLIC_URL, readSessionJwt, TOKEN_COOKIE } from "@/lib/backend";
import { safeNext } from "@/lib/safe-next";
import {
  analysisKindEnum,
  applicationBodySchema,
  approveBodySchema,
  commentBodySchema,
  dataSourceBodySchema,
  gpuResetSchema,
  idSchema,
  issueBodySchema,
  issueUpdateBodySchema,
  jobCreateBodySchema,
  memberAddSchema,
  memberRoleEnum,
  previewBodySchema,
  projectUpdateBodySchema,
  queuePositionEnum,
  quotaBodySchema,
  resolutionNoteSchema,
  resourcePoolSchema,
  reviewNoteSchema,
  slugSchema,
  stopReasonSchema,
  toolAnalyzeSchema,
  toolPoolSchema,
  toolProcessSchema,
  toolUploadIdSchema,
  userUpdateBodySchema,
  weightIdSchema,
  weightImportSchema,
  zodMessage,
} from "@/lib/schemas";
import type { GpuResetMode, GpuResetResult, Job, PreprocessStep, PreviewPayload, Project } from "@/types/domain";

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

// --- project applications (a project is created when someone applies) ------------------------------

export async function applyProjectAction(body: J): Promise<ActionResult<Project>> {
  const r = await run(async () =>
    toProject(await apiFetch<J>("/projects", { method: "POST", body: applicationBodySchema.parse(body) })),
  );
  if (r.ok) revalidatePath("/projects");
  return r;
}

export async function updateApplicationAction(slug: string, body: J): Promise<ActionResult<Project>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    const payload = applicationBodySchema.partial().parse(body);
    return toProject(await apiFetch<J>(`/projects/${enc(s)}/application`, { method: "PATCH", body: payload }));
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function withdrawApplicationAction(slug: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/projects/${enc(slugSchema.parse(slug))}/withdraw`, { method: "POST" });
    return undefined;
  });
  if (r.ok) revalidatePath("/projects");
  return r;
}

export async function reviewApplicationAction(slug: string): Promise<ActionResult<Project>> {
  const r = await run(async () =>
    toProject(await apiFetch<J>(`/projects/${enc(slugSchema.parse(slug))}/review`, { method: "POST" })),
  );
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function approveApplicationAction(slug: string, body: J): Promise<ActionResult<Project>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    const payload = approveBodySchema.parse(body);
    return toProject(await apiFetch<J>(`/projects/${enc(s)}/approve`, { method: "POST", body: payload }));
  });
  if (r.ok) {
    revalidatePath(`/projects/${slug}`, "layout");
    revalidatePath("/projects");
    revalidatePath("/admin");
  }
  return r;
}

export async function rejectApplicationAction(slug: string, reviewNote: string): Promise<ActionResult<Project>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    const review_note = reviewNoteSchema.parse(reviewNote);
    return toProject(await apiFetch<J>(`/projects/${enc(s)}/reject`, { method: "POST", body: { review_note } }));
  });
  if (r.ok) {
    revalidatePath(`/projects/${slug}`, "layout");
    revalidatePath("/projects");
  }
  return r;
}

export async function completeProjectAction(slug: string): Promise<ActionResult<Project>> {
  const r = await run(async () =>
    toProject(await apiFetch<J>(`/projects/${enc(slugSchema.parse(slug))}/complete`, { method: "POST" })),
  );
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function reopenProjectAction(slug: string): Promise<ActionResult<Project>> {
  const r = await run(async () =>
    toProject(await apiFetch<J>(`/projects/${enc(slugSchema.parse(slug))}/reopen`, { method: "POST" })),
  );
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

const commentTargetEnum = z.enum(["issue", "application"]);

/** `target` "issue" takes the issue id; "application" takes the project slug (review thread of its application). */
export async function addCommentAction(
  target: "issue" | "application",
  id: number | string,
  body: string,
): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const t = commentTargetEnum.parse(target);
    const text = commentBodySchema.parse(body);
    const path =
      t === "issue"
        ? `/issues/${idSchema.parse(id)}/comments`
        : `/projects/${enc(slugSchema.parse(String(id)))}/application/comments`;
    await apiFetch<J>(path, { method: "POST", body: { body: text } });
    return undefined;
  });
  if (r.ok) revalidatePath(target === "issue" ? `/discussions/${id}` : `/projects/${id}/application`);
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

/** Author or admin edits a thread's title / type / body (`PATCH /issues/{id}`; the backend decides who may). */
export async function updateIssueAction(id: number, body: J): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const iid = idSchema.parse(id);
    await apiFetch<J>(`/issues/${iid}`, { method: "PATCH", body: issueUpdateBodySchema.parse(body) });
    return undefined;
  });
  if (r.ok) {
    revalidatePath(`/discussions/${id}`);
    revalidatePath("/discussions");
  }
  return r;
}

/** Author or admin rewrites one issue comment (`PATCH /issues/{id}/comments/{comment_id}`). */
export async function updateCommentAction(
  issueId: number,
  commentId: number,
  body: string,
): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const iid = idSchema.parse(issueId);
    const cid = idSchema.parse(commentId);
    const text = commentBodySchema.parse(body);
    await apiFetch<J>(`/issues/${iid}/comments/${cid}`, { method: "PATCH", body: { body: text } });
    return undefined;
  });
  if (r.ok) revalidatePath(`/discussions/${issueId}`);
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
    revalidatePath("/admin");
  }
  return r;
}

export async function updateQuotaAction(slug: string, body: J): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    await apiFetch<J>(`/projects/${enc(s)}/quota`, { method: "PATCH", body: quotaBodySchema.parse(body) });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
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

/** Add a member picked from the autocomplete (`UserPicker`): by user id instead of username / e-mail. */
export async function addMemberByIdAction(
  slug: string,
  userId: number,
  role: string,
): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const s = slugSchema.parse(slug);
    const payload = memberAddSchema.parse({ user_id: idSchema.parse(userId), role });
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

/** IMAGE previews: `thumb` = longest side of the thumbnails, `imageIds` = only these entries (lightbox). */
export interface PreviewOptions {
  thumb?: number;
  imageIds?: string[];
}

export async function previewPreprocessAction(
  slug: string,
  uploadId: number,
  steps: PreprocessStep[],
  spec: J,
  sample = 5,
  opts: PreviewOptions = {},
): Promise<ActionResult<PreviewPayload>> {
  return run(() => {
    const s = slugSchema.parse(slug);
    const uid = idSchema.parse(uploadId);
    const payload = previewBodySchema.parse({ steps, spec, sample, thumb: opts.thumb, image_ids: opts.imageIds });
    return apiFetch<PreviewPayload>(`/projects/${enc(s)}/uploads/${uid}/preview`, { method: "POST", body: payload });
  });
}

// --- standalone preprocessing tool -----------------------------------------------------------------

export async function previewToolAction(
  id: string,
  steps: PreprocessStep[],
  spec: J,
  sample = 5,
  opts: PreviewOptions = {},
): Promise<ActionResult<PreviewPayload>> {
  return run(() => {
    const uid = toolUploadIdSchema.parse(id);
    const payload = previewBodySchema.parse({ steps, spec, sample, thumb: opts.thumb, image_ids: opts.imageIds });
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

export async function updateToolPoolAction(d: {
  gpuLimit: number;
  cpuLimit: number;
  memoryLimitMb: number;
  storageQuotaMb: number;
  maxConcurrentJobs: number;
  maxJobsPerUser: number;
  resultTtlHours: number;
}): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const v = toolPoolSchema.parse(d);
    await apiFetch<J>("/admin/settings/tool-pool", {
      method: "PUT",
      body: {
        gpu_limit: v.gpuLimit,
        cpu_limit: v.cpuLimit,
        memory_limit_mb: v.memoryLimitMb,
        storage_quota_mb: v.storageQuotaMb,
        max_concurrent_jobs: v.maxConcurrentJobs,
        max_jobs_per_user: v.maxJobsPerUser,
        result_ttl_hours: v.resultTtlHours,
      },
    });
    return undefined;
  });
  if (r.ok) {
    revalidatePath("/admin");
    revalidatePath("/tools");
  }
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
    revalidatePath(`/projects/${slug}/infer`);
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
