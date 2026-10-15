import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex items-center gap-2 overflow-x-auto">
      {steps.map((s, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={s} className="flex shrink-0 items-center gap-2">
            <span
              className={cn(
                "flex size-6 items-center justify-center rounded-full border font-mono text-[11px] tabular-nums",
                done && "border-primary bg-primary text-primary-foreground",
                active && "border-primary text-brand-ink",
                !done && !active && "border-border text-subtle-foreground",
              )}
            >
              {done ? <Check className="size-3.5" /> : i + 1}
            </span>
            <span className={cn("text-sm", active ? "font-medium text-foreground" : "text-muted-foreground")}>{s}</span>
            {i < steps.length - 1 ? <span className={cn("mx-1 h-px w-8", done ? "bg-primary" : "bg-border")} /> : null}
          </li>
        );
      })}
    </ol>
  );
}
