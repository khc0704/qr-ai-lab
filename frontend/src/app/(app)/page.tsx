import { ClipboardList, FolderKanban, HardDrive, ListOrdered, Plus, Timer } from "lucide-react";
import Link from "next/link";
import { KindChip } from "@/components/features/chips";
import { EmptyState } from "@/components/features/empty-state";
import { Greeting } from "@/components/features/greeting";
import { ProjectCard } from "@/components/features/project-card";
import { StatCard } from "@/components/features/stat-card";
import { StatusBadge } from "@/components/features/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RelativeTime } from "@/components/features/time";
import { formatBytes } from "@/lib/format";
import { getAdminOverview, getCapacity, listJobs, listProjectRequests, listProjects } from "@/lib/api";
import { getCurrentUser, isAdmin } from "@/lib/session";

export default async function HomePage() {
  const user = await getCurrentUser();
  const admin = isAdmin(user);
  const [projects, jobs, requests, capacity, overview] = await Promise.all([
    listProjects(),
    listJobs({ limit: 6 }),
    listProjectRequests({ applicantId: user.id }),
    getCapacity(),
    admin ? getAdminOverview() : null,
  ]);
  const { pool, allocated } = capacity;
  const running = jobs.filter((j) => j.status === "running").length;
  const storage = projects.reduce((s, p) => s + p.storageUsedBytes, 0);
  const freeGpu = pool.gpuIndices.length - allocated.gpu;

  return (
    <>
      <PageHeader
        eyebrow={<Greeting />}
        title={`${user.displayName}，今天有 ${freeGpu} 張 GPU 可用`}
        description={`資源池 ${pool.gpuIndices.length} GPU 中 ${allocated.gpu} 張執行中${overview ? `；佇列中 ${overview.queued} 個任務` : ""}。`}
        actions={
          <Button asChild>
            <Link href="/project-requests/new">
              <Plus />
              申請新專案
            </Link>
          </Button>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="我的專案"
          value={projects.length}
          icon={FolderKanban}
          hint={`${projects.filter((p) => p.usage.runningJobs > 0).length} 個有任務執行中`}
        />
        <StatCard
          label="執行中任務"
          value={running}
          icon={Timer}
          tone={running > 0 ? "signal" : "default"}
          hint="全部專案"
        />
        <StatCard
          label="我的申請"
          value={requests.filter((r) => r.status === "submitted" || r.status === "in_review").length}
          icon={ClipboardList}
          tone="warning"
          hint={`共 ${requests.length} 件`}
        />
        <StatCard label="儲存使用" value={formatBytes(storage)} icon={HardDrive} hint="本機專案資料夾合計" />
      </div>
      {admin && overview ? (
        <div className="grid gap-4 sm:grid-cols-3">
          <StatCard
            label="待審申請"
            value={overview.pendingRequests}
            tone="warning"
            hint={
              <Link href="/admin/requests" className="text-brand-ink hover:underline">
                前往審核
              </Link>
            }
          />
          <StatCard
            label="佇列"
            value={overview.queued}
            icon={ListOrdered}
            hint={
              <Link href="/admin/queue" className="text-brand-ink hover:underline">
                管理佇列
              </Link>
            }
          />
          <StatCard
            label="資源池使用率"
            value={`${overview.poolUtilization}%`}
            hint={`${overview.poolGpuUsed} / ${overview.poolGpuTotal} GPU`}
            tone={overview.poolUtilization >= 90 ? "destructive" : "default"}
          />
        </div>
      ) : null}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold tracking-tight">我的專案</h2>
          <Link href="/projects" className="text-sm text-brand-ink hover:underline">
            全部專案
          </Link>
        </div>
        {projects.length === 0 ? (
          <EmptyState
            icon={FolderKanban}
            title="還沒有專案"
            description="先在「專案申請」提出申請，管理員核准後專案會出現在這裡。"
            dots
            action={
              <Button asChild>
                <Link href="/project-requests/new">申請新專案</Link>
              </Button>
            }
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {projects.map((p) => (
              <ProjectCard key={p.id} project={p} latestJob={jobs.find((j) => j.projectId === p.id)} />
            ))}
          </div>
        )}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight">最近的任務</h2>
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>任務</TableHead>
                <TableHead>專案</TableHead>
                <TableHead>狀態</TableHead>
                <TableHead className="text-right">進度</TableHead>
                <TableHead className="text-right">建立</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.map((j) => (
                <TableRow key={j.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <KindChip kind={j.kind} />
                      <Link
                        href={`/projects/${j.projectSlug}/jobs/${j.id}`}
                        className="font-medium hover:text-brand-ink"
                      >
                        {j.name}
                      </Link>
                      <span className="font-mono text-xs text-subtle-foreground">#{j.id}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{j.projectName}</TableCell>
                  <TableCell>
                    <StatusBadge status={j.status} />
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {j.status === "queued" ? "—" : `${j.progress}%`}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                    <RelativeTime iso={j.createdAt} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
    </>
  );
}
