"use client";

import { Pencil, Undo2 } from "lucide-react";
import Link from "next/link";
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
import { withdrawApplicationAction } from "@/lib/actions";
import type { Project } from "@/types/domain";

/** The applicant's own controls: edit & resubmit (pending / rejected) and withdraw (deletes the pending project). */
export function ApplicationOwnerActions({ project }: { project: Project }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const editable = project.status === "pending" || project.status === "rejected";
  const withdrawable = editable || project.status === "in_review";
  if (!editable && !withdrawable) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {editable ? (
        <Button variant={project.status === "rejected" ? "default" : "outline"} asChild>
          <Link href={`/projects/${project.slug}/application/edit`}>
            <Pencil />
            {project.status === "rejected" ? "修改並重送" : "修改申請"}
          </Link>
        </Button>
      ) : null}
      {withdrawable ? (
        <Button variant="outline" disabled={pending} onClick={() => setOpen(true)}>
          <Undo2 />
          撤回
        </Button>
      ) : null}
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>撤回「{project.name}」的申請？</AlertDialogTitle>
            <AlertDialogDescription>撤回會刪除這個申請中的專案；之後可以重新提出。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={pending}
              onClick={() =>
                startTransition(async () => {
                  const r = await withdrawApplicationAction(project.slug);
                  if (!r.ok) toast.error(r.error);
                  else {
                    toast.success("已撤回申請");
                    router.push("/projects");
                  }
                  setOpen(false);
                })
              }
            >
              撤回申請
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
