import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Tone = "default" | "success" | "warning" | "destructive" | "signal";
const valueTone: Record<Tone, string> = {
  default: "text-foreground",
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
  signal: "text-signal",
};

export function StatCard({
  label,
  value,
  unit,
  hint,
  icon: Icon,
  tone = "default",
  className,
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  hint?: React.ReactNode;
  icon?: LucideIcon;
  tone?: Tone;
  className?: string;
}) {
  return (
    <Card className={cn("gap-2 p-5", className)}>
      <div className="flex items-center justify-between">
        <span className="text-label">{label}</span>
        {Icon ? <Icon className="size-5 text-muted-foreground" /> : null}
      </div>
      <div className={cn("font-mono text-3xl font-semibold tracking-tight tabular-nums", valueTone[tone])}>
        {value}
        {unit ? <span className="ml-1 text-base font-normal text-muted-foreground">{unit}</span> : null}
      </div>
      {hint ? <div className="text-xs text-muted-foreground">{hint}</div> : null}
    </Card>
  );
}
