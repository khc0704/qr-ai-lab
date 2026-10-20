import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { AdminJobActions } from "@/components/features/admin-job-actions";
import { AnalysisReport } from "@/components/features/analysis-report";
import { InputKindChip } from "@/components/features/chips";
import { JobLive } from "@/components/features/job-live";
import { JobStatusBar } from "@/components/features/job-status-bar";
import { UserInline } from "@/components/features/member-avatars";
import { PageSkeleton } from "@/components/features/skeletons";
import { StatCard } from "@/components/features/stat-card";
import { RelativeTime } from "@/components/features/time";
import { PreprocessJobResults } from "@/components/features/tool-job-results";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { analysisKindLabel, dataTypeLabel, jobKindLabel } from "@/i18n/zh-TW";
import { getJob, getJobLog } from "@/lib/api";
import { canCancelJob } from "@/lib/roles";
import { can, getCurrentUser } from "@/lib/session";
import type { AnalysisKind, DataType, PreprocessStep } from "@/types/domain";

/** Preprocessing / analysis jobs run in the shared tool pool, so they get their own page (no project tabs). */
async function ToolJobDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const job = await getJob(Number(id));
  if (!job || (job.kind !== "preprocess" && job.kind !== "analysis")) notFound();
  const [log, user] = await Promise.all([getJobLog(job.id), getCurrentUser()]);
  const controlsJobs = can(user, "jobs.control");
  // the creator acts as a member of their own tool job (the pool has no members)
  const canCancel = canCancelJob(
    job.createdBy.id === user.id ? "member" : controlsJobs ? "owner" : null,
    user,
    job.createdBy.id,
  );
  const steps = (job.input.spec?.preprocess ?? job.config?.steps ?? []) as PreprocessStep[];
  const analysisKind = job.config?.analysis as AnalysisKind | undefined;
  const dataType = (job.input.spec?.data_type ?? job.config?.data_type) as DataType | undefined;
  const back = job.kind === "analysis" ? "/tools/analyze" : "/tools/preprocess";

  const overview = (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        label={job.kind === "analysis" ? "分析類型" : "前處理步驟"}
        value={
          <span className="text-base">
            {job.kind === "analysis"
              ? analysisKind
                ? (analysisKindLabel[analysisKind] ?? analysisKind)
                : "—"
              : `${steps.length} 步`}
          </span>
        }
        hint="工具池任務；輸入檔於任務結束後刪除"
      />
      <StatCard
        label="資料類型"
        value={<span className="text-base">{dataType ? `${dataType} · ${dataTypeLabel[dataType]}` : "—"}</span>}
        hint={
          job.input.originalFilename ? (
            <span className="font-mono">{String(job.input.originalFilename)}</span>
          ) : undefined
        }
      />
      <StatCard
        label="CPU / 記憶體"
        value={`${job.requestedCpu} 核 · ${job.requestedMemoryMb} MB`}
        hint="由工具池配額決定"
      />
      <StatCard label="GPU" value={job.requestedGpu} hint={job.requestedGpu ? "共用工具池的 GPU" : "不需要 GPU"} />
    </div>
  );

  const results =
    job.kind === "preprocess" ? (
      <PreprocessJobResults job={job} />
    ) : job.result ? (
      <AnalysisReport result={job.result} job={job} />
    ) : (
      <Card>
        <CardContent className="text-sm text-muted-foreground">任務完成後會在這裡顯示分析報告。</CardContent>
      </Card>
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
          {steps.length ? (
            <ol className="space-y-1 text-sm">
              {steps.map((s, i) => (
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
            <p className="text-xs text-muted-foreground">沒有前處理步驟。</p>
          )}
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
            <Button variant="outline" size="sm" asChild>
              <Link href={back}>
                <ArrowLeft />
                回到工具
              </Link>
            </Button>
          </div>
        }
      />
      <JobStatusBar job={job} canCancel={canCancel} />
      <JobLive
        job={job}
        log={log}
        overview={overview}
        results={results}
        resultsLabel={job.kind === "analysis" ? "報告" : "結果"}
        config={config}
        defaultTab={job.status === "succeeded" || job.status === "failed" ? "results" : "overview"}
      />
    </>
  );
}

export default function ToolJobPage({ params }: PageProps<"/tools/jobs/[id]">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ToolJobDetail params={params} />
    </Suspense>
  );
}
