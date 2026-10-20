// Verdict pill shared by the server-rendered result summary and the client-side prediction table.
import { CheckCircle2, CircleAlert, CircleX } from "lucide-react";
import { cn } from "@/lib/utils";

export const verdictTone: Record<string, { className: string; icon: typeof CheckCircle2; label: string }> = {
  match: { className: "bg-success/10 text-success border-success/30", icon: CheckCircle2, label: "一致" },
  pass: { className: "bg-success/10 text-success border-success/30", icon: CheckCircle2, label: "通過" },
  drift: { className: "bg-warning/10 text-warning border-warning/30", icon: CircleAlert, label: "漂移" },
  fail: { className: "bg-destructive/10 text-destructive border-destructive/30", icon: CircleX, label: "不一致" },
  normal: { className: "bg-success/10 text-success border-success/30", icon: CheckCircle2, label: "正常" },
  anomaly: { className: "bg-destructive/10 text-destructive border-destructive/30", icon: CircleX, label: "異常" },
};

export function VerdictBadge({ verdict }: { verdict: string }) {
  const t = verdictTone[verdict];
  if (!t) return <span className="font-mono text-xs">{verdict}</span>;
  const Icon = t.icon;
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", t.className)}
    >
      <Icon className="size-3.5" />
      {t.label}
      <span className="font-mono opacity-70">{verdict}</span>
    </span>
  );
}
