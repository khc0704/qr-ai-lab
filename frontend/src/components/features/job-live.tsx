"use client";

// Live job views built on useJobStream (one EventSource per mounted view, proxied through /api/stream/jobs/{id}):
//   - JobLive: the project job page (progress card + tabs: overview / log / results / config);
//   - JobLogLive: just the live LogViewer, used by the admin queue drawer so both share the same stream path.
import { LogViewer } from "@/components/features/log-viewer";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useJobStream } from "@/hooks/use-job-stream";
import { jobStageLabel } from "@/i18n/zh-TW";
import { formatMetric } from "@/lib/format";
import type { Job, JobLogSnapshot } from "@/types/domain";

export function JobLive({
  job,
  log,
  overview,
  results,
  resultsLabel,
  config,
  defaultTab = "overview",
}: {
  job: Job;
  log: JobLogSnapshot;
  overview: React.ReactNode;
  results: React.ReactNode;
  resultsLabel: string;
  config: React.ReactNode;
  defaultTab?: string;
}) {
  const { lines, dropped, live, connection } = useJobStream(job, log);
  const search = job.config?.search as { max_trials?: number } | undefined;
  const best = Object.entries(live.metrics).filter(([k]) => k.startsWith("best_"));
  const running = live.status === "running" || live.status === "scheduled";

  return (
    <Tabs defaultValue={defaultTab}>
      <TabsList>
        <TabsTrigger value="overview">概況</TabsTrigger>
        <TabsTrigger value="log">Log</TabsTrigger>
        <TabsTrigger value="results">{resultsLabel}</TabsTrigger>
        <TabsTrigger value="config">設定</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className="space-y-6 pt-4">
        {running ? (
          <Card className="gap-3 p-5" data-testid="live-progress">
            <div className="flex items-center justify-between">
              <span className="text-label">{live.stage ? jobStageLabel[live.stage] : "進度"}</span>
              <span className="font-mono text-sm tabular-nums">{live.progress}%</span>
            </div>
            <Progress value={live.progress} />
            <p className="text-xs text-muted-foreground">
              {live.message ? <span className="font-mono">{live.message}</span> : null}
              {search ? (
                <span className={live.message ? "ml-2" : undefined}>
                  AutoML：trial {live.metrics.trial ?? "—"} / {search.max_trials ?? "—"}，目前最佳{" "}
                  {best.map(([k, v]) => `${k.replace("best_", "")}=${formatMetric(v)}`).join(" ") || "—"}
                </span>
              ) : null}
              {live.metrics.epoch !== undefined && !search ? (
                <span className={live.message ? "ml-2" : undefined}>epoch {live.metrics.epoch}</span>
              ) : null}
            </p>
          </Card>
        ) : null}
        {overview}
      </TabsContent>
      <TabsContent value="log" className="pt-4">
        <LogViewer
          lines={lines}
          dropped={dropped}
          connection={connection}
          status={live.status}
          title="job.log"
          maxHeight="max-h-[640px]"
          downloadHref={`/api/download/jobs/${job.id}/logs/download`}
        />
      </TabsContent>
      <TabsContent value="results" className="pt-4">
        {results}
      </TabsContent>
      <TabsContent value="config" className="pt-4">
        {config}
      </TabsContent>
    </Tabs>
  );
}

/** Live log only (admin queue drawer). Mount it while the drawer is open; the stream closes on unmount. */
export function JobLogLive({ job, log, maxHeight }: { job: Job; log: JobLogSnapshot; maxHeight?: string }) {
  const { lines, dropped, live, connection } = useJobStream(job, log);
  return (
    <LogViewer
      lines={lines}
      dropped={dropped}
      connection={connection}
      status={live.status}
      title="job.log"
      maxHeight={maxHeight}
      downloadHref={`/api/download/jobs/${job.id}/logs/download`}
    />
  );
}
