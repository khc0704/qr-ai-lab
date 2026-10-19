"use client";

import { useTransition } from "react";
import { toast } from "sonner";
import { UserInline } from "@/components/features/member-avatars";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { superadminFixedLabel, systemRoleLabel } from "@/i18n/zh-TW";
import { RelativeTime } from "@/components/features/time";
import { updateUserAction } from "@/lib/actions";
import { ASSIGNABLE_ROLES } from "@/lib/roles";
import type { User } from "@/types/domain";

export function UsersTable({
  users,
  currentUserId,
  canManage,
}: {
  users: User[];
  currentUserId: number;
  canManage: boolean;
}) {
  const [pending, startTransition] = useTransition();
  const update = (u: User, body: { role?: string; is_active?: boolean }, done: string) =>
    startTransition(async () => {
      const r = await updateUserAction(u.id, body);
      if (!r.ok) toast.error(r.error);
      else toast.success(done);
    });
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>使用者</TableHead>
            <TableHead>帳號</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>系統角色</TableHead>
            <TableHead>啟用</TableHead>
            <TableHead className="text-right">最近登入</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.map((u) => (
            <TableRow key={u.id} className={!u.isActive ? "opacity-60" : undefined}>
              <TableCell>
                <UserInline user={u} />
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {u.username}
                {u.authProvider === "keycloak" ? (
                  <span className="ml-1 rounded-sm bg-muted px-1 text-[10px] text-muted-foreground">keycloak</span>
                ) : null}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">{u.email}</TableCell>
              <TableCell>
                {u.role === "superadmin" ? (
                  // exactly one, fixed by the backend's SUPERADMIN_USERNAME: nothing to select here
                  <Badge variant="secondary">{superadminFixedLabel}</Badge>
                ) : (
                  <Select
                    value={u.role}
                    disabled={pending || !canManage || u.id === currentUserId}
                    onValueChange={(v) =>
                      update(u, { role: v }, `${u.displayName} → ${systemRoleLabel[v as User["role"]]}`)
                    }
                  >
                    <SelectTrigger size="sm" className="w-32" aria-label={`${u.displayName} 的系統角色`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ASSIGNABLE_ROLES.map((r) => (
                        <SelectItem key={r} value={r}>
                          {systemRoleLabel[r]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </TableCell>
              <TableCell>
                {u.role === "superadmin" ? (
                  <span className="text-xs text-muted-foreground">固定啟用</span>
                ) : (
                  <Switch
                    checked={u.isActive}
                    disabled={pending || !canManage || u.id === currentUserId}
                    aria-label={`啟用 ${u.displayName}`}
                    onCheckedChange={(c) => update(u, { is_active: c }, `${u.displayName} 已${c ? "啟用" : "停用"}`)}
                  />
                )}
              </TableCell>
              <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                {u.lastLoginAt ? <RelativeTime iso={u.lastLoginAt} /> : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
