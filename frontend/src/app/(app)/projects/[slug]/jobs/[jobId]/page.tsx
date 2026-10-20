import { Copy, Download, Info, PackageOpen } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { AdminJobActions } from "@/components/features/admin-job-actions";
import { AnalysisReport } from "@/components/features/analysis-report";
import { PreprocessJobResults } from "@/components/features/tool-job-results";
import { ArtifactRowActions } from "@/components/features/artifact-row-actions";
import { FamilyText, InputKindChip } from "@/components/features/chips";
import { EmptyState } from "@/components/features/empty-state";
import { JobLive } from "@/components/features/job-live";
import { JobResults } from "@/components/features/job-results";
import { JobStatusBar } from "@/components/features/job-status-bar";
import { LeaderboardChart } from "@/components/features/leaderboard-chart";
import { UserInline } from "@/components/features/member-avatars";
import { PageSkeleton } from "@/components/features/skeletons";
import { StatCard } from "@/components/features/stat-card";
import { RelativeTime } from "@/components/features/time";
import { PageHeader } from "@/components/layout/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  analysisKindLabel,
  artifactKindLabel,
  familyLabel,
  inferenceModeLabel,
  jobCopy,
  jobKindLabel,
  jobModeLabel,
} from "@/i18n/zh-TW";
import { getArtifact, getJob, getJobLog, getProject, listArtifactsForJob } from "@/lib/api";
import { formatBytes, formatMetric } from "@/lib/format";
import { canCancelJob, canProject, projectRole } from "@/lib/roles";
import { can, getCurrentUser } from "@/lib/session";
import type { AnalysisKind, InferenceMode, PreprocessStep } from "@/types/domain";
import { withBase } from "@/lib/base-path";

