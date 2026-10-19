// System roles and permissions as reported by the backend (/me → permissions). Client-safe: no server imports.
// The backend decides on every request; these helpers only hide UI (CLAUDE.md rule 3).
import type { Project, ProjectRole, SystemRole, User } from "@/types/domain";

export type Permission =
  | "admin.view"
  | "audit.view"
  | "usage.view"
  | "users.view"
  | "requests.review"
  | "jobs.control"
  | "issues.moderate"
  | "pool.manage"
  | "quota.manage"
  | "projects.delete"
  | "users.manage"
  | "model_zoo.manage"
  | "gpu.reset";

export const SYSTEM_ROLES: readonly SystemRole[] = ["superadmin", "admin", "user"];
/** Roles the UI may assign. superadmin is exactly one account fixed by the backend's SUPERADMIN_USERNAME: never granted here. */
export const ASSIGNABLE_ROLES: readonly SystemRole[] = ["admin", "user"];

export function isAdminRole(role: string | undefined | null): boolean {
  return role === "admin" || role === "superadmin";
}

export function can(user: Pick<User, "permissions"> | null | undefined, perm: Permission): boolean {
  return user?.permissions?.includes(perm) ?? false;
}

// --- project roles (mirror of backend/app/core/deps.py `project_access(min_role)`) -----------------------

const PROJECT_ROLE_RANK: Record<ProjectRole, number> = { viewer: 0, member: 1, maintainer: 2, owner: 3 };

/**
 * What a project role may do; the backend's minimum role per endpoint:
 * - `settings` (owner):       rename / describe / archive the project
 * - `manage`   (maintainer):  add / change / remove members, delete artifacts
 * - `edit`     (member):      data sources (create / check / delete), uploads, set the default model
 * - `run`      (member):      create jobs and cancel their own (maintainer+ may cancel anyone's)
 * - `view`     (viewer):      read-only
 */
export type ProjectAction = "view" | "run" | "edit" | "manage" | "settings";

const MIN_ROLE: Record<ProjectAction, ProjectRole> = {
  view: "viewer",
  run: "member",
  edit: "member",
  manage: "maintainer",
  settings: "owner",
};

/** The user's effective role in a project; system admins act as owner everywhere (backend `project_access`). */
export function projectRole(
  project: Pick<Project, "members"> | null | undefined,
  user: Pick<User, "id" | "role"> | null | undefined,
): ProjectRole | null {
  if (!user) return null;
  if (isAdminRole(user.role)) return "owner";
  return project?.members.find((m) => m.user.id === user.id)?.role ?? null;
}

export function canProject(role: ProjectRole | null | undefined, action: ProjectAction): boolean {
  if (!role) return false;
  return PROJECT_ROLE_RANK[role] >= PROJECT_ROLE_RANK[MIN_ROLE[action]];
}

/** Members may only cancel the jobs they created; maintainers and above may cancel any job in the project. */
export function canCancelJob(
  role: ProjectRole | null | undefined,
  user: Pick<User, "id"> | null | undefined,
  createdById: number,
): boolean {
  if (!role || !user) return false;
  if (!canProject(role, "run")) return false;
  return canProject(role, "manage") || createdById === user.id;
}

/** Work tabs (data sources, jobs, models, members, settings) exist only once the application was approved. */
export function isApproved(project: Pick<Project, "status">): boolean {
  return project.status === "active" || project.status === "completed" || project.status === "archived";
}
