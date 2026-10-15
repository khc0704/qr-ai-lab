import { PageHeader } from "@/components/layout/page-header";
import { listUsers } from "@/lib/api";
import { UsersTable } from "./users-table";

export default async function AdminUsersPage() {
  const users = await listUsers();
  return (
    <>
      <PageHeader title="使用者" description="帳號來自 Keycloak，首次登入自動建立。這裡只調整系統角色與啟用狀態。" />
      <UsersTable users={users} />
    </>
  );
}
