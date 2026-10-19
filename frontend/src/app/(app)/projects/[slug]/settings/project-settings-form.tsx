"use client";

import { Archive, Save, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition, type ReactNode } from "react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { archiveProjectAction, deleteProjectAction, updateProjectAction } from "@/lib/actions";

const OWNER_ONLY = "只有專案擁有者（或管理員）可以更改設定";

/** Wraps a disabled control so the tooltip still opens (disabled buttons do not receive pointer events). */
function Gated({ allowed, children }: { allowed: boolean; children: ReactNode }) {
  if (allowed) return <>{children}</>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex rounded-md focus-visible:ring-2 focus-visible:ring-ring/50">
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent>{OWNER_ONLY}</TooltipContent>
    </Tooltip>
  );
}

export function ProjectSettingsForm({
  name,
  description,
  slug,
  archived,
  canEdit = true,
  canDelete = false,
}: {
  name: string;
  description: string;
  slug: string;
  archived: boolean;
  /** Project role `settings` (owner, or a system admin); otherwise the form is read-only. */
  canEdit?: boolean;
  canDelete?: boolean;
}) {
  const router = useRouter();
  const [n, setN] = useState(name);
  const [d, setD] = useState(description);
  const [open, setOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [typed, setTyped] = useState("");
  const [pending, startTransition] = useTransition();
  const remove = () =>
    startTransition(async () => {
      const r = await deleteProjectAction(slug);
      if (!r.ok) toast.error(r.error);
      else {
        toast.success(`專案 ${name} 已刪除`);
        router.push("/projects");
      }
    });
  const dirty = n !== name || d !== description;
  const save = () =>
    startTransition(async () => {
      const r = await updateProjectAction(slug, { name: n, description: d });
      if (!r.ok) toast.error(r.error);
      else toast.success("已儲存專案設定");
    });
  const archive = () =>
    startTransition(async () => {
      const r = await archiveProjectAction(slug);
      if (!r.ok) toast.error(r.error);
      else toast.success("專案已封存");
    });
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>基本</CardTitle>
          <CardDescription>
            slug <span className="font-mono text-foreground">{slug}</span> 建立後不可更改（對應網址與資料夾）。
            {!canEdit ? ` ${OWNER_ONLY}。` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="p-name">名稱</Label>
            <Input id="p-name" value={n} onChange={(e) => setN(e.target.value)} readOnly={!canEdit} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="p-desc">描述</Label>
            <Textarea id="p-desc" rows={4} value={d} onChange={(e) => setD(e.target.value)} readOnly={!canEdit} />
          </div>
          <div className="flex justify-end">
            <Gated allowed={canEdit}>
              <Button disabled={!canEdit || !dirty || pending} onClick={save}>
                <Save />
                儲存
              </Button>
            </Gated>
          </div>
        </CardContent>
      </Card>
      <Card className="border-destructive/30">
        <CardHeader>
          <CardTitle>封存專案</CardTitle>
          <CardDescription>封存後不能建立任務，產物與 log 保留可讀；管理員可解除封存。</CardDescription>
        </CardHeader>
        <CardContent>
          <Gated allowed={canEdit}>
            <Button variant="destructive" disabled={!canEdit || archived} onClick={() => setOpen(true)}>
              <Archive />
              {archived ? "已封存" : "封存專案"}
            </Button>
          </Gated>
        </CardContent>
      </Card>
      {canDelete ? (
        <Card className="border-destructive/50">
          <CardHeader>
            <CardTitle>刪除專案</CardTitle>
            <CardDescription>
              superadmin
              專用。刪除任務、產物、log、資料來源設定與成員，資料夾一併移除，無法復原；還有未結束的任務時會拒絕。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="destructive" onClick={() => setConfirmDelete(true)} data-testid="delete-project">
              <Trash2 />
              刪除專案
            </Button>
          </CardContent>
        </Card>
      ) : null}
      <AlertDialog open={confirmDelete} onOpenChange={(o) => (setConfirmDelete(o), setTyped(""))}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>刪除 {name}？</AlertDialogTitle>
            <AlertDialogDescription>
              請輸入專案 slug <span className="font-mono text-foreground">{slug}</span> 確認。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <Input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={slug}
            aria-label="輸入 slug 確認"
          />
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={pending || typed !== slug}
              onClick={remove}
            >
              永久刪除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>封存 {name}？</AlertDialogTitle>
            <AlertDialogDescription>執行中的任務會先被取消。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={pending}
              onClick={archive}
            >
              封存
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
