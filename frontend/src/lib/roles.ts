// System roles and permissions as reported by the backend (/me → permissions). Client-safe: no server imports.
// The backend decides on every request; these helpers only hide UI (CLAUDE.md rule 3).
import type { SystemRole, User } from "@/types/domain";

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

export function isAdminRole(role: string | undefined | null): boolean {
  return role === "admin" || role === "superadmin";
}

export function can(user: Pick<User, "permissions"> | null | undefined, perm: Permission): boolean {
  return user?.permissions?.includes(perm) ?? false;
}
