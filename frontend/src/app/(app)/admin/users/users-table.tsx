"use client";

import { toast } from "sonner";
import { UserInline } from "@/components/features/member-avatars";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { systemRoleLabel } from "@/i18n/zh-TW";
import { formatRelative } from "@/lib/format";
import type { User } from "@/types/domain";

export function UsersTable({ users }: { users: User[] }) {
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
              <TableCell className="font-mono text-xs text-muted-foreground">{u.username}</TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">{u.email}</TableCell>
              <TableCell>
                <Select
                  defaultValue={u.role}
                  onValueChange={(v) => toast.success(`${u.displayName} → ${systemRoleLabel[v as User["role"]]}`)}
                >
                  <SelectTrigger size="sm" className="w-28">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="admin">{systemRoleLabel.admin}</SelectItem>
                    <SelectItem value="user">{systemRoleLabel.user}</SelectItem>
                  </SelectContent>
                </Select>
              </TableCell>
              <TableCell>
                <Switch
                  defaultChecked={u.isActive}
                  aria-label={`啟用 ${u.displayName}`}
                  onCheckedChange={(c) => toast.success(`${u.displayName} 已${c ? "啟用" : "停用"}`)}
                />
              </TableCell>
              <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                {u.lastLoginAt ? formatRelative(u.lastLoginAt) : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
