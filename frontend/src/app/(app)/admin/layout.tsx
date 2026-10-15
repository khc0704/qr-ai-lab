import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { getCurrentUser, isAdmin } from "@/lib/session";

// Backend enforces authorization; this only hides the UI from non-admins (CLAUDE.md rule 3).
export default async function AdminLayout({ children }: { children: ReactNode }) {
  const user = await getCurrentUser();
  if (!isAdmin(user)) notFound();
  return <>{children}</>;
}
