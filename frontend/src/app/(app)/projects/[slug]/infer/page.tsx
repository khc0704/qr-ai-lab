import { Download } from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";
import { JobLive } from "@/components/features/job-live";
import { JobResults } from "@/components/features/job-results";
import { JobStatusBar } from "@/components/features/job-status-bar";
import { PageSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { RelativeTime } from "@/components/features/time";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { inferenceModeLabel } from "@/i18n/zh-TW";
import { getCatalog, getJob, getJobLog, getProject, getToolPoolStatus, listArtifacts, listJobsPage } from "@/lib/api";
import { canCancelJob, canProject, isApproved, projectRole } from "@/lib/roles";
import { getCurrentUser } from "@/lib/session";
import { withBase } from "@/lib/base-path";
import { modelPreprocessOps } from "@/lib/preprocess-steps";
import { cn } from "@/lib/utils";
import type { InferenceMode } from "@/types/domain";
import { InferPanel, type InferModel } from "./infer-panel";

async function Infer({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ job?: string | string[] }>;
}) {
  const [{ slug }, sp] = await Promise.all([params, searchParams]);
  const [project, user] = await Promise.all([getProject(slug), getCurrentUser()]);
  if (!project) notFound();
  if (!isApproved(project)) redirect(`/projects/${project.slug}/application`);
  const role = projectRole(project, user);
  const canRun = canProject(role, "run") && project.status === "active";
  const jobParam = Array.isArray(sp.job) ? sp.job[0] : sp.job;
  const jobId = Number(jobParam);
  const [artifacts, catalog, recent, pool, picked] = await Promise.all([
    listArtifacts(project.slug, "model"),
    getCatalog(),
    listJobsPage({ slug: project.slug, ephemeral: true, pageSize: 8 }),
    getToolPoolStatus(),
    Number.isInteger(jobId) && jobId > 0 ? getJob(jobId) : undefined,
  ]);
  const current = picked && picked.projectSlug === project.slug && picked.ephemeral ? picked : undefined;
  const log = current ? await getJobLog(current.id, 400) : undefined;
  const models: InferModel[] = artifacts.map((m) => {
    const fam = catalog.families[m.modelFamily];
    return {
      id: m.id,
      name: m.name,
      version: m.version,
      family: m.modelFamily,
      isDefault: m.isDefault,
      inferenceModes: ((m.metadata?.inference_modes as string[] | undefined) ?? fam?.inference_modes ?? []) as string[],
      gpuRequired: fam?.resources.gpu === "required",
      weightsReady: fam?.weights_ready !== false,
      preprocess: modelPreprocessOps(m.metadata),
    };
  });
  const canCancel = current ? canCancelJob(role, user, current.createdBy.id) : false;
  const mode = (current?.config?.mode as InferenceMode | undefined) ?? undefined;

  return (
    <div className="space-y-6">
      <InferPanel
        slug={project.slug}
        dataType={project.dataType}
        taskType={project.taskType}
        canRun={canRun}
        models={models}
      />
      {current && log ? (
        <section className="space-y-4" data-testid="infer-view">
          <JobStatusBar job={current} queuePosition={current.queuePosition} canCancel={canCancel} />
          <JobLive
            job={current}
            log={log}
            overview={
              <dl className="grid gap-x-6 gap-y-1 font-mono text-xs tabular-nums sm:grid-cols-2 lg:grid-cols-4">
                {(
                  [
                    ["模型", current.artifactId ? `#${current.artifactId}` : "—"],
                    ["推論模式", mode ? (inferenceModeLabel[mode] ?? mode) : "—"],
                    [
                      "輸入",
                      current.input.originalFilename ??
                        (current.input.rows ? `${current.input.rows.length} 筆直接輸入` : "—"),
                    ],
                    ["建立", current.createdAt],
                  ] as [string, string][]
                ).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3 border-b border-border/60 py-1">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd className="truncate text-right">{k === "建立" ? <RelativeTime iso={v} /> : v}</dd>
                  </div>
                ))}
              </dl>
            }
            results={
              current.result ? (
                <div className="space-y-4">
                  {current.status === "succeeded" ? (
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-card px-4 py-3 text-sm">
                      <span className="text-muted-foreground">
                        完整結果（所有列）可下載為 CSV；{pool.resultTtlHours} 小時後連同這次推論一起清除。
                      </span>
                      <Button variant="outline" size="sm" asChild>
                        <a
                          href={withBase(`/api/download/jobs/${current.id}/download`)}
                          download
                          data-testid="infer-download"
                        >
                          <Download />
                          下載結果（CSV）
                        </a>
                      </Button>
                    </div>
                  ) : null}
                  <JobResults result={current.result} job={current} />
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">推論完成後結果會顯示在這裡。</p>
              )
            }
            resultsLabel="結果"
            config={
              <pre className="overflow-auto rounded-md border border-border bg-muted p-3 font-mono text-xs">
                {JSON.stringify({ config: current.config, input: current.input.spec }, null, 2)}
              </pre>
            }
            defaultTab={current.status === "succeeded" ? "results" : "overview"}
          />
        </section>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>最近的一次性推論</CardTitle>
          <CardDescription>
            這些推論不會進入任務列表，結果與輸出在 {pool.resultTtlHours} 小時後自動清除。
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {recent.items.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-muted-foreground">還沒有推論。</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>推論</TableHead>
                  <TableHead>狀態</TableHead>
                  <TableHead>模式</TableHead>
                  <TableHead>輸入</TableHead>
                  <TableHead className="text-right">建立</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recent.items.map((j) => {
                  const m = j.config?.mode as InferenceMode | undefined;
                  return (
                    <TableRow key={j.id} className={cn(current?.id === j.id && "bg-primary/5")}>
                      <TableCell>
                        <Link
                          href={`/projects/${project.slug}/infer?job=${j.id}`}
                          className="font-medium hover:underline"
                        >
                          #{j.id} {j.name}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={j.status} />
                      </TableCell>
                      <TableCell className="font-mono text-xs">{m ? (inferenceModeLabel[m] ?? m) : "—"}</TableCell>
                      <TableCell className="max-w-56 truncate font-mono text-xs">
                        {j.input.originalFilename ?? (j.input.rows ? `${j.input.rows.length} 筆直接輸入` : "—")}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        <RelativeTime iso={j.createdAt} />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function InferPage({ params, searchParams }: PageProps<"/projects/[slug]/infer">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Infer params={params} searchParams={searchParams} />
    </Suspense>
  );
}