async function JobDetail({ params }: { params: Promise<{ slug: string; jobId: string }> }) {
  const { slug, jobId } = await params;
  const job = await getJob(Number(jobId));
  if (!job || job.projectSlug !== slug) notFound();
  const [log, artifacts, model, user, project] = await Promise.all([
    getJobLog(job.id),
    listArtifactsForJob(job.id),
    job.artifactId ? getArtifact(job.artifactId) : undefined,
    getCurrentUser(),
    getProject(job.projectSlug),
  ]);
  const controlsJobs = can(user, "jobs.control");
  const role = projectRole(project, user);
  const canCancel = canCancelJob(role, user, job.createdBy.id);
  const canRun = canProject(role, "run");
  const { leaderboard, ...metrics } = job.metrics ?? {};
  // Live metrics (job.metrics) are whatever the trainer reported last. Once a training job has a result, or
  // an AutoML leaderboard, the headline cards show the best model instead of the last trial.
  const finalMetrics =
    (job.kind === "train" && job.result?.metrics && typeof job.result.metrics === "object"
      ? (job.result.metrics as Record<string, unknown>)
      : undefined) ??
    leaderboard?.[0]?.metrics ??
    metrics;
  const metricEntries = Object.entries(finalMetrics).filter(([, v]) => typeof v === "number") as [string, number][];
  const headline = metricEntries.filter(([k]) => k !== "trial" && k !== "epoch" && k !== "n_trials");
  const search = job.config?.search as { max_trials?: number; metric?: string; direction?: string } | undefined;
  const metricName =
    (typeof job.result?.metric === "string" ? job.result.metric : undefined) ??
    search?.metric ??
    Object.keys(metrics)
      .find((k) => k.startsWith("best_"))
      ?.replace("best_", "") ??
    headline[0]?.[0] ??
    "metric";
  const direction =
    (job.result?.direction as "maximize" | "minimize" | undefined) ??
    (/(rmse|mae|mse|loss|error|distance|reconstruction)/i.test(metricName) ? "minimize" : "maximize");
  const preprocess = (job.input.spec?.preprocess ?? []) as PreprocessStep[];
  const inferenceMode = job.config?.mode as InferenceMode | undefined;
  const isTool = job.kind === "preprocess" || job.kind === "analysis";
  const analysisKind = job.config?.analysis as AnalysisKind | undefined;

  // AutoML runs stopped early (time budget / cancel) still export the best trial so far; say so next to the metrics.
  const stoppedNote =
    job.result?.stopped === "deadline"
      ? jobCopy.stoppedDeadline
      : job.result?.stopped === "cancelled"
        ? jobCopy.stoppedCancelled
        : undefined;

  const overview = (
    <>
      {stoppedNote ? (
        <Alert>
          <Info />
          <AlertDescription>{stoppedNote}</AlertDescription>
        </Alert>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label={
            job.kind === "train"
              ? "模型家族"
              : job.kind === "inference"
                ? "推論模式"
                : job.kind === "analysis"
                  ? "分析類型"
                  : "前處理步驟"
          }
          value={
            <span className="text-base">
              {job.kind === "train"
                ? familyLabel(job.modelFamily)
                : job.kind === "inference"
                  ? inferenceMode
                    ? (inferenceModeLabel[inferenceMode] ?? inferenceMode)
                    : "—"
                  : job.kind === "analysis"
                    ? analysisKind
                      ? (analysisKindLabel[analysisKind] ?? analysisKind)
                      : "—"
                    : `${preprocess.length} 步`}
            </span>
          }
          hint={
            job.modelFamily ? (
              <span className="font-mono">{job.modelFamily}</span>
            ) : job.mode === "auto" ? (
              "AutoML 完成後回填最佳家族"
            ) : isTool ? (
              "工具池任務；輸入檔於任務結束後刪除"
            ) : undefined
          }
        />
        {headline.slice(0, 3).map(([k, v]) => (
          <StatCard key={k} label={k} value={formatMetric(v)} tone={k.startsWith("best_") ? "signal" : "default"} />
        ))}
      </div>
      {leaderboard?.length ? (
        <Card>
          <CardHeader>
            <CardTitle>AutoML Leaderboard</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <LeaderboardChart rows={leaderboard} metricName={metricName} direction={direction} />
            <div className="overflow-hidden rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-16 text-right">Trial</TableHead>
                    <TableHead>模型</TableHead>
                    <TableHead>參數</TableHead>
                    <TableHead className="text-right">{metricName}</TableHead>
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
                      <TableCell className="max-w-md truncate font-mono text-xs text-muted-foreground">
                        {Object.entries(r.params)
                          .map(
                            ([k, v]) =>
                              `${k}=${typeof v === "number" && !Number.isInteger(v) ? formatMetric(v) : String(v)}`,
                          )
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
            </div>
          </CardContent>
        </Card>
      ) : null}
      {metricEntries.length > 4 ? (
        <Card>
          <CardHeader>
            <CardTitle>所有指標</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-x-6 gap-y-1 font-mono text-xs tabular-nums sm:grid-cols-2 lg:grid-cols-3">
              {metricEntries.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 border-b border-border/60 py-1">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd>{formatMetric(v)}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      ) : null}
    </>
  );

  const results =
    job.kind === "preprocess" ? (
      <PreprocessJobResults job={job} />
    ) : job.kind === "analysis" ? (
      job.result ? (
        <AnalysisReport result={job.result} />
      ) : (
        <Card>
          <CardContent className="text-sm text-muted-foreground">任務完成後會在這裡顯示分析報告。</CardContent>
        </Card>
      )
    ) : job.kind === "inference" ? (
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>推論</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <span>
              使用模型：
              {model ? (
                <Link href={`/projects/${slug}/models`} className="text-brand-ink hover:underline">
                  {model.name} v{model.version}
                </Link>
              ) : (
                "—"
              )}
            </span>
            <span>
              模式：
              <span className="font-mono text-xs">{inferenceMode ?? "predict"}</span>
            </span>
            {job.status === "succeeded" ? (
              <Button variant="outline" size="sm" asChild className="ml-auto">
                <a href={withBase(`/api/download/jobs/${job.id}/download`)} download>
                  <Download />
                  下載結果（CSV）
                </a>
              </Button>
            ) : null}
          </CardContent>
        </Card>
        {job.result ? (
          <JobResults result={job.result} job={job} />
        ) : (
          <Card>
            <CardContent className="text-sm text-muted-foreground">
              任務完成後會在這裡顯示結果摘要、預覽與下載。
            </CardContent>
          </Card>
        )}
      </div>
    ) : artifacts.length === 0 ? (
      <EmptyState
        icon={PackageOpen}
        title={job.status === "succeeded" ? "沒有登記產物" : "任務成功後產物會列在這裡"}
        description="模型、前處理狀態、指標與報告都會以產物形式保存在專案資料夾。"
      />
    ) : (
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>名稱</TableHead>
              <TableHead>種類</TableHead>
              <TableHead>路徑</TableHead>
              <TableHead className="text-right">大小</TableHead>
              <TableHead className="w-44" />
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
                <TableCell className="text-right font-mono text-xs tabular-nums">{formatBytes(a.sizeBytes)}</TableCell>
                <TableCell className="text-right">
                  <ArtifactRowActions
                    id={a.id}
                    slug={slug}
                    kind={a.kind}
                    isDefault={a.isDefault}
                    canSetDefault={canProject(role, "edit")}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    );

  const config = (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            輸入 <InputKindChip kind={job.input.kind} />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {preprocess.length ? (
            <ol className="space-y-1 text-sm">
              {preprocess.map((s, i) => (
                <li key={i} className="flex flex-wrap items-baseline gap-2">
                  <span className="font-mono text-xs text-muted-foreground tabular-nums">{i + 1}.</span>
                  <span className="font-mono text-xs">{s.op}</span>
                  {s.params && Object.keys(s.params).length ? (
                    <span className="font-mono text-xs text-muted-foreground">{JSON.stringify(s.params)}</span>
                  ) : null}
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-xs text-muted-foreground">未使用前處理步驟。</p>
          )}
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
    </div>
  );

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
            <RelativeTime iso={job.createdAt} className="font-mono text-xs" />
          </span>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {controlsJobs ? <AdminJobActions job={job} /> : null}
            {isTool || !canRun ? null : (
              <Button variant="outline" size="sm" asChild>
                <Link href={`/projects/${slug}/jobs/new?from=${job.id}`}>
                  <Copy />
                  複製設定
                </Link>
              </Button>
            )}
          </div>
        }
      />
      <JobStatusBar job={job} canCancel={canCancel} />
      <JobLive
        job={job}
        log={log}
        overview={overview}
        results={results}
        resultsLabel={job.kind === "train" ? "產物" : job.kind === "analysis" ? "報告" : "結果"}
        config={config}
        defaultTab={isTool && (job.status === "succeeded" || job.status === "failed") ? "results" : "overview"}
      />
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
