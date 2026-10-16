"use client";

import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { closeIssueAction, deleteIssueAction, reopenIssueAction } from "@/lib/actions";

export function IssueAdminActions({
  id,
  status,
  canDelete = false,
}: {
  id: number;
  status: "open" | "closed";
  canDelete?: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [note, setNote] = useState("");
  const [pending, startTransition] = useTransition();
  const remove = () =>
    startTransition(async () => {
      const r = await deleteIssueAction(id);
      if (!r.ok) toast.error(r.error);
      else {
        toast.success(`已刪除討論串 #${id}`);
        router.push("/discussions");
      }
    });
  const deleteButton = canDelete ? (
    <>
      <Button
        variant="ghost"
        className="text-destructive hover:text-destructive"
        onClick={() => setConfirmDelete(true)}
      >
        <Trash2 />
        刪除
      </Button>
      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>刪除討論串 #{id}？</AlertDialogTitle>
            <AlertDialogDescription>討論串與所有留言會一併刪除，無法復原；操作會寫入稽核紀錄。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={pending}
              onClick={remove}
            >
              刪除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  ) : null;
  if (status === "closed")
    return (
      <div className="flex items-center gap-2">
        {deleteButton}
        <Button
          variant="outline"
          disabled={pending}
          onClick={() =>
            startTransition(async () => {
              const r = await reopenIssueAction(id);
              if (!r.ok) toast.error(r.error);
              else toast.success("已重開");
            })
          }
        >
          重開
        </Button>
      </div>
    );
  return (
    <div className="flex items-center gap-2">
      {deleteButton}
      <Button variant="outline" onClick={() => setOpen(true)}>
        關閉問題
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>關閉問題 #{id}</DialogTitle>
            <DialogDescription>寫下處理結果，作者會在討論串看到。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="resolution">處理結果</Label>
            <Textarea id="resolution" rows={4} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button
              disabled={!note.trim() || pending}
              onClick={() =>
                startTransition(async () => {
                  const r = await closeIssueAction(id, note.trim());
                  if (!r.ok) toast.error(r.error);
                  else {
                    toast.success("已關閉");
                    setOpen(false);
                  }
                })
              }
            >
              關閉
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
