"use client";

// shadcn table with two additions every list in the app gets for free: a 「展開內容」toggle that lets
// truncated cells wrap (long names, paths, file names), and drag handles on the header cells to resize columns.
import * as React from "react";
import { WrapText } from "lucide-react";
import { cn } from "@/lib/utils";

function Table({ className, children, ...props }: React.ComponentProps<"table">) {
  const [wrap, setWrap] = React.useState(false);
  return (
    <div
      data-slot="table-container"
      data-wrap={wrap || undefined}
      className="group/table relative w-full overflow-x-auto"
    >
      <table data-slot="table" className={cn("w-full caption-bottom text-sm", className)} {...props}>
        {children}
      </table>
      <button
        type="button"
        aria-pressed={wrap}
        aria-label={wrap ? "恢復單行顯示" : "展開內容（換行顯示被截斷的文字）"}
        title={wrap ? "恢復單行顯示" : "展開內容"}
        onClick={() => setWrap((w) => !w)}
        className={cn(
          "absolute top-1.5 right-1.5 z-10 inline-flex size-6 items-center justify-center rounded-md border border-border bg-card/90 text-muted-foreground shadow-xs backdrop-blur transition-opacity hover:text-foreground focus-visible:opacity-100 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
          wrap ? "text-brand-ink opacity-100" : "opacity-0 group-hover/table:opacity-100",
        )}
        data-testid="table-wrap-toggle"
      >
        <WrapText className="size-3.5" />
      </button>
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return <thead data-slot="table-header" className={cn("[&_tr]:border-b", className)} {...props} />;
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return <tbody data-slot="table-body" className={cn("[&_tr:last-child]:border-0", className)} {...props} />;
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn("border-t bg-muted/50 font-medium [&>tr]:last:border-b-0", className)}
      {...props}
    />
  );
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b transition-colors hover:bg-muted/50 has-aria-expanded:bg-muted/50 data-[state=selected]:bg-muted",
        className,
      )}
      {...props}
    />
  );
}

const MIN_COLUMN_PX = 48;

/** Header cell with a drag handle on its right edge: dragging sets the column width (auto layout keeps it as a minimum). */
function TableHead({ className, children, style, ...props }: React.ComponentProps<"th">) {
  const ref = React.useRef<HTMLTableCellElement>(null);
  const [width, setWidth] = React.useState<number | undefined>(undefined);
  const onPointerDown = (e: React.PointerEvent<HTMLSpanElement>) => {
    const th = ref.current;
    if (!th) return;
    e.preventDefault();
    e.stopPropagation();
    const startX = e.clientX;
    const startW = th.getBoundingClientRect().width;
    const move = (ev: PointerEvent) => setWidth(Math.max(MIN_COLUMN_PX, Math.round(startW + ev.clientX - startX)));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <th
      ref={ref}
      data-slot="table-head"
      style={width === undefined ? style : { ...style, width, minWidth: width, maxWidth: width }}
      className={cn(
        "relative h-10 px-2 text-left align-middle font-medium whitespace-nowrap text-foreground [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        className,
      )}
      {...props}
    >
      {children}
      <span
        role="separator"
        aria-orientation="vertical"
        aria-label="拖曳調整欄寬"
        title="拖曳調整欄寬；雙擊恢復"
        onPointerDown={onPointerDown}
        onDoubleClick={() => setWidth(undefined)}
        className="absolute top-0 right-0 h-full w-2 cursor-col-resize touch-none opacity-0 transition-opacity select-none group-hover/table:opacity-100 after:absolute after:top-2 after:bottom-2 after:left-[3px] after:w-px after:bg-border-strong hover:after:bg-primary"
      />
    </th>
  );
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "p-2 align-middle whitespace-nowrap [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        className,
      )}
      {...props}
    />
  );
}

function TableCaption({ className, ...props }: React.ComponentProps<"caption">) {
  return (
    <caption data-slot="table-caption" className={cn("mt-4 text-sm text-muted-foreground", className)} {...props} />
  );
}

export { Table, TableHeader, TableBody, TableFooter, TableHead, TableRow, TableCell, TableCaption };
