"use client";

import {
  ClipboardCheck,
  ClipboardList,
  FolderKanban,
  Gauge,
  House,
  ListOrdered,
  MessagesSquare,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  Users,
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
  myRequestReplies?: number;
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
    { href: "/project-requests", label: nav.projectRequests, icon: ClipboardList, badge: counts.myRequestReplies },
    { href: "/projects", label: nav.projects, icon: FolderKanban },
  ];
  const admin: NavItem[] = [
    { href: "/admin", label: nav.adminDashboard, icon: Gauge, exact: true },
    { href: "/admin/requests", label: nav.adminRequests, icon: ClipboardCheck, badge: counts.pendingRequests },
    { href: "/admin/queue", label: nav.adminQueue, icon: ListOrdered, badge: counts.runningJobs },
    { href: "/admin/users", label: nav.adminUsers, icon: Users },
    { href: "/admin/quotas", label: nav.adminQuotas, icon: SlidersHorizontal },
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
        {user.role === "admin" ? <NavGroup label={nav.admin} items={admin} /> : null}
      </SidebarContent>
      <SidebarFooter>
        <UserMenu user={user} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

export const adminIcon = ShieldCheck;
