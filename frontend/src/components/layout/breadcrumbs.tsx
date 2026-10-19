"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment } from "react";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { nav, routeLabel } from "@/i18n/zh-TW";
import { cn } from "@/lib/utils";

/** Intermediate segments without a page of their own link to the page that lists them instead. */
const CRUMB_HREF: Record<string, string> = {
  "/tools/jobs": "/tools",
};

/** `path` is the URL prefix this crumb stands for (unique, used as the key); `href` is where clicking it goes. */
function crumbsFor(pathname: string): { path: string; href: string; label: string }[] {
  const parts = pathname.split("/").filter(Boolean);
  const crumbs: { path: string; href: string; label: string }[] = [{ path: "/", href: "/", label: nav.home }];
  let acc = "";
  for (const part of parts) {
    acc += `/${part}`;
    const label = routeLabel[part] ?? (/^\d+$/.test(part) ? `#${part}` : part);
    crumbs.push({ path: acc, href: CRUMB_HREF[acc] ?? acc, label });
  }
  return crumbs;
}

/** Reads the URL; the Topbar wraps it in <Suspense> so dynamic routes keep a static shell. */
export function Breadcrumbs() {
  const crumbs = crumbsFor(usePathname());
  return (
    <Breadcrumb className="min-w-0 flex-1">
      <BreadcrumbList className="flex-nowrap">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          // On narrow screens keep only the current page and its parent.
          const hidden = i < crumbs.length - 2 ? "hidden md:inline-flex" : undefined;
          return (
            <Fragment key={c.path}>
              {i > 0 ? <BreadcrumbSeparator className={cn(hidden && "hidden md:block")} /> : null}
              <BreadcrumbItem className={cn("whitespace-nowrap", hidden)}>
                {last ? (
                  <BreadcrumbPage className="truncate">{c.label}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink asChild>
                    <Link href={c.href}>{c.label}</Link>
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
            </Fragment>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
