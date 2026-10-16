"use client";

// Live job feed shared by the project job page (JobLive) and the admin queue drawer (JobLogLive): one
// EventSource per mounted consumer, proxied through /api/stream/jobs/{id}.
//   - opens with `?last_event_id=` (the cursor from GET /jobs/{id}/logs, or the last event seen) so the backend
//     does not replay lines the snapshot already contains;
//   - on error: closes, shows "reconnecting", retries with exponential backoff (1 s → 30 s) and meanwhile polls
//     router.refresh() every 10 s so the server-rendered parts still move;
//   - status / metric / end events trigger a throttled router.refresh() so metrics, leaderboard and artifacts
//     catch up without a manual reload;
//   - keeps at most MAX_LOG_LINES lines in memory (older ones are in the downloadable log file);
//   - stops everything on a terminal status (`end` event or server prop) and on unmount.
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { Job, JobLogSnapshot, JobStage, JobStatus, LogLine } from "@/types/domain";

export const ACTIVE_STATUSES: readonly JobStatus[] = ["queued", "scheduled", "running"];
export const MAX_LOG_LINES = 5000;
const REFRESH_MS = 1500;
const POLL_MS = 10_000;
const BACKOFF_MIN_MS = 1000;
const BACKOFF_MAX_MS = 30_000;

export type StreamConnection = "idle" | "live" | "reconnecting";

export interface LiveState {
  status: JobStatus;
  progress: number;
  stage?: JobStage;
  message?: string;
  metrics: Record<string, number>;
}

interface Buffer {
  lines: LogLine[];
  /** Lines evicted from the front of `lines` to stay under MAX_LOG_LINES. */
  dropped: number;
}

export function liveFromJob(job: Job): LiveState {
  const metrics: Record<string, number> = {};
  for (const [k, v] of Object.entries(job.metrics ?? {})) if (typeof v === "number") metrics[k] = v;
  return { status: job.status, progress: job.progress, stage: job.currentStage, metrics };
}

function parse(e: MessageEvent): Record<string, unknown> {
  try {
    return JSON.parse(e.data) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function append(buf: Buffer, line: Omit<LogLine, "n">): Buffer {
  const n = (buf.lines[buf.lines.length - 1]?.n ?? 0) + 1;
  const lines = [...buf.lines, { ...line, n }];
  if (lines.length <= MAX_LOG_LINES) return { lines, dropped: buf.dropped };
  const overflow = lines.length - MAX_LOG_LINES;
  return { lines: lines.slice(overflow), dropped: buf.dropped + overflow };
}

export function useJobStream(job: Job, snapshot: JobLogSnapshot) {
  const router = useRouter();
  const [buf, setBuf] = useState<Buffer>({ lines: snapshot.lines, dropped: 0 });
  const [live, setLive] = useState(() => liveFromJob(job));
  const [connection, setConnection] = useState<StreamConnection>("idle");
  // Server props change after router.refresh(): adopt the authoritative snapshot (derived state).
  const [prev, setPrev] = useState({ job, snapshot });
  if (prev.job !== job || prev.snapshot !== snapshot) {
    setPrev({ job, snapshot });
    setBuf({ lines: snapshot.lines, dropped: 0 });
    setLive(liveFromJob(job));
  }
  // SSE cursor: the snapshot's id until the stream has delivered its first event, then the last event seen.
  const cursor = useRef<string | undefined>(undefined);
  const seenEvent = useRef(false);
  const snapshotCursor = snapshot.lastEventId;
  useEffect(() => {
    if (!seenEvent.current && snapshotCursor) cursor.current = snapshotCursor;
  }, [snapshotCursor]);
  const active = ACTIVE_STATUSES.includes(job.status);

  useEffect(() => {
    if (!active) return;
    let es: EventSource | null = null;
    let stopped = false;
    let attempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    const scheduleRefresh = () => {
      if (refreshTimer || stopped) return;
      refreshTimer = setTimeout(() => {
        refreshTimer = null;
        router.refresh();
      }, REFRESH_MS);
    };
    const stopPolling = () => {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
    };
    const startPolling = () => {
      if (pollTimer) return;
      pollTimer = setInterval(() => router.refresh(), POLL_MS);
    };
    const stopAll = () => {
      stopped = true;
      es?.close();
      es = null;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (refreshTimer) clearTimeout(refreshTimer);
      reconnectTimer = null;
      refreshTimer = null;
      stopPolling();
    };

    const connect = () => {
      if (stopped) return;
      const qs = cursor.current ? `?last_event_id=${encodeURIComponent(cursor.current)}` : "";
      const source = new EventSource(`/api/stream/jobs/${job.id}${qs}`);
      es = source;
      source.onopen = () => {
        attempt = 0;
        setConnection("live");
        stopPolling();
      };
      source.onerror = () => {
        source.close();
        if (es === source) es = null;
        if (stopped) return;
        setConnection("reconnecting");
        startPolling();
        const delay = Math.min(BACKOFF_MAX_MS, BACKOFF_MIN_MS * 2 ** attempt);
        attempt += 1;
        reconnectTimer = setTimeout(connect, delay);
      };
      const on = (type: string, fn: (d: Record<string, unknown>) => void) =>
        source.addEventListener(type, (e) => {
          const me = e as MessageEvent;
          if (me.lastEventId) {
            cursor.current = me.lastEventId;
            seenEvent.current = true;
          }
          fn(parse(me));
        });
      on("log", (d) => {
        const level = String(d.level ?? "INFO").toUpperCase();
        setBuf((b) =>
          append(b, {
            ts: new Date().toISOString(),
            level: (level === "WARNING" ? "WARN" : level) as LogLine["level"],
            text: String(d.text ?? ""),
          }),
        );
      });
      on("status", (d) => {
        setLive((s) => ({ ...s, status: (d.status as JobStatus) ?? s.status }));
        scheduleRefresh();
      });
      on("progress", (d) => {
        setLive((s) => ({
          ...s,
          progress: typeof d.progress === "number" ? Math.round(d.progress) : s.progress,
          stage: (d.stage as JobStage | undefined) ?? s.stage,
          message: typeof d.message === "string" ? d.message : s.message,
          status: d.status === "running" ? "running" : s.status,
        }));
      });
      on("metric", (d) => {
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
      on("end", (d) => {
        setLive((s) => ({ ...s, status: (d.status as JobStatus) ?? s.status }));
        setConnection("idle");
        stopAll();
        router.refresh();
      });
    };

    connect();
    return stopAll;
  }, [active, job.id, router]);

  return { lines: buf.lines, dropped: buf.dropped, live, connection: active ? connection : "idle", active };
}
