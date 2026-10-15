"use client";

import { UserPlus, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { UserInline } from "@/components/features/member-avatars";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { projectRoleLabel } from "@/i18n/zh-TW";
import { formatRelative } from "@/lib/format";
import type { ProjectMember, ProjectRole } from "@/types/domain";

export function MembersTable({ members }: { members: ProjectMember[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs text-muted-foreground tabular-nums">{members.length} 位成員</span>
        <Button size="sm" onClick={() => setOpen(true)}>
          <UserPlus />
          邀請成員
        </Button>
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
                  {m.role === "owner" ? (
                    <span className="text-sm">{projectRoleLabel.owner}</span>
                  ) : (
                    <Select
                      defaultValue={m.role}
                      onValueChange={(v) =>
                        toast.success(`已將 ${m.user.displayName} 改為 ${projectRoleLabel[v as ProjectRole]}`)
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
                  {formatRelative(m.addedAt)}
                </TableCell>
                <TableCell>
                  {m.role !== "owner" ? (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="移除成員"
                      onClick={() => toast.success(`已移除 ${m.user.displayName}`)}
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
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>邀請成員</DialogTitle>
            <DialogDescription>成員必須先用公司帳號登入過一次才找得到。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="inv-email">Email</Label>
              <Input id="inv-email" className="font-mono" placeholder="name@example.com" />
            </div>
            <div className="grid gap-2">
              <Label>角色</Label>
              <Select defaultValue="member">
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
              onClick={() => {
                setOpen(false);
                toast.success("已送出邀請");
              }}
            >
              邀請
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
