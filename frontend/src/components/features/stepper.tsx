import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Horizontal step indicator. `current` is clamped into range (a stale index after a step list shrinks shows
 * the last step instead of nothing). With `onSelect`, completed steps become buttons that jump back.
 */
export function Stepper({
  steps,
  current,
  onSelect,
}: {
  steps: string[];
  current: number;
  onSelect?: (index: number) => void;
}) {
  const cur = Math.min(Math.max(0, current), Math.max(0, steps.length - 1));
  return (
    <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-2" aria-label="步驟">
      {steps.map((s, i) => {
        const done = i < cur;
        const active = i === cur;
        const clickable = done && Boolean(onSelect);
        const Tag = clickable ? "button" : "div";
        return (
          <li key={`${i}-${s}`} className="flex items-center gap-1.5">
            <Tag
              type={clickable ? "button" : undefined}
              onClick={clickable ? () => onSelect?.(i) : undefined}
              aria-current={active ? "step" : undefined}
              aria-label={clickable ? `回到步驟 ${i + 1}：${s}` : undefined}
              className={cn(
                "flex items-center gap-1.5 rounded-md outline-none",
                clickable && "cursor-pointer hover:opacity-80 focus-visible:ring-[3px] focus-visible:ring-ring/50",
              )}
            >
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
              {/* on narrow screens only the current step keeps its label; the others are the numbered dots */}
              <span
                className={cn(
                  "text-sm whitespace-nowrap",
                  active ? "font-medium text-foreground" : "hidden text-muted-foreground sm:inline",
                )}
              >
                {s}
              </span>
            </Tag>
            {i < steps.length - 1 ? (
              <span className={cn("mx-0.5 h-px w-3 sm:w-5", done ? "bg-primary" : "bg-border")} />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
