"use client";

import {
  ChartLine,
  ChartScatter,
  ClipboardCheck,
  FolderKanban,
  Gauge,
  House,
  ListChecks,
  ListOrdered,
  MessagesSquare,
  PackageSearch,
  ScrollText,
  ShieldCheck,
  Users,
  Wand2,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";
import { BrandMark } from "@/components/layout/brand-mark";
import { UserMenu } from "@/components/layout/user-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { common, nav } from "@/i18n/zh-TW";
import { isAdminRole } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { User } from "@/types/domain";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: number;
  exact?: boolean;
}

export interface SidebarCounts {
  pendingRequests?: number;
  runningJobs?: number;
}

const activeClasses =
  "relative data-[active=true]:before:absolute data-[active=true]:before:top-1/2 data-[active=true]:before:left-0 data-[active=true]:before:h-5 data-[active=true]:before:w-0.5 data-[active=true]:before:-translate-y-1/2 data-[active=true]:before:rounded-full data-[active=true]:before:bg-primary data-[active=true]:[&>svg]:text-brand-ink";

function isActive(item: NavItem, pathname: string | null) {
  if (pathname === null) return false;
  return item.exact ? pathname === item.href : pathname === item.href || pathname.startsWith(`${item.href}/`);
}

/** Reads the URL; must sit under <Suspense> so dynamic routes can still prerender a static shell. */
function NavGroupLive(props: { label: string; items: NavItem[] }) {
  const pathname = usePathname();
  return <NavGroupView {...props} pathname={pathname} />;
}

function NavGroup(props: { label: string; items: NavItem[] }) {
  return (
    <Suspense fallback={<NavGroupView {...props} pathname={null} />}>
      <NavGroupLive {...props} />
    </Suspense>
  );
}

function NavGroupView({ label, items, pathname }: { label: string; items: NavItem[]; pathname: string | null }) {
  return (
    <SidebarGroup>
      <SidebarGroupLabel className="text-label">{label}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => {
            const active = isActive(item, pathname);
            return (
              <SidebarMenuItem key={item.href}>
                <SidebarMenuButton asChild isActive={active} tooltip={item.label} className={cn(activeClasses)}>
                  <Link href={item.href}>
                    <item.icon />
                    <span>{item.label}</span>
                  </Link>
                </SidebarMenuButton>
                {item.badge ? (
                  <SidebarMenuBadge className="font-mono text-xs tabular-nums">{item.badge}</SidebarMenuBadge>
                ) : null}
              </SidebarMenuItem>
            );
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

export function AppSidebar({ user, counts = {} }: { user: User; counts?: SidebarCounts }) {
  const main: NavItem[] = [
    { href: "/", label: nav.home, icon: House, exact: true },
    { href: "/discussions", label: nav.discussions, icon: MessagesSquare },
    { href: "/projects", label: nav.projects, icon: FolderKanban },
    { href: "/tools/preprocess", label: nav.tools, icon: Wand2 },
    { href: "/tools/analyze", label: nav.analyze, icon: ChartScatter },
  ];
  const admin: NavItem[] = [
    { href: "/admin", label: nav.adminDashboard, icon: Gauge, exact: true },
    {
      href: "/projects?status=pending",
      label: nav.pendingProjects,
      icon: ClipboardCheck,
      badge: counts.pendingRequests,
      exact: true,
    },
    { href: "/admin/queue", label: nav.adminQueue, icon: ListOrdered, badge: counts.runningJobs },
    { href: "/admin/jobs", label: nav.adminJobs, icon: ListChecks },
    { href: "/admin/users", label: nav.adminUsers, icon: Users },
    { href: "/admin/model-zoo", label: nav.adminModelZoo, icon: PackageSearch },
    { href: "/admin/usage", label: nav.adminUsage, icon: ChartLine },
    { href: "/admin/audit", label: nav.adminAudit, icon: ScrollText },
  ];

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild size="lg" className="hover:bg-transparent">
              <Link href="/">
                <BrandMark />
                <div className="grid flex-1 leading-tight">
                  <span className="truncate text-sm font-semibold tracking-tight">{common.appName}</span>
                  <span className="text-label tracking-normal normal-case">AI 模型實驗室</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavGroup label="主選單" items={main} />
        {isAdminRole(user.role) ? <NavGroup label={nav.admin} items={admin} /> : null}
      </SidebarContent>
      <SidebarFooter>
        <UserMenu user={user} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

export const adminIcon = ShieldCheck;
