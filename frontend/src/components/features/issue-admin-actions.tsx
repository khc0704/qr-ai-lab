"use client";

import { useState, useTransition } from "react";
import { toast } from "sonner";
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
import { closeIssueAction, reopenIssueAction } from "@/lib/actions";

export function IssueAdminActions({ id, status }: { id: number; status: "open" | "closed" }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [pending, startTransition] = useTransition();
  if (status === "closed")
    return (
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
    );
  return (
    <>
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
    </>
  );
}
