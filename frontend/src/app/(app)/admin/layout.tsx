import { notFound } from "next/navigation";
import { Suspense, type ReactNode } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { getCurrentUser, isAdmin } from "@/lib/session";

// Backend enforces authorization; this only hides the UI from non-admins (CLAUDE.md rule 3).
async function Guard({ children }: { children: ReactNode }) {
  const user = await getCurrentUser();
  if (!isAdmin(user)) notFound();
  return <>{children}</>;
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Guard>{children}</Guard>
    </Suspense>
  );
}
