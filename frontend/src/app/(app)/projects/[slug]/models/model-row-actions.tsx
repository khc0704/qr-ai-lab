"use client";

import { Download, Star, Trash2 } from "lucide-react";
import { useState, useTransition } from "react";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { deleteArtifactAction, setDefaultArtifactAction } from "@/lib/actions";

export function ModelRowActions({
  id,
  name,
  isDefault,
  slug,
  canSetDefault = true,
  canDelete = true,
}: {
  id: number;
  name: string;
  isDefault: boolean;
  slug: string;
  /** Project role `edit` (member+). */
  canSetDefault?: boolean;
  /** Project role `manage` (maintainer+): the backend requires maintainer to delete artifacts. */
  canDelete?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  return (
    <div className="flex justify-end gap-1">
      {!isDefault && canSetDefault ? (
        <Button
          variant="ghost"
          size="sm"
          disabled={pending}
          onClick={() =>
            startTransition(async () => {
              const r = await setDefaultArtifactAction(id, slug);
              if (!r.ok) toast.error(r.error);
              else toast.success(`已將 ${name} 設為預設模型`);
            })
          }
        >
          <Star />
          設為預設
        </Button>
      ) : null}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label="下載" asChild>
            <a href={`/api/download/artifacts/${id}/download`} download>
              <Download />
            </a>
          </Button>
        </TooltipTrigger>
        <TooltipContent>下載（目錄會打包成 zip）</TooltipContent>
      </Tooltip>
      {canDelete ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="刪除" onClick={() => setOpen(true)}>
              <Trash2 />
            </Button>
          </TooltipTrigger>
          <TooltipContent>刪除</TooltipContent>
        </Tooltip>
      ) : null}
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>刪除模型 {name}？</AlertDialogTitle>
            <AlertDialogDescription>
              檔案會從專案資料夾移除並釋放配額；引用它的推論紀錄需先刪除。此操作無法復原。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={pending}
              onClick={() =>
                startTransition(async () => {
                  const r = await deleteArtifactAction(id, slug);
                  if (!r.ok) toast.error(r.error);
                  else toast.success(`已刪除模型 ${name}`);
                })
              }
            >
              刪除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
