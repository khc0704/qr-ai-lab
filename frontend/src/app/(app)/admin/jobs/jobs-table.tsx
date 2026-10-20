"use client";

// Cross-project job list with multi-select bulk delete (jobs.control). Only finished jobs can be picked; the
// backend reports the ones it refused (model still in use…) and they are shown as warnings.
import { Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { FamilyText, KindChip } from "@/components/features/chips";
import { isFinished, JobDeleteButton } from "@/components/features/job-delete-button";
import { UserInline } from "@/components/features/member-avatars";
import { StatusBadge } from "@/components/features/status-badge";
import { Duration, RelativeTime } from "@/components/features/time";
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
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { deleteJobsAction } from "@/lib/actions";
import { formatMb } from "@/lib/format";
import type { Job } from "@/types/domain";

/** Where a job's page lives: tool jobs under /tools, one-off inference on the project's 推論 page. */
export function jobHref(j: Job): string {
  if (j.kind === "preprocess" || j.kind === "analysis") return `/tools/jobs/${j.id}`;
  if (j.ephemeral) return `/projects/${j.projectSlug}/infer?job=${j.id}`;
  return `/projects/${j.projectSlug}/jobs/${j.id}`;
}

export function JobsTable({ jobs }: { jobs: Job[] }) {
  const router = useRouter();
  const [selected, setSelected] = useState<number[]>([]);
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const deletable = jobs.filter(isFinished).map((j) => j.id);
  const allChecked = deletable.length > 0 && deletable.every((id) => selected.includes(id));
  const toggle = (id: number, on: boolean) =>
    setSelected((s) => (on ? Array.from(new Set([...s, id])) : s.filter((x) => x !== id)));
  const remove = () =>
    startTransition(async () => {
      const r = await deleteJobsAction(selected);
      if (!r.ok) toast.error(r.error);
      else {
        if (r.data.deleted.length) toast.success(`已刪除 ${r.data.deleted.length} 個任務`);
        for (const s of r.data.skipped) toast.warning(`#${s.id} 未刪除：${s.message}`);
        setSelected([]);
        router.refresh();
      }
      setOpen(false);
    });
  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-muted-foreground tabular-nums">
          已選 {selected.length} 個 · 這一頁可刪除 {deletable.length} 個（已結束的任務）
        </span>
        <Button
          variant="destructive"
          size="sm"
          disabled={selected.length === 0 || pending}
          onClick={() => setOpen(true)}
          data-testid="jobs-bulk-delete"
        >
          <Trash2 />
          刪除所選
        </Button>
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <Checkbox
                  checked={allChecked}
                  disabled={deletable.length === 0}
                  aria-label="選取這一頁所有已結束的任務"
                  onCheckedChange={(v) => setSelected(v === true ? deletable : [])}
                />
              </TableHead>
              <TableHead>任務</TableHead>
              <TableHead>專案</TableHead>
              <TableHead>模型</TableHead>
              <TableHead>狀態</TableHead>
              <TableHead>建立者</TableHead>
              <TableHead>資源</TableHead>
              <TableHead className="text-right">時間</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((j) => {
              const finished = isFinished(j);
              return (
                <TableRow key={j.id} data-testid="admin-job-row" data-selected={selected.includes(j.id) || undefined}>
                  <TableCell>
                    <Checkbox
                      checked={selected.includes(j.id)}
                      disabled={!finished}
                      aria-label={`選取任務 #${j.id}`}
                      onCheckedChange={(v) => toggle(j.id, v === true)}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <KindChip kind={j.kind} />
                      <Link href={jobHref(j)} className="font-medium hover:text-brand-ink">
                        {j.name}
                      </Link>
                      <span className="font-mono text-xs text-subtle-foreground">#{j.id}</span>
                      {j.ephemeral ? (
                        <span className="rounded-sm bg-muted px-1.5 text-[11px] text-muted-foreground">一次性</span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    {j.kind === "preprocess" || j.kind === "analysis" ? (
                      <span className="text-xs text-muted-foreground">工具池</span>
                    ) : (
                      <Link href={`/projects/${j.projectSlug}`} className="text-sm hover:underline">
                        {j.projectName}
                      </Link>
                    )}
                  </TableCell>
                  <TableCell>
                    <FamilyText family={j.modelFamily} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={j.status} />
                  </TableCell>
                  <TableCell>
                    <UserInline user={j.createdBy} />
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground tabular-nums">
                    {j.requestedGpu} GPU · {j.requestedCpu} CPU · {formatMb(j.requestedMemoryMb)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                    {j.startedAt ? (
                      <Duration start={j.startedAt} end={j.finishedAt} />
                    ) : (
                      <RelativeTime iso={j.createdAt} />
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <JobDeleteButton job={j} iconOnly />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>刪除 {selected.length} 個任務？</AlertDialogTitle>
            <AlertDialogDescription>
              任務紀錄、log、輸出與這些任務產生的模型 /
              報告會一併刪除，無法復原。還被推論任務引用的模型會跳過並說明原因。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              disabled={pending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={remove}
              data-testid="jobs-bulk-delete-confirm"
            >
              刪除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
