import { cn } from "@/lib/utils";
import { issueStatusLabel, jobStatusLabel, projectStatusLabel, requestStatusLabel } from "@/i18n/zh-TW";
import type { IssueStatus, JobStatus, ProjectStatus, RequestStatus } from "@/types/domain";

export type AnyStatus = JobStatus | RequestStatus | IssueStatus | ProjectStatus | "pending" | "purged" | "ok" | "error";
type Tone = "muted" | "info" | "primary" | "success" | "warning" | "destructive";

/** DESIGN.md §2.5 — the only mapping from status to color. */
const toneOf: Record<AnyStatus, Tone> = {
  queued: "muted",
  cancelled: "muted",
  closed: "muted",
  archived: "muted",
  withdrawn: "muted",
  purged: "muted",
  scheduled: "info",
  open: "info",
  submitted: "info",
  pending: "info",
  running: "primary",
  succeeded: "success",
  approved: "success",
  active: "success",
  ok: "success",
  failed: "destructive",
  rejected: "destructive",
  error: "destructive",
  in_review: "warning",
};

const labelOf: Record<AnyStatus, string> = {
  ...jobStatusLabel,
  ...requestStatusLabel,
  ...issueStatusLabel,
  ...projectStatusLabel,
  pending: "待處理",
  purged: "已清除",
  ok: "正常",
  error: "異常",
};

const toneClasses: Record<Tone, { badge: string; dot: string }> = {
  muted: { badge: "border-border bg-muted text-muted-foreground", dot: "bg-muted-foreground" },
  info: { badge: "border-info/30 bg-info/10 text-info", dot: "bg-info" },
  primary: { badge: "border-primary/30 bg-primary/10 text-brand-ink", dot: "bg-primary" },
  success: { badge: "border-success/30 bg-success/10 text-success", dot: "bg-success" },
  warning: { badge: "border-warning/30 bg-warning/10 text-warning", dot: "bg-warning" },
  destructive: { badge: "border-destructive/30 bg-destructive/10 text-destructive", dot: "bg-destructive" },
};

export function StatusBadge({ status, label, className }: { status: AnyStatus; label?: string; className?: string }) {
  const tone = toneOf[status];
  const t = toneClasses[tone];
  return (
    <span
      title={status}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        t.badge,
        className,
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          t.dot,
          status === "running" && "animate-pulse-dot motion-reduce:animate-none",
        )}
      />
      {label ?? labelOf[status]}
    </span>
  );
}
