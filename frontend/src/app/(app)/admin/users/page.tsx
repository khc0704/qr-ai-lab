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
            ? "帳號由 Keycloak 首次登入時自動建立（Keycloak 只提供身分，不決定角色）；系統角色與啟用狀態只在這裡管理。"
            : "開發環境為本地帳號；正式環境由 Keycloak 首次登入自動建立（只提供身分）。系統角色與啟用狀態只在這裡管理。"
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
          <p className="mt-2 text-xs">
            超級管理員只有一位，由環境變數 <span className="font-mono">SUPERADMIN_USERNAME</span>{" "}
            指定，不能在這裡指派、降級或停用；這裡最多只能把其他人指派為管理員。
          </p>
          {!canManage ? <p className="mt-1 text-xs">只有超級管理員可以變更角色或停用帳號；你目前只能檢視。</p> : null}
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
