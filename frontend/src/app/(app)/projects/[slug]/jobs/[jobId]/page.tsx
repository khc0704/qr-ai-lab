import { Download, Star } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { FamilyText, InputKindChip } from "@/components/features/chips";
import { JobStatusBar } from "@/components/features/job-status-bar";
import { LogViewer } from "@/components/features/log-viewer";
import { UserInline } from "@/components/features/member-avatars";
import { PageSkeleton } from "@/components/features/skeletons";
import { StatCard } from "@/components/features/stat-card";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { artifactKindLabel, jobKindLabel, jobModeLabel, jobStageLabel, modelFamilyLabel } from "@/i18n/zh-TW";
import { getArtifact, getJob, getJobLog, getQueuePosition, listArtifactsForJob } from "@/lib/api";
import { formatBytes, formatDateTime, formatMetric, formatRelative } from "@/lib/format";

async function JobDetail({ params }: { params: Promise<{ slug: string; jobId: string }> }) {
  const { slug, jobId } = await params;
  const job = await getJob(Number(jobId));
  if (!job || job.projectSlug !== slug) notFound();
  const [log, artifacts, position, model] = await Promise.all([
    getJobLog(job.id),
    listArtifactsForJob(job.id),
    getQueuePosition(job.id),
    job.artifactId ? getArtifact(job.artifactId) : undefined,
  ]);
  const { leaderboard, ...metrics } = job.metrics ?? {};
  const metricEntries = Object.entries(metrics).filter(([, v]) => typeof v === "number") as [string, number][];

  return (
    <>
      <PageHeader
        eyebrow={
          <span className="font-mono normal-case">
            #{job.id} · {jobKindLabel[job.kind]}
            {job.mode ? ` · ${jobModeLabel[job.mode]}` : ""}
          </span>
        }
        title={job.name}
        description={
          <span className="inline-flex flex-wrap items-center gap-2">
            建立者 <UserInline user={job.createdBy} /> ·{" "}
            <span className="font-mono text-xs" title={formatDateTime(job.createdAt)}>
              {formatRelative(job.createdAt)}
            </span>
          </span>
        }
      />
      <JobStatusBar job={job} queuePosition={position} />
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">概況</TabsTrigger>
          <TabsTrigger value="log">Log</TabsTrigger>
          <TabsTrigger value="artifacts">{job.kind === "train" ? "產物" : "結果"}</TabsTrigger>
          <TabsTrigger value="config">設定</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="space-y-6 pt-4">
          {job.status === "running" ? (
            <Card className="gap-3 p-5">
              <div className="flex items-center justify-between">
                <span className="text-label">{job.currentStage ? jobStageLabel[job.currentStage] : "進度"}</span>
                <span className="font-mono text-sm tabular-nums">{job.progress}%</span>
              </div>
              <Progress value={job.progress} />
              {job.config?.search ? (
                <p className="text-xs text-muted-foreground">
                  AutoML：trial {String(metrics.trial ?? "—")} /{" "}
                  {String((job.config.search as { max_trials: number }).max_trials)}，目前最佳{" "}
                  {metricEntries
                    .filter(([k]) => k.startsWith("best_"))
                    .map(([k, v]) => `${k.replace("best_", "")}=${formatMetric(v)}`)
                    .join(" ") || "—"}
                </p>
              ) : null}
            </Card>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="模型"
              value={<span className="text-base">{job.modelFamily ? modelFamilyLabel[job.modelFamily] : "—"}</span>}
              hint={
                job.modelFamily ? (
                  <span className="font-mono">{job.modelFamily}</span>
                ) : job.mode === "auto" ? (
                  "AutoML 完成後回填最佳家族"
                ) : undefined
              }
            />
            {metricEntries
              .filter(([k]) => k !== "trial" && k !== "epoch")
              .slice(0, 3)
              .map(([k, v]) => (
                <StatCard
                  key={k}
                  label={k}
                  value={formatMetric(v)}
                  tone={k.startsWith("best_") ? "signal" : "default"}
                />
              ))}
          </div>
          {leaderboard?.length ? (
            <Card>
              <CardHeader>
                <CardTitle>AutoML Leaderboard</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-16 text-right">Trial</TableHead>
                      <TableHead>模型</TableHead>
                      <TableHead>參數</TableHead>
                      <TableHead className="text-right">指標</TableHead>
                      <TableHead className="text-right">耗時</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {leaderboard.map((r, i) => (
                      <TableRow key={r.trial} className={i === 0 ? "bg-primary/5" : undefined}>
                        <TableCell className="text-right font-mono text-xs tabular-nums">{r.trial}</TableCell>
                        <TableCell>
                          <FamilyText family={r.family} />
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {Object.entries(r.params)
                            .map(([k, v]) => `${k}=${v}`)
                            .join("  ")}
                        </TableCell>
                        <TableCell
                          className={`text-right font-mono text-xs tabular-nums ${i === 0 ? "font-semibold text-brand-ink" : ""}`}
                        >
                          {formatMetric(r.metric)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                          {r.durationS}s
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>
        <TabsContent value="log" className="pt-4">
          <LogViewer lines={log} status={job.status} title={`job.log`} maxHeight="max-h-[640px]" />
        </TabsContent>
        <TabsContent value="artifacts" className="pt-4">
          {job.kind === "inference" ? (
            <Card>
              <CardHeader>
                <CardTitle>推論結果</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div>
                  使用模型：
                  {model ? (
                    <Link href={`/projects/${slug}/models`} className="text-brand-ink hover:underline">
                      {model.name} v{model.version}
                    </Link>
                  ) : (
                    "—"
                  )}
                </div>
                {metricEntries.length ? (
                  <dl className="grid max-w-sm grid-cols-2 gap-1 font-mono text-xs tabular-nums">
                    {metricEntries.map(([k, v]) => (
                      <div key={k} className="contents">
                        <dt className="text-muted-foreground">{k}</dt>
                        <dd className="text-right">{formatMetric(v)}</dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="text-muted-foreground">任務完成後會在這裡顯示結果摘要與下載。</p>
                )}
                {job.status === "succeeded" ? (
                  <Button variant="outline" size="sm">
                    <Download />
                    下載結果
                  </Button>
                ) : null}
              </CardContent>
            </Card>
          ) : artifacts.length === 0 ? (
            <Card>
              <CardContent className="text-sm text-muted-foreground">
                {job.status === "succeeded" ? "沒有登記產物。" : "任務成功後產物會列在這裡。"}
              </CardContent>
            </Card>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名稱</TableHead>
                    <TableHead>種類</TableHead>
                    <TableHead>路徑</TableHead>
                    <TableHead className="text-right">大小</TableHead>
                    <TableHead className="w-40" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {artifacts.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell className="font-medium">
                        {a.name} <span className="font-mono text-xs text-muted-foreground">v{a.version}</span>
                        {a.isDefault ? (
                          <span className="ml-2 rounded-sm bg-primary/10 px-1.5 text-[11px] text-brand-ink">預設</span>
                        ) : null}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{artifactKindLabel[a.kind]}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{a.path}</TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {formatBytes(a.sizeBytes)}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          {a.kind === "model" && !a.isDefault ? (
                            <Button variant="ghost" size="sm">
                              <Star />
                              設為預設
                            </Button>
                          ) : null}
                          <Button variant="ghost" size="icon-sm" aria-label="下載">
                            <Download />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>
        <TabsContent value="config" className="grid gap-4 pt-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                輸入 <InputKindChip kind={job.input.kind} />
              </CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="overflow-auto rounded-md bg-background p-3 font-mono text-xs leading-5">
                {JSON.stringify(job.input, null, 2)}
              </pre>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>設定</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="overflow-auto rounded-md bg-background p-3 font-mono text-xs leading-5">
                {JSON.stringify(job.config ?? {}, null, 2)}
              </pre>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  );
}

export default function JobPage({ params }: PageProps<"/projects/[slug]/jobs/[jobId]">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <JobDetail params={params} />
    </Suspense>
  );
}
