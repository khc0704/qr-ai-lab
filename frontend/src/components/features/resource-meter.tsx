import { cn } from "@/lib/utils";

export function ResourceMeter({
  label,
  used,
  total,
  format = (n) => String(n),
  unit,
  className,
  compact = false,
}: {
  label: string;
  used: number;
  total: number;
  format?: (n: number) => string;
  unit?: string;
  className?: string;
  compact?: boolean;
}) {
  const ratio = total > 0 ? Math.min(1, used / total) : 0;
  const pct = ratio * 100;
  const fill = pct >= 90 ? "bg-destructive" : pct >= 70 ? "bg-warning" : "bg-primary";
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className={cn("text-label", compact && "text-[10px]")}>{label}</span>
        {total > 0 ? (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {format(used)} / {format(total)}
            {unit ? ` ${unit}` : ""}
          </span>
        ) : (
          <span className="text-xs text-subtle-foreground">未配置</span>
        )}
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        aria-label={label}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-500 ease-out motion-reduce:transition-none",
            fill,
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
