"use client";

import { RefreshCw, Trash2 } from "lucide-react";
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
import { checkDataSourceAction, deleteDataSourceAction } from "@/lib/actions";

export function SourceRowActions({
  slug,
  id,
  name,
  canEdit = true,
}: {
  slug: string;
  id: number;
  name: string;
  /** Project role `edit` (member+): check and delete; viewers see nothing here. */
  canEdit?: boolean;
}) {
  const [pending, startTransition] = useTransition();
  const [confirmOpen, setConfirmOpen] = useState(false);
  if (!canEdit) return null;
  return (
    <div className="flex justify-end gap-1">
      <Button
        variant="ghost"
        size="sm"
        disabled={pending}
        onClick={() =>
          startTransition(async () => {
            const r = await checkDataSourceAction(slug, id);
            if (!r.ok) toast.error(r.error);
            else if (r.data) toast.success(`${name} 連線正常`);
            else toast.warning(`${name} 連線失敗，請看最近檢查訊息`);
          })
        }
      >
        <RefreshCw className={pending ? "animate-spin" : undefined} />
        檢查連線
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="刪除資料來源"
        disabled={pending}
        onClick={() => setConfirmOpen(true)}
      >
        <Trash2 />
      </Button>
      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>刪除資料來源「{name}」？</AlertDialogTitle>
            <AlertDialogDescription>只移除這裡記錄的連線資訊與憑證，不影響你的資料。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={pending}
              onClick={() =>
                startTransition(async () => {
                  const r = await deleteDataSourceAction(slug, id);
                  if (!r.ok) toast.error(r.error);
                  else toast.success("已刪除");
                  setConfirmOpen(false);
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
