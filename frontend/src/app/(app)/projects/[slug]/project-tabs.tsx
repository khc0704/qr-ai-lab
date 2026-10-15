"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";
import { cn } from "@/lib/utils";

const tabs = [
  { seg: "", label: "總覽" },
  { seg: "data-sources", label: "資料來源" },
  { seg: "jobs", label: "任務" },
  { seg: "models", label: "模型" },
  { seg: "members", label: "成員" },
  { seg: "settings", label: "設定" },
];

function TabsView({ slug, pathname }: { slug: string; pathname: string | null }) {
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

function TabsLive({ slug }: { slug: string }) {
  return <TabsView slug={slug} pathname={usePathname()} />;
}

export function ProjectTabs({ slug }: { slug: string }) {
  return (
    <Suspense fallback={<TabsView slug={slug} pathname={null} />}>
      <TabsLive slug={slug} />
    </Suspense>
  );
}
