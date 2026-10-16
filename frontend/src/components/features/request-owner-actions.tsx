"use client";

import { Undo2 } from "lucide-react";
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
import { withdrawRequestAction } from "@/lib/actions";

export function WithdrawRequestButton({ id }: { id: number }) {
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  return (
    <>
      <Button variant="outline" disabled={pending} onClick={() => setOpen(true)}>
        <Undo2 />
        撤回
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>撤回申請 #{id}？</AlertDialogTitle>
            <AlertDialogDescription>撤回後審核會停止；之後可以修改內容重新提出。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={pending}
              onClick={() =>
                startTransition(async () => {
                  const r = await withdrawRequestAction(id);
                  if (!r.ok) toast.error(r.error);
                  else toast.success("已撤回");
                  setOpen(false);
                })
              }
            >
              撤回申請
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
