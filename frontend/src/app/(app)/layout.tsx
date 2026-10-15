import type { ReactNode } from "react";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { SidebarStateSync } from "@/components/layout/sidebar-state-sync";
import { Topbar } from "@/components/layout/topbar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { getQueue, listProjectRequests, listProjects } from "@/lib/api";
import { getCurrentUser, isAdmin } from "@/lib/session";

// The shell is static: no cookies()/headers() here (Cache Components would block every route).
// Session and counts come from mock data today; once they hit the real API, move them into
// <Suspense> islands (see docs/ARCHITECTURE.md §2 and the Next.js caching guide).
export default async function AppLayout({ children }: { children: ReactNode }) {
  const user = await getCurrentUser();
  const admin = isAdmin(user);
  const [projects, queue, pending] = await Promise.all([
    listProjects({ memberOf: admin ? undefined : user.id }),
    getQueue(),
    listProjectRequests({ status: ["submitted", "in_review"] }),
  ]);

  return (
    <TooltipProvider delayDuration={300}>
      <SidebarProvider>
        <SidebarStateSync />
        <AppSidebar
          user={user}
          counts={{ pendingRequests: admin ? pending.length : undefined, runningJobs: queue.running.length }}
        />
        <SidebarInset>
          <Topbar
            isAdmin={admin}
            unread={2}
            projects={projects.map((p) => ({ label: p.name, href: `/projects/${p.slug}`, hint: p.slug }))}
          />
          <main className="flex-1 p-4 md:p-6">
            <div className="mx-auto w-full max-w-7xl space-y-6">{children}</div>
          </main>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
