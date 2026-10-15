"use server";

// Server actions: the only place the UI mutates backend state. Each returns {ok} | {ok:false, error}
// so client components can toast the backend's message; successful ones revalidate the affected paths.
import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { toJob, toProject, toRequest, toUpload, toUser } from "@/lib/api/mappers";
import { ApiError, apiFetch, errorMessage, TOKEN_COOKIE } from "@/lib/backend";
import type { Job, PreprocessStep, PreviewPayload, Project, ProjectRequest, Upload } from "@/types/domain";

type J = Record<string, unknown>;
export type ActionResult<T = undefined> = { ok: true; data: T } | { ok: false; error: string; code?: string };

async function run<T>(fn: () => Promise<T>): Promise<ActionResult<T>> {
  try {
    return { ok: true, data: await fn() };
  } catch (e) {
    return { ok: false, error: errorMessage(e), code: e instanceof ApiError ? e.code : undefined };
  }
}

// --- auth ------------------------------------------------------------------------------------------

export interface LoginState {
  error?: string;
}

export async function loginAction(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const username = String(formData.get("username") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const next = String(formData.get("next") ?? "/");
  let token: string;
  let expiresIn: number;
  try {
    const r = await apiFetch<{ access_token: string; expires_in: number }>("/auth/login", {
      method: "POST",
      body: { username, password },
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
  redirect(next.startsWith("/") && !next.startsWith("//") ? next : "/");
}

export async function logoutAction(): Promise<void> {
  (await cookies()).delete(TOKEN_COOKIE);
  redirect("/login");
}

// --- project requests ------------------------------------------------------------------------------

export async function createProjectRequestAction(body: J): Promise<ActionResult<ProjectRequest>> {
  const r = await run(async () => toRequest(await apiFetch<J>("/project-requests", { method: "POST", body })));
  if (r.ok) revalidatePath("/project-requests");
  return r;
}

export async function updateProjectRequestAction(id: number, body: J): Promise<ActionResult<ProjectRequest>> {
  const r = await run(async () => toRequest(await apiFetch<J>(`/project-requests/${id}`, { method: "PATCH", body })));
  if (r.ok) revalidatePath(`/project-requests/${id}`);
  return r;
}

export async function withdrawRequestAction(id: number): Promise<ActionResult<ProjectRequest>> {
  const r = await run(async () => toRequest(await apiFetch<J>(`/project-requests/${id}/withdraw`, { method: "POST" })));
  if (r.ok) revalidatePath(`/project-requests/${id}`);
  return r;
}

export async function reviewRequestAction(id: number): Promise<ActionResult<ProjectRequest>> {
  const r = await run(async () => toRequest(await apiFetch<J>(`/project-requests/${id}/review`, { method: "POST" })));
  if (r.ok) revalidatePath(`/project-requests/${id}`);
  return r;
}

export async function approveRequestAction(id: number, body: J): Promise<ActionResult<Project>> {
  const r = await run(async () =>
    toProject(await apiFetch<J>(`/project-requests/${id}/approve`, { method: "POST", body })),
  );
  if (r.ok) {
    revalidatePath(`/project-requests/${id}`);
    revalidatePath("/projects");
    revalidatePath("/admin/requests");
  }
  return r;
}

export async function rejectRequestAction(id: number, reviewNote: string): Promise<ActionResult<ProjectRequest>> {
  const r = await run(async () =>
    toRequest(await apiFetch<J>(`/project-requests/${id}/reject`, { method: "POST", body: { review_note: reviewNote } })),
  );
  if (r.ok) revalidatePath(`/project-requests/${id}`);
  return r;
}

export async function addCommentAction(
  target: "issue" | "project_request",
  id: number,
  body: string,
): Promise<ActionResult<undefined>> {
  const base = target === "issue" ? "/issues" : "/project-requests";
  const r = await run(async () => {
    await apiFetch<J>(`${base}/${id}/comments`, { method: "POST", body: { body } });
    return undefined;
  });
  if (r.ok) revalidatePath(target === "issue" ? `/discussions/${id}` : `/project-requests/${id}`);
  return r;
}

// --- issues ----------------------------------------------------------------------------------------

export async function createIssueAction(body: J): Promise<ActionResult<{ id: number }>> {
  const r = await run(async () => {
    const i = await apiFetch<J>("/issues", { method: "POST", body });
    return { id: Number(i.id) };
  });
  if (r.ok) revalidatePath("/discussions");
  return r;
}

export async function closeIssueAction(id: number, note: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/issues/${id}/close`, { method: "POST", body: { resolution_note: note } });
    return undefined;
  });
  if (r.ok) revalidatePath(`/discussions/${id}`);
  return r;
}

export async function reopenIssueAction(id: number): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/issues/${id}/reopen`, { method: "POST" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/discussions/${id}`);
  return r;
}

// --- projects --------------------------------------------------------------------------------------

export async function updateProjectAction(slug: string, body: J): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/projects/${slug}`, { method: "PATCH", body });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function archiveProjectAction(slug: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/projects/${slug}/archive`, { method: "POST" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function updateQuotaAction(slug: string, body: J): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/projects/${slug}/quota`, { method: "PATCH", body });
    return undefined;
  });
  if (r.ok) revalidatePath("/admin/quotas");
  return r;
}

export async function addMemberAction(slug: string, usernameOrEmail: string, role: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/projects/${slug}/members`, { method: "POST", body: { username_or_email: usernameOrEmail, role } });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function updateMemberAction(slug: string, userId: number, role: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/projects/${slug}/members/${userId}`, { method: "PATCH", body: { role } });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function removeMemberAction(slug: string, userId: number): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/projects/${slug}/members/${userId}`, { method: "DELETE" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

// --- data sources / uploads ------------------------------------------------------------------------

export async function createDataSourceAction(slug: string, body: J): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    const ds = await apiFetch<J>(`/projects/${slug}/data-sources`, { method: "POST", body });
    await apiFetch<J>(`/projects/${slug}/data-sources/${ds.id}/check`, { method: "POST" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}/data-sources`);
  return r;
}

