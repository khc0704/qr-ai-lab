// Mock session until Auth.js + Keycloak are wired (see docs/ARCHITECTURE.md §2).
// When this reads cookies(), every caller must sit inside a <Suspense> boundary (Cache Components).
import "server-only";

import { users } from "@/lib/mock-data";
import type { User } from "@/types/domain";

export async function getCurrentUser(): Promise<User> {
  return users[0];
}

export function isAdmin(user: User): boolean {
  return user.role === "admin";
}
