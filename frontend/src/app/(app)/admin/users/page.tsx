import { Info } from "lucide-react";
import { Suspense } from "react";
import { pageFromParam, pageHref, Pagination } from "@/components/features/pagination";
import { TableSkeleton } from "@/components/features/skeletons";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { PageHeader } from "@/components/layout/page-header";
import { systemRoleHint, systemRoleLabel } from "@/i18n/zh-TW";
import { listUsersPage } from "@/lib/api";
import { SYSTEM_ROLES } from "@/lib/roles";
import { can, getCurrentUser } from "@/lib/session";
import { UsersTable } from "./users-table";

const PAGE_SIZE = 50;

async function Users({ searchParams }: { searchParams: Promise<{ page?: string | string[] }> }) {
  const sp = await searchParams;
  const page = pageFromParam(sp.page);
  const [users, me] = await Promise.all([listUsersPage({ page, pageSize: PAGE_SIZE }), getCurrentUser()]);
  const canManage = can(me, "users.manage");
  return (
    <>
      <PageHeader
        title="使用者"
        description={
          me.authMode === "keycloak"
            ? "帳號由 Keycloak 首次登入時自動建立；這裡調整系統角色與啟用狀態（Keycloak 群組對應的角色會在登入時覆蓋）。"
            : "開發環境為本地帳號；正式環境由 Keycloak 首次登入自動建立。這裡只調整系統角色與啟用狀態。"
        }
        eyebrow={<span className="font-mono normal-case">{users.total} 位使用者</span>}
      />
      <Alert>
        <Info />
        <AlertTitle>三種系統角色</AlertTitle>
        <AlertDescription>
          <ul className="grid gap-1 sm:grid-cols-3">
            {SYSTEM_ROLES.map((r) => (
              <li key={r}>
                <span className="font-medium text-foreground">{systemRoleLabel[r]}</span>
                <span className="ml-1 font-mono text-xs">{r}</span>
                <div className="text-xs">{systemRoleHint[r]}</div>
              </li>
            ))}
          </ul>
          {!canManage ? <p className="mt-2 text-xs">只有 superadmin 可以變更角色或停用帳號；你目前只能檢視。</p> : null}
        </AlertDescription>
      </Alert>
      <UsersTable users={users.items} currentUserId={me.id} canManage={canManage} />
      <Pagination
        page={users.page}
        pageSize={users.pageSize}
        total={users.total}
        href={(p) => pageHref("/admin/users", {}, p)}
      />
    </>
  );
}

export default function AdminUsersPage({ searchParams }: PageProps<"/admin/users">) {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <Users searchParams={searchParams} />
    </Suspense>
  );
}
