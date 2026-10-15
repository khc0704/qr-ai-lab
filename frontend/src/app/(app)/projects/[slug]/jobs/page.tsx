import { Brain, Plus, Sparkles } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { EmptyState } from "@/components/features/empty-state";
import { FamilyText, InputKindChip, KindChip } from "@/components/features/chips";
import { UserInline } from "@/components/features/member-avatars";
import { TableSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { jobModeLabel } from "@/i18n/zh-TW";
import { getProject, getQueue, listJobs } from "@/lib/api";
import { formatDuration, formatMb, formatRelative } from "@/lib/format";

async function Jobs({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const project = await getProject(slug);
  if (!project) notFound();
  const [jobs, queue] = await Promise.all([listJobs({ projectId: project.id }), getQueue()]);
  const pos = (id: number) => queue.queued.findIndex((j) => j.id === id) + 1;
  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-muted-foreground tabular-nums">
          {jobs.length} 個任務 · 同時上限 {project.maxConcurrentJobs}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link href={`/projects/${project.slug}/jobs/new?kind=inference`}>
              <Sparkles />
              新建推論
            </Link>
          </Button>
          <Button size="sm" asChild>
            <Link href={`/projects/${project.slug}/jobs/new`}>
              <Plus />
              新建訓練
            </Link>
          </Button>
        </div>
      </div>
      {jobs.length === 0 ? (
        <EmptyState
          icon={Brain}
          title="還沒有任務"
          description="先新建一個訓練任務；不確定選什麼模型就用自動模式。"
          dots
          action={
            <Button asChild>
              <Link href={`/projects/${project.slug}/jobs/new`}>新建訓練</Link>
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>任務</TableHead>
                <TableHead>模型 / 模式</TableHead>
                <TableHead>輸入</TableHead>
                <TableHead>狀態</TableHead>
                <TableHead className="text-right">進度</TableHead>
                <TableHead>資源</TableHead>
                <TableHead>建立者</TableHead>
                <TableHead className="text-right">時間</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.map((j) => (
                <TableRow key={j.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <KindChip kind={j.kind} />
                      <Link
                        href={`/projects/${project.slug}/jobs/${j.id}`}
                        className="font-medium hover:text-brand-ink"
                      >
                        {j.name}
                      </Link>
                      <span className="font-mono text-xs text-subtle-foreground">#{j.id}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <FamilyText family={j.modelFamily} />
                      {j.mode ? (
                        <span className="rounded-sm bg-muted px-1.5 text-[11px] text-muted-foreground">
                          {jobModeLabel[j.mode]}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <InputKindChip kind={j.input.kind} />
                      <span className="truncate font-mono text-xs text-muted-foreground">
                        {j.input.originalFilename ?? j.input.dataSourceName ?? "inline"}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={j.status} />
                      {j.status === "queued" ? (
                        <span className="font-mono text-xs text-muted-foreground tabular-nums">#{pos(j.id)}</span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {j.status === "queued" ? "—" : `${j.progress}%`}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground tabular-nums">
                    {j.requestedGpu} GPU · {j.requestedCpu} CPU · {formatMb(j.requestedMemoryMb)}
                  </TableCell>
                  <TableCell>
                    <UserInline user={j.createdBy} />
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                    {j.startedAt ? formatDuration(j.startedAt, j.finishedAt) : formatRelative(j.createdAt)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}

export default function JobsPage({ params }: PageProps<"/projects/[slug]/jobs">) {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <Jobs params={params} />
    </Suspense>
  );
}
