import { Info } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { PageHeader } from "@/components/layout/page-header";
import { systemRoleHint, systemRoleLabel } from "@/i18n/zh-TW";
import { listUsers } from "@/lib/api";
import { SYSTEM_ROLES } from "@/lib/roles";
import { can, getCurrentUser } from "@/lib/session";
import { UsersTable } from "./users-table";

export default async function AdminUsersPage() {
  const [users, me] = await Promise.all([listUsers(), getCurrentUser()]);
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
      <UsersTable users={users} currentUserId={me.id} canManage={canManage} />
    </>
  );
}