export async function checkDataSourceAction(slug: string, id: number): Promise<ActionResult<boolean>> {
  const r = await run(async () => {
    const ds = await apiFetch<J>(`/projects/${slug}/data-sources/${id}/check`, { method: "POST" });
    return Boolean(ds.last_check_ok);
  });
  if (r.ok) revalidatePath(`/projects/${slug}/data-sources`);
  return r;
}

export async function deleteDataSourceAction(slug: string, id: number): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/projects/${slug}/data-sources/${id}`, { method: "DELETE" });
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
  return run(() =>
    apiFetch<PreviewPayload>(`/projects/${slug}/uploads/${uploadId}/preview`, {
      method: "POST",
      body: { steps, sample, spec },
    }),
  );
}

export async function uploadStatusAction(slug: string, raw: J): Promise<Upload> {
  void slug;
  return toUpload(raw);
}

// --- jobs ------------------------------------------------------------------------------------------

export async function createJobAction(slug: string, body: J): Promise<ActionResult<Job>> {
  const r = await run(async () => toJob(await apiFetch<J>(`/projects/${slug}/jobs`, { method: "POST", body })));
  if (r.ok) {
    revalidatePath(`/projects/${slug}/jobs`);
    revalidatePath("/");
  }
  return r;
}

export async function cancelJobAction(id: number, slug: string): Promise<ActionResult<Job>> {
  const r = await run(async () => toJob(await apiFetch<J>(`/jobs/${id}/cancel`, { method: "POST" })));
  if (r.ok) {
    revalidatePath(`/projects/${slug}/jobs/${id}`);
    revalidatePath(`/projects/${slug}/jobs`);
  }
  return r;
}

export async function setDefaultArtifactAction(id: number, slug: string, value = true): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/artifacts/${id}`, { method: "PATCH", body: { is_default: value } });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

export async function deleteArtifactAction(id: number, slug: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/artifacts/${id}`, { method: "DELETE" });
    return undefined;
  });
  if (r.ok) revalidatePath(`/projects/${slug}`, "layout");
  return r;
}

// --- admin -----------------------------------------------------------------------------------------

export async function updateUserAction(id: number, body: J): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    toUser(await apiFetch<J>(`/users/${id}`, { method: "PATCH", body }));
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
}): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>("/admin/settings/resource-pool", {
      method: "PUT",
      body: {
        gpu_indices: pool.gpuIndices,
        cpu_cores: pool.cpuCores,
        memory_mb: pool.memoryMb,
        max_running_jobs: pool.maxRunningJobs,
        allow_backfill: pool.allowBackfill,
      },
    });
    return undefined;
  });
  if (r.ok) revalidatePath("/admin", "layout");
  return r;
}

export async function moveQueueAction(jobId: number, position: "top" | "up" | "down" | "bottom"): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J[]>(`/admin/queue/${jobId}/move`, { method: "POST", body: { position } });
    return undefined;
  });
  if (r.ok) revalidatePath("/admin/queue");
  return r;
}

export async function stopJobAction(jobId: number, reason: string): Promise<ActionResult<undefined>> {
  const r = await run(async () => {
    await apiFetch<J>(`/admin/jobs/${jobId}/stop`, { method: "POST", body: { reason } });
    return undefined;
  });
  if (r.ok) revalidatePath("/admin/queue");
  return r;
}
