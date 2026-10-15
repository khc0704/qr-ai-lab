"use client";

// Live job view: one EventSource per page (proxied through /api/stream/jobs/{id}) feeds the progress
// card and the log viewer; status / metric / end events trigger a throttled router.refresh() so the
// server-rendered tabs (metrics, leaderboard, artifacts, results) catch up without a manual reload.
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { LogViewer } from "@/components/features/log-viewer";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { jobStageLabel } from "@/i18n/zh-TW";
import { formatMetric } from "@/lib/format";
import type { Job, JobStage, JobStatus, LogLine } from "@/types/domain";

const ACTIVE: JobStatus[] = ["queued", "scheduled", "running"];
const REFRESH_MS = 1500;

interface LiveState {
  status: JobStatus;
  progress: number;
  stage?: JobStage;
  message?: string;
  metrics: Record<string, number>;
}

function fromJob(job: Job): LiveState {
  const metrics: Record<string, number> = {};
  for (const [k, v] of Object.entries(job.metrics ?? {})) if (typeof v === "number") metrics[k] = v;
  return { status: job.status, progress: job.progress, stage: job.currentStage, metrics };
}

export function JobLive({
  job,
  initialLines,
  overview,
  results,
  resultsLabel,
  config,
  defaultTab = "overview",
}: {
  job: Job;
  initialLines: LogLine[];
  overview: React.ReactNode;
  results: React.ReactNode;
  resultsLabel: string;
  config: React.ReactNode;
  defaultTab?: string;
}) {
  const router = useRouter();
  const [lines, setLines] = useState(initialLines);
  const [live, setLive] = useState(() => fromJob(job));
  // Server props change after router.refresh(): adopt the authoritative snapshot (derived state).
  const [prev, setPrev] = useState({ job, initialLines });
  if (prev.job !== job || prev.initialLines !== initialLines) {
    setPrev({ job, initialLines });
    setLines(initialLines);
    setLive(fromJob(job));
  }
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const active = ACTIVE.includes(job.status);

  useEffect(() => {
    if (!active) return;
    const es = new EventSource(`/api/stream/jobs/${job.id}`);
    const scheduleRefresh = () => {
      if (refreshTimer.current) return;
      refreshTimer.current = setTimeout(() => {
        refreshTimer.current = null;
        router.refresh();
      }, REFRESH_MS);
    };
    const parse = (e: MessageEvent) => {
      try {
        return JSON.parse(e.data) as Record<string, unknown>;
      } catch {
        return {};
      }
    };
    es.addEventListener("log", (e) => {
      const d = parse(e as MessageEvent);
      const level = String(d.level ?? "INFO").toUpperCase();
      setLines((ls) => [
        ...ls,
        {
          n: (ls[ls.length - 1]?.n ?? 0) + 1,
          ts: new Date().toISOString(),
          level: (level === "WARNING" ? "WARN" : level) as LogLine["level"],
          text: String(d.text ?? ""),
        },
      ]);
    });
    es.addEventListener("status", (e) => {
      const d = parse(e as MessageEvent);
      setLive((s) => ({ ...s, status: (d.status as JobStatus) ?? s.status }));
      scheduleRefresh();
    });
    es.addEventListener("progress", (e) => {
      const d = parse(e as MessageEvent);
      setLive((s) => ({
        ...s,
        progress: typeof d.progress === "number" ? Math.round(d.progress) : s.progress,
        stage: (d.stage as JobStage | undefined) ?? s.stage,
        message: typeof d.message === "string" ? d.message : s.message,
        status: d.status === "running" ? "running" : s.status,
      }));
    });
    es.addEventListener("metric", (e) => {
      const d = parse(e as MessageEvent);
      const m = (d.metrics as Record<string, number> | undefined) ?? {};
      setLive((s) => ({
        ...s,
        metrics: {
          ...s.metrics,
          ...m,
          ...(typeof d.trial === "number" ? { trial: d.trial } : {}),
          ...(typeof d.epoch === "number" ? { epoch: d.epoch } : {}),
        },
      }));
      scheduleRefresh();
    });
    es.addEventListener("end", (e) => {
      const d = parse(e as MessageEvent);
      setLive((s) => ({ ...s, status: (d.status as JobStatus) ?? s.status }));
      es.close();
      scheduleRefresh();
    });
    return () => {
      es.close();
      if (refreshTimer.current) {
        clearTimeout(refreshTimer.current);
        refreshTimer.current = null;
      }
    };
  }, [active, job.id, router]);

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
