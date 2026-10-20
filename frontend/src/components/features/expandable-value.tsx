"use client";

// A single value in a key / value list (result summary, sample fields): truncated to one line, with a toggle that
// shows the whole thing when it was cut off. Tables get the same behaviour from TableCell.
import { ChevronsLeftRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export function ExpandableValue({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [overflowing, setOverflowing] = useState(false);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      if (!el.dataset.expanded) setOverflowing(el.scrollWidth > el.clientWidth + 1);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const show = overflowing || expanded;
  return (
    <span className={cn("flex min-w-0 items-start justify-end gap-1", className)}>
      <span
        ref={ref}
        data-expanded={expanded || undefined}
        className={cn("min-w-0", expanded ? "break-all whitespace-pre-wrap" : "truncate")}
        title={expanded ? undefined : text}
      >
        {text}
      </span>
      {show ? (
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={expanded ? "收合" : "展開完整內容"}
          title={expanded ? "收合" : "展開完整內容"}
          onClick={() => setExpanded((x) => !x)}
          className={cn(
            "inline-flex size-5 shrink-0 items-center justify-center rounded border border-border bg-card text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
            expanded && "text-brand-ink",
          )}
          data-testid="value-expand"
        >
          <ChevronsLeftRight className="size-3" />
        </button>
      ) : null}
    </span>
  );
}
