import { Box, Cpu, HardDrive, MemoryStick, Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { FamilyText, KindChip } from "@/components/features/chips";
import { ResourceMeter } from "@/components/features/resource-meter";
import { PageSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { UserInline } from "@/components/features/member-avatars";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { projectRoleLabel } from "@/i18n/zh-TW";
import { getProject, listArtifacts, listJobs } from "@/lib/api";
import { RelativeTime } from "@/components/features/time";
import { formatBytes, formatMb, formatMetric } from "@/lib/format";
import { canProject, projectRole } from "@/lib/roles";
import { getCurrentUser } from "@/lib/session";

async function Overview({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [project, user] = await Promise.all([getProject(slug), getCurrentUser()]);
  if (!project) notFound();
  const [jobs, models] = await Promise.all([
    listJobs({ slug: project.slug, limit: 5 }),
    listArtifacts(project.slug, "model"),
  ]);
  const def = models.find((m) => m.isDefault);
  const canRun = canProject(projectRole(project, user), "run") && project.status === "active";
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Card className="gap-3 p-5">
            <div className="flex items-center justify-between">
              <span className="text-label">GPU</span>
              <HardDrive className="size-4 text-muted-foreground" />
            </div>
            <ResourceMeter label="同時使用" used={project.usage.gpu} total={project.gpuLimit} compact />
          </Card>
          <Card className="gap-3 p-5">
            <div className="flex items-center justify-between">
              <span className="text-label">CPU</span>
              <Cpu className="size-4 text-muted-foreground" />
            </div>
            <ResourceMeter label="核數" used={project.usage.cpu} total={project.cpuLimit} compact />
          </Card>
          <Card className="gap-3 p-5">
            <div className="flex items-center justify-between">
              <span className="text-label">Memory</span>
              <MemoryStick className="size-4 text-muted-foreground" />
            </div>
            <ResourceMeter
              label="使用"
              used={project.usage.memoryMb}
              total={project.memoryLimitMb}
              format={formatMb}
              compact
            />
          </Card>
          <Card className="gap-3 p-5">
            <div className="flex items-center justify-between">
              <span className="text-label">Storage</span>
              <Box className="size-4 text-muted-foreground" />
            </div>
            <ResourceMeter
              label="專案資料夾"
              used={project.storageUsedBytes}
              total={project.storageQuotaMb * 1024 * 1024}
              format={formatBytes}
              compact
            />
          </Card>
        </div>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>最近任務</CardTitle>
            {canRun ? (
              <Button size="sm" asChild>
                <Link href={`/projects/${project.slug}/jobs/new`}>
                  <Plus />
                  新建訓練
                </Link>
              </Button>
            ) : null}
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>任務</TableHead>
                  <TableHead>模型</TableHead>
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
                          href={`/projects/${project.slug}/jobs/${j.id}`}
                          className="font-medium hover:text-brand-ink"
                        >
                          {j.name}
                        </Link>
                        <span className="font-mono text-xs text-subtle-foreground">#{j.id}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <FamilyText family={j.modelFamily} />
                    </TableCell>
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
          </CardContent>
        </Card>
      </div>
      <aside className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>預設模型</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {def ? (
              <>
                <div className="font-medium">
                  {def.name} <span className="font-mono text-xs text-muted-foreground">v{def.version}</span>
                </div>
                <FamilyText family={def.modelFamily} />
                <dl className="grid grid-cols-2 gap-1 font-mono text-xs tabular-nums">
                  {Object.entries(def.metrics ?? {}).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-muted-foreground">{k}</dt>
                      <dd className="text-right">{formatMetric(v)}</dd>
                    </div>
                  ))}
                </dl>
                <div className="text-xs text-muted-foreground">
                  {formatBytes(def.sizeBytes)} · <RelativeTime iso={def.createdAt} />
                </div>
              </>
            ) : (
              <span className="text-muted-foreground">尚未設定；到「模型」分頁選一個。</span>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>成員</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {project.members.map((m) => (
              <div key={m.user.id} className="flex items-center justify-between">
                <UserInline user={m.user} />
                <span className="text-xs text-muted-foreground">{projectRoleLabel[m.role]}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </aside>
    </div>
  );
}

export default function ProjectOverviewPage({ params }: PageProps<"/projects/[slug]">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Overview params={params} />
    </Suspense>
  );
}
