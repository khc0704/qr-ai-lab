import { Suspense, type ReactNode } from "react";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { SidebarStateSync } from "@/components/layout/sidebar-state-sync";
import { Topbar } from "@/components/layout/topbar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipProvider } from "@/components/ui/tooltip";
import { getAdminOverview, listProjects } from "@/lib/api";
import { getCurrentUser, isAdmin } from "@/lib/session";

// The shell reads the session cookie, so everything below the Suspense boundary is dynamic (Cache
// Components); the boundary itself is the static part that streams first.
async function Shell({ children }: { children: ReactNode }) {
  const user = await getCurrentUser();
  const admin = isAdmin(user);
  const [projects, overview] = await Promise.all([listProjects(), admin ? getAdminOverview() : null]);
  return (
    <>
      <AppSidebar
        user={user}
        counts={{ pendingRequests: overview?.pendingRequests || undefined, runningJobs: overview?.running || undefined }}
      />
      <SidebarInset className="min-w-0">
        <Topbar
          isAdmin={admin}
          projects={projects.map((p) => ({ label: p.name, href: `/projects/${p.slug}`, hint: p.slug }))}
        />
        <main className="flex-1 p-4 md:p-6">
          <div className="mx-auto w-full max-w-7xl space-y-6">{children}</div>
        </main>
      </SidebarInset>
    </>
  );
}

function ShellSkeleton() {
  return (
    <div className="flex min-h-svh w-full">
      <div className="hidden w-64 border-r border-border p-4 md:block">
        <Skeleton className="h-8 w-40" />
        <div className="mt-6 space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      </div>
      <div className="flex-1 p-6">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="mt-6 h-32 w-full" />
      </div>
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={300}>
      <SidebarProvider>
        <SidebarStateSync />
        <Suspense fallback={<ShellSkeleton />}>
          <Shell>{children}</Shell>
        </Suspense>
      </SidebarProvider>
    </TooltipProvider>
  );
}
