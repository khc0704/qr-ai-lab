import { PageHeader } from "@/components/layout/page-header";
import { listUsers } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";
import { UsersTable } from "./users-table";

export default async function AdminUsersPage() {
  const [users, me] = await Promise.all([listUsers(), getCurrentUser()]);
  return (
    <>
      <PageHeader title="使用者" description="過渡期為本地帳號（之後由 Keycloak 首次登入自動建立）。這裡只調整系統角色與啟用狀態。" />
      <UsersTable users={users} currentUserId={me.id} />
    </>
  );
}
