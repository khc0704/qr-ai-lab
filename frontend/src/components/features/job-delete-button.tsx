"use client";

// Delete a finished job: its record, log, output folder and the artifacts it produced. Rendered for the
// creator, for maintainers and for admins (the page decides with `canDeleteJob`); the backend decides for real
// on DELETE /jobs/{id} and refuses active jobs and models another inference run still uses.
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
import { jobCopy } from "@/i18n/zh-TW";
import { deleteJobAction } from "@/lib/actions";
import type { Job } from "@/types/domain";

export function isFinished(job: Pick<Job, "status">): boolean {
  return job.status === "succeeded" || job.status === "failed" || job.status === "cancelled";
}

export function JobDeleteButton({
  job,
  afterHref,
  iconOnly = false,
}: {
  job: Pick<Job, "id" | "name" | "status" | "projectSlug" | "kind">;
  /** Where to go once the job is gone (a list page); omitted = stay and refresh. */
  afterHref?: string;
  iconOnly?: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  if (!isFinished(job)) return null;
  const remove = () =>
    startTransition(async () => {
      const r = await deleteJobAction(job.id, job.projectSlug);
      if (!r.ok) toast.error(r.error);
      else {
        toast.success(`已刪除任務 #${job.id}`);
        if (afterHref) router.push(afterHref);
        else router.refresh();
      }
      setOpen(false);
    });
  return (
    <>
      {iconOnly ? (
        <Button
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground hover:text-destructive"
          aria-label={`刪除任務 #${job.id}`}
          title="刪除任務"
          onClick={() => setOpen(true)}
          data-testid="job-delete"
        >
          <Trash2 />
        </Button>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive hover:text-destructive"
          onClick={() => setOpen(true)}
          data-testid="job-delete"
        >
          <Trash2 />
          刪除
        </Button>
      )}
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              刪除任務 #{job.id} {job.name}？
            </AlertDialogTitle>
            <AlertDialogDescription>
              {job.kind === "train" ? jobCopy.deleteTrainDescription : jobCopy.deleteDescription}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              disabled={pending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={remove}
              data-testid="job-delete-confirm"
            >
              刪除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
