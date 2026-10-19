"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";
import { cn } from "@/lib/utils";
import type { ProjectStatus } from "@/types/domain";

const WORK_TABS = [
  { seg: "", label: "總覽" },
  { seg: "data-sources", label: "資料來源" },
  { seg: "jobs", label: "任務" },
  { seg: "models", label: "模型" },
  { seg: "members", label: "成員" },
  { seg: "settings", label: "設定" },
];
const APPLICATION_TAB = { seg: "application", label: "申請" };

/** Before approval only the 申請 tab exists; afterwards it stays as the record, after the work tabs. */
export function tabsFor(status: ProjectStatus, hasApplication: boolean) {
  const approved = status === "active" || status === "completed" || status === "archived";
  if (!approved) return [APPLICATION_TAB];
  return hasApplication ? [...WORK_TABS, APPLICATION_TAB] : WORK_TABS;
}

function TabsView({
  slug,
  pathname,
  tabs,
}: {
  slug: string;
  pathname: string | null;
  tabs: { seg: string; label: string }[];
}) {
  const base = `/projects/${slug}`;
  return (
    <nav className="-mb-px flex gap-1 overflow-x-auto border-b border-border" aria-label="專案分頁">
      {tabs.map((t) => {
        const href = t.seg ? `${base}/${t.seg}` : base;
        const active =
          pathname !== null && (t.seg ? pathname === href || pathname.startsWith(`${href}/`) : pathname === base);
        return (
          <Link
            key={t.seg}
            href={href}
            className={cn(
              "border-b-2 px-3 py-2 text-sm whitespace-nowrap transition-colors",
              active
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}

function TabsLive({ slug, tabs }: { slug: string; tabs: { seg: string; label: string }[] }) {
  return <TabsView slug={slug} pathname={usePathname()} tabs={tabs} />;
}

export function ProjectTabs({
  slug,
  status,
  hasApplication,
}: {
  slug: string;
  status: ProjectStatus;
  hasApplication: boolean;
}) {
  const tabs = tabsFor(status, hasApplication);
  return (
    <Suspense fallback={<TabsView slug={slug} pathname={null} tabs={tabs} />}>
      <TabsLive slug={slug} tabs={tabs} />
    </Suspense>
  );
}
