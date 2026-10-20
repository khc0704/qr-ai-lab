import { Brain, Plus, Sparkles } from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";
import { EmptyState } from "@/components/features/empty-state";
import { FamilyText, InputKindChip, KindChip } from "@/components/features/chips";
import { UserInline } from "@/components/features/member-avatars";
import { pageFromParam, pageHref, Pagination } from "@/components/features/pagination";
import { TableSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { jobModeLabel } from "@/i18n/zh-TW";
import { Duration, RelativeTime } from "@/components/features/time";
import { getProject, listJobsPage } from "@/lib/api";
import { formatMb } from "@/lib/format";
import { canProject, isApproved, projectRole } from "@/lib/roles";
import { getCurrentUser } from "@/lib/session";

const PAGE_SIZE = 20;

async function Jobs({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ page?: string | string[] }>;
}) {
  const [{ slug }, sp] = await Promise.all([params, searchParams]);
  const page = pageFromParam(sp.page);
  const [project, user] = await Promise.all([getProject(slug), getCurrentUser()]);
  if (!project) notFound();
  if (!isApproved(project)) redirect(`/projects/${project.slug}/application`);
  const jobs = await listJobsPage({ slug: project.slug, page, pageSize: PAGE_SIZE });
  const canRun = canProject(projectRole(project, user), "run") && project.status === "active";
  const href = (p: number) => pageHref(`/projects/${project.slug}/jobs`, {}, p);
  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-muted-foreground tabular-nums">
          {jobs.total} 個任務 · 同時上限 {project.maxConcurrentJobs}
        </span>
        {canRun ? (
          <div className="flex gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link href={`/projects/${project.slug}/infer`}>
                <Sparkles />
                推論
              </Link>
            </Button>
            <Button size="sm" asChild>
              <Link href={`/projects/${project.slug}/jobs/new`}>
                <Plus />
                新建訓練
              </Link>
            </Button>
          </div>
        ) : null}
      </div>
      {jobs.items.length === 0 ? (
        <EmptyState
          icon={Brain}
          title={jobs.total === 0 ? "還沒有任務" : "這一頁沒有任務"}
          description={
            jobs.total === 0
              ? canRun
                ? "先新建一個訓練任務；不確定選什麼模型就用自動模式。"
                : "專案成員建立任務後會列在這裡。"
              : "回到第一頁查看。"
          }
          dots
          action={
            jobs.total === 0 && canRun ? (
              <Button asChild>
                <Link href={`/projects/${project.slug}/jobs/new`}>新建訓練</Link>
              </Button>
            ) : jobs.total > 0 ? (
              <Button variant="outline" asChild>
                <Link href={href(1)}>第一頁</Link>
              </Button>
            ) : undefined
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
              {jobs.items.map((j) => (
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
                        <span className="font-mono text-xs text-muted-foreground tabular-nums">
                          #{j.queuePosition ?? "—"}
                        </span>
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
                    {j.startedAt ? (
                      <Duration start={j.startedAt} end={j.finishedAt} />
                    ) : (
                      <RelativeTime iso={j.createdAt} />
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <Pagination page={jobs.page} pageSize={jobs.pageSize} total={jobs.total} href={href} />
    </>
  );
}

export default function JobsPage({ params, searchParams }: PageProps<"/projects/[slug]/jobs">) {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <Jobs params={params} searchParams={searchParams} />
    </Suspense>
  );
}
