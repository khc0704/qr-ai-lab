"use client";

import { Suspense } from "react";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { CommandMenu, type CommandEntry } from "@/components/layout/command-menu";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";

export function Topbar({ projects, isAdmin }: { projects: CommandEntry[]; isAdmin: boolean }) {
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-border glass px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
      <Suspense fallback={<Skeleton className="h-4 w-40" />}>
        <Breadcrumbs />
      </Suspense>
      <div className="flex items-center gap-1">
        <CommandMenu projects={projects} isAdmin={isAdmin} />
        <ThemeToggle />
      </div>
    </header>
  );
}
