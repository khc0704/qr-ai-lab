"use client";

import { Bell } from "lucide-react";
import { Suspense } from "react";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { CommandMenu, type CommandEntry } from "@/components/layout/command-menu";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function Topbar({
  projects,
  isAdmin,
  unread = 0,
}: {
  projects: CommandEntry[];
  isAdmin: boolean;
  unread?: number;
}) {
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-border glass px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
      <Suspense fallback={<Skeleton className="h-4 w-40" />}>
        <Breadcrumbs />
      </Suspense>
      <div className="flex items-center gap-1">
        <CommandMenu projects={projects} isAdmin={isAdmin} />
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="通知" className="relative">
              <Bell />
              {unread > 0 ? <span className="absolute top-2 right-2 size-2 rounded-full bg-primary" /> : null}
            </Button>
          </TooltipTrigger>
          <TooltipContent>通知</TooltipContent>
        </Tooltip>
        <ThemeToggle />
      </div>
    </header>
  );
}
