"use client";

import { UserPlus, X } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { UserInline } from "@/components/features/member-avatars";
import { UserPicker } from "@/components/features/user-picker";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { projectRoleLabel } from "@/i18n/zh-TW";
import { RelativeTime } from "@/components/features/time";
import { addMemberByIdAction, removeMemberAction, updateMemberAction } from "@/lib/actions";
import type { ProjectMember, ProjectRole, UserLookup } from "@/types/domain";

export function MembersTable({
  slug,
  members,
  canManage,
}: {
  slug: string;
  members: ProjectMember[];
  canManage: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<UserLookup | null>(null);
  const [role, setRole] = useState<ProjectRole>("member");
  const [pending, startTransition] = useTransition();
  const act = (fn: () => Promise<{ ok: boolean; error?: string }>, done: string) =>
    startTransition(async () => {
      const r = await fn();
      if (!r.ok) toast.error(r.error ?? "失敗");
      else toast.success(done);
    });
  return (
    <>
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs text-muted-foreground tabular-nums">{members.length} 位成員</span>
        {canManage ? (
          <Button size="sm" onClick={() => setOpen(true)}>
            <UserPlus />
            邀請成員
          </Button>
        ) : null}
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>成員</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>角色</TableHead>
              <TableHead className="text-right">加入</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.map((m) => (
              <TableRow key={m.user.id}>
                <TableCell>
                  <UserInline user={m.user} />
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{m.user.email}</TableCell>
                <TableCell>
                  {m.role === "owner" || !canManage ? (
                    <span className="text-sm">{projectRoleLabel[m.role]}</span>
                  ) : (
                    <Select
                      value={m.role}
                      disabled={pending}
                      onValueChange={(v) =>
                        act(
                          () => updateMemberAction(slug, m.user.id, v),
                          `已將 ${m.user.displayName} 改為 ${projectRoleLabel[v as ProjectRole]}`,
                        )
                      }
                    >
                      <SelectTrigger size="sm" className="w-32">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(["maintainer", "member", "viewer"] as ProjectRole[]).map((r) => (
                          <SelectItem key={r} value={r}>
                            {projectRoleLabel[r]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </TableCell>
                <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                  <RelativeTime iso={m.addedAt} />
                </TableCell>
                <TableCell>
                  {m.role !== "owner" && canManage ? (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="移除成員"
                      disabled={pending}
                      onClick={() => act(() => removeMemberAction(slug, m.user.id), `已移除 ${m.user.displayName}`)}
                    >
                      <X />
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setPicked(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>邀請成員</DialogTitle>
            <DialogDescription>搜尋帳號、姓名或 email 後選擇；對方必須已經登入過一次。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="inv-user">成員</Label>
              <UserPicker
                id="inv-user"
                value={picked}
                onChange={setPicked}
                excludeIds={members.map((m) => m.user.id)}
                disabled={pending}
              />
            </div>
            <div className="grid gap-2">
              <Label>角色</Label>
              <Select value={role} onValueChange={(v) => setRole(v as ProjectRole)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(["maintainer", "member", "viewer"] as ProjectRole[]).map((r) => (
                    <SelectItem key={r} value={r}>
                      {projectRoleLabel[r]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button
              disabled={!picked || pending}
              onClick={() =>
                startTransition(async () => {
                  if (!picked) return;
                  const r = await addMemberByIdAction(slug, picked.id, role);
                  if (!r.ok) toast.error(r.error);
                  else {
                    toast.success(`已加入 ${picked.displayName}`);
                    setOpen(false);
                    setPicked(null);
                  }
                })
              }
            >
              加入
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
