import { ClipboardList, FolderKanban, Plus } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";
import { DataTypeChip, TaskChip } from "@/components/features/chips";
import { EmptyState } from "@/components/features/empty-state";
import { UserInline } from "@/components/features/member-avatars";
import { ProjectCard } from "@/components/features/project-card";
import { PageSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { RelativeTime } from "@/components/features/time";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { projectStatusHint, projectStatusLabel } from "@/i18n/zh-TW";
import { listJobs, listProjects } from "@/lib/api";
import { formatMb } from "@/lib/format";
import { getCurrentUser, isAdmin } from "@/lib/session";
import { cn } from "@/lib/utils";
import type { Project, ProjectStatus } from "@/types/domain";

type Filter = "all" | "pending" | ProjectStatus;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "active", label: projectStatusLabel.active },
  { value: "pending", label: "申請中 / 審核中" },
  { value: "rejected", label: projectStatusLabel.rejected },
  { value: "completed", label: projectStatusLabel.completed },
  { value: "archived", label: projectStatusLabel.archived },
];

function pickFilter(raw: string | string[] | undefined): Filter {
  const v = Array.isArray(raw) ? raw[0] : raw;
  return FILTERS.some((f) => f.value === v) ? (v as Filter) : "all";
}

/** Applications (pending / in review / rejected) read better as a table: who applied for what, and since when. */
function ApplicationTable({ projects, showApplicant }: { projects: Project[]; showApplicant: boolean }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>專案</TableHead>
            <TableHead>資料 / 任務</TableHead>
            <TableHead>資源需求</TableHead>
            <TableHead>狀態</TableHead>
            {showApplicant ? <TableHead>申請人</TableHead> : null}
            <TableHead className="text-right">送出</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {projects.map((p) => (
            <TableRow key={p.id}>
              <TableCell>
                <Link href={`/projects/${p.slug}/application`} className="font-medium hover:text-brand-ink">
                  {p.name}
                </Link>
                <div className="font-mono text-[11px] text-subtle-foreground">{p.slug}</div>
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  <DataTypeChip dataType={p.dataType} />
                  <TaskChip taskType={p.taskType} />
                </div>
              </TableCell>
              <TableCell className="font-mono text-xs tabular-nums">
                {p.application
                  ? `${p.application.requestedGpu} GPU · ${p.application.requestedCpu} CPU · ${formatMb(p.application.requestedMemoryMb)}`
                  : "—"}
              </TableCell>
              <TableCell>
                <StatusBadge status={p.status} />
              </TableCell>
              {showApplicant ? (
                <TableCell>
                  <UserInline user={p.owner} />
                </TableCell>
              ) : null}
              <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                <RelativeTime iso={p.application?.submittedAt ?? p.createdAt} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

async function Projects({ searchParams }: { searchParams: Promise<{ status?: string | string[]; q?: string }> }) {
  const sp = await searchParams;
  const filter = pickFilter(sp.status);
  const q = typeof sp.q === "string" ? sp.q : undefined;
  const [user, projects] = await Promise.all([
    getCurrentUser(),
    listProjects({
      status: filter === "all" ? undefined : filter === "pending" ? ["pending"] : [filter],
      q,
    }),
  ]);
  const admin = isAdmin(user);
  const [jobs] = await Promise.all([projects.length ? listJobs({ limit: 100 }) : Promise.resolve([])]);
  const applications = projects.filter(
    (p) => p.status === "pending" || p.status === "in_review" || p.status === "rejected",
  );
  const working = projects.filter((p) => p.status === "active" || p.status === "completed");
  const archived = projects.filter((p) => p.status === "archived");
  const counts = {
    pending: projects.filter((p) => p.status === "pending" || p.status === "in_review").length,
  };
  return (
    <>
      <PageHeader
        title="專案"
        description={
          admin
            ? "所有專案與申請：申請中的專案點進「申請」分頁審核、核准並設定配額。"
            : "你有權限的專案與你提出的申請。新專案請按「專案申請」，管理員核准後其他分頁才會開放。"
        }
        actions={
          <Button asChild>
            <Link href="/projects/new">
              <Plus />
              專案申請
            </Link>
          </Button>
        }
      >
        <nav className="-mb-px flex gap-1 overflow-x-auto border-b border-border" aria-label="狀態篩選">
          {FILTERS.map((f) => (
            <Link
              key={f.value}
              href={f.value === "all" ? "/projects" : `/projects?status=${f.value}`}
              className={cn(
                "border-b-2 px-3 py-2 text-sm whitespace-nowrap transition-colors",
                filter === f.value
                  ? "border-primary font-medium text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {f.label}
              {f.value === "pending" && counts.pending && filter === "all" ? (
                <span className="ml-1 rounded-sm bg-warning/10 px-1 font-mono text-[11px] text-warning">
                  {counts.pending}
                </span>
              ) : null}
            </Link>
          ))}
        </nav>
      </PageHeader>
      {projects.length === 0 ? (
        <EmptyState
          icon={filter === "pending" || filter === "rejected" ? ClipboardList : FolderKanban}
          title={filter === "all" ? "還沒有專案" : `沒有${FILTERS.find((f) => f.value === filter)?.label}的專案`}
          description={
            filter === "all" ? "填寫題目、資料類型與資源需求提出申請，管理員核准後專案就會開始進行。" : undefined
          }
          dots
          action={
            filter === "all" ? (
              <Button asChild>
                <Link href="/projects/new">專案申請</Link>
              </Button>
            ) : undefined
          }
        />
      ) : null}
      {applications.length ? (
        <section className="space-y-3">
          <div className="flex items-baseline gap-2">
            <h2 className="text-lg font-semibold tracking-tight">申請</h2>
            <span className="text-xs text-muted-foreground">{projectStatusHint.pending}</span>
          </div>
          <ApplicationTable projects={applications} showApplicant={admin} />
        </section>
      ) : null}
      {working.length ? (
        <section className="space-y-3">
          {applications.length ? <h2 className="text-lg font-semibold tracking-tight">進行中</h2> : null}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {working.map((p) => (
              <ProjectCard key={p.id} project={p} latestJob={jobs.find((j) => j.projectId === p.id)} />
            ))}
          </div>
        </section>
      ) : null}
      {archived.length ? (
        <section className="space-y-3">
          <h2 className="text-label">已封存</h2>
          <div className="grid gap-4 opacity-70 md:grid-cols-2 xl:grid-cols-3">
            {archived.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}

export default function ProjectsPage({ searchParams }: PageProps<"/projects">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Projects searchParams={searchParams} />
    </Suspense>
  );
}
