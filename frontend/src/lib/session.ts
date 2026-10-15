// Current user from the backend (/me) using the token cookie. Any component calling this reads cookies,
// so it must render inside a <Suspense> boundary (Cache Components) — the (app) layout provides one.
import "server-only";

import { redirect } from "next/navigation";
import { cache } from "react";
import { toUser, type UserRead } from "@/lib/api/mappers";
import { ApiError, apiFetch, getToken } from "@/lib/backend";
import { can as canPerm, isAdminRole, type Permission } from "@/lib/roles";
import type { User } from "@/types/domain";

export const getOptionalUser = cache(async (): Promise<User | null> => {
  const token = await getToken();
  if (!token) return null;
  try {
    return toUser(await apiFetch<UserRead>("/me", { token }));
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return null;
    throw e;
  }
});

export const getCurrentUser = cache(async (): Promise<User> => {
  const user = await getOptionalUser();
  if (!user) redirect("/login?reason=expired");
  return user;
});

/** admin or superadmin: may enter the admin area. Use `can()` for anything finer. */
export function isAdmin(user: User): boolean {
  return isAdminRole(user.role);
}

export function can(user: User, perm: Permission): boolean {
  return canPerm(user, perm);
}
