"use client";

// Spreadsheet-like view of a preprocessing preview sample: sticky headers with per-column statistics and an
// operations menu, a windowed body (up to 500 rows), changed cells highlighted after a step ran.
import { Ellipsis, Lock } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formatCell, type CellKey } from "@/lib/preprocess-steps";
import { cn } from "@/lib/utils";
import type { PreprocessOp, PreviewColumnStat } from "@/types/domain";

const ROW_H = 28;
const OVERSCAN = 12;

const DTYPE_LABEL: Record<PreviewColumnStat["dtype"], string> = {
  number: "數值",
  text: "文字",
  bool: "布林",
  datetime: "日期",
};

export interface ColumnAction {
  op: PreprocessOp;
  /** Choice param that becomes a submenu (strategy / method …). */
  choice?: { name: string; label: string; values: unknown[] };
}

export function PreprocessGrid({
  columns,
  rows,
  stats,
  changed,
  protectedColumns,
  actions,
  dropOp,
  onColumnAction,
  loading,
  className,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  stats: Map<string, PreviewColumnStat>;
  changed: Set<CellKey>;
  protectedColumns: Set<string>;
  /** Column operations offered in every header menu (derived from the catalog). */
  actions: ColumnAction[];
  /** The 移除欄位 op, when the data type has one. */
  dropOp?: PreprocessOp;
  onColumnAction: (op: PreprocessOp, column: string, extra?: Record<string, unknown>) => void;
  loading?: boolean;
  className?: string;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(480);
  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const end = Math.min(rows.length, Math.ceil((scrollTop + height) / ROW_H) + OVERSCAN);
  const visible = rows.slice(start, end);

  return (
    <div className={cn("relative min-w-0 rounded-lg border border-border bg-card", className)}>
      {loading ? (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center bg-background/60 text-sm text-muted-foreground backdrop-blur-[1px]"
          role="status"
        >
          預覽計算中…
        </div>
      ) : null}
      <div
        ref={(el) => {
          viewport.current = el;
          if (el && el.clientHeight && el.clientHeight !== height) setHeight(el.clientHeight);
        }}
        className="h-full max-h-[inherit] overflow-auto"
        onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
        data-testid="preprocess-grid"
      >
        <table className="w-max min-w-full border-separate border-spacing-0 text-xs">
          <thead className="sticky top-0 z-10 bg-muted">
            <tr>
              <th className="sticky left-0 z-10 w-12 border-r border-b border-border bg-muted px-2 py-1 text-right font-mono text-[11px] text-muted-foreground tabular-nums">
                #
              </th>
              {columns.map((c) => {
                const st = stats.get(c);
                const locked = protectedColumns.has(c);
                const missingPct = st ? Math.round(st.missing_ratio * 1000) / 10 : 0;
                return (
                  <th
                    key={c}
                    scope="col"
                    className="min-w-36 border-r border-b border-border px-2 py-1.5 text-left align-top font-normal"
                  >
                    <div className="flex items-start justify-between gap-1">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1">
                          <span className="truncate text-sm font-medium" title={c}>
                            {c}
                          </span>
                          {locked ? (
                            <Lock className="size-3 shrink-0 text-muted-foreground" aria-label="受保護" />
                          ) : null}
                        </div>
                        {st ? (
                          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 font-mono text-[11px] tabular-nums">
                            <span className="rounded-sm bg-background px-1 text-muted-foreground">
                              {DTYPE_LABEL[st.dtype]}
                            </span>
                            <span className={cn(missingPct > 0 ? "text-warning" : "text-muted-foreground")}>
                              缺 {missingPct}%
                            </span>
                            <span className="text-muted-foreground">{st.unique} 種</span>
                          </div>
                        ) : null}
                      </div>
                      <ColumnMenu
                        column={c}
                        locked={locked}
                        actions={actions}
                        dropOp={dropOp}
                        stat={st}
                        onColumnAction={onColumnAction}
                      />
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {start > 0 ? (
              <tr aria-hidden>
                <td colSpan={columns.length + 1} style={{ height: start * ROW_H }} />
              </tr>
            ) : null}
            {visible.map((r, k) => {
              const i = start + k;
              return (
                <tr key={i} style={{ height: ROW_H }} className="hover:bg-accent/40">
                  <td className="sticky left-0 border-r border-b border-border/60 bg-card px-2 text-right text-[11px] text-subtle-foreground">
                    {i + 1}
                  </td>
                  {columns.map((c) => {
                    const v = r[c];
                    const missing = v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));
                    const diff = changed.has(`${i}:${c}`);
                    return (
                      <td
                        key={c}
                        className={cn(
                          "max-w-64 truncate border-r border-b border-border/60 px-2",
                          typeof v === "number" ? "text-right" : "text-left",
                          diff && "bg-primary/10",
                          missing && "text-subtle-foreground",
                        )}
                        title={missing ? "缺值" : formatCell(v)}
                      >
                        {missing ? "—" : formatCell(v)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {end < rows.length ? (
              <tr aria-hidden>
                <td colSpan={columns.length + 1} style={{ height: (rows.length - end) * ROW_H }} />
              </tr>
            ) : null}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length + 1} className="px-3 py-6 text-center font-sans text-muted-foreground">
                  沒有列可以顯示
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ColumnMenu({
  column,
  locked,
  actions,
  dropOp,
  stat,
  onColumnAction,
}: {
  column: string;
  locked: boolean;
  actions: ColumnAction[];
  dropOp?: PreprocessOp;
  stat?: PreviewColumnStat;
  onColumnAction: (op: PreprocessOp, column: string, extra?: Record<string, unknown>) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" className="shrink-0" aria-label={`${column} 的操作`}>
          <Ellipsis />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="truncate font-mono text-xs">{column}</DropdownMenuLabel>
        {stat?.top?.length ? (
          <div className="px-2 pb-1 text-[11px] text-muted-foreground">
            常見值：{stat.top.map((t) => `${t.value}（${t.count}）`).join("、")}
          </div>
        ) : null}
        <DropdownMenuSeparator />
        {locked ? (
          <div className="px-2 py-1.5 text-xs text-muted-foreground">目標 / ID 欄位受保護，不會被處理。</div>
        ) : (
          actions.map((a) =>
            a.choice ? (
              <DropdownMenuSub key={a.op.id}>
                <DropdownMenuSubTrigger>{a.op.label}</DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  {a.choice.values.map((v) => (
                    <DropdownMenuItem
                      key={String(v)}
                      onSelect={() => onColumnAction(a.op, column, { [a.choice!.name]: v })}
                    >
                      <span className="font-mono text-xs">{String(v)}</span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            ) : (
              <DropdownMenuItem key={a.op.id} onSelect={() => onColumnAction(a.op, column)}>
                {a.op.label}
              </DropdownMenuItem>
            ),
          )
        )}
        {dropOp && !locked ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onSelect={() => onColumnAction(dropOp, column)}>
              {dropOp.label}
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
