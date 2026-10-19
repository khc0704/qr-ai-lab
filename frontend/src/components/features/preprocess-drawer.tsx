"use client";

// Full-width drawer that hosts the preprocessing workbench, plus the compact summary card that opens it.
import { Check, SlidersHorizontal, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { describeParams } from "@/lib/preprocess-steps";
import type { PreprocessOp, PreprocessStep, PreviewPayload } from "@/types/domain";

export function PreprocessDrawer({
  open,
  onOpenChange,
  title = "資料前處理",
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="flex h-[94vh] max-h-[94vh] flex-col gap-0 p-0 sm:max-w-none">
        <SheetHeader className="border-b border-border px-6 py-3">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>
            {description ??
              "按欄位標頭的 ⋯ 對單一欄位操作；列 / 整表的操作在上方；每次變動都會重新抽樣預覽，變動的格子會標色。"}
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-auto px-6 py-4">{children}</div>
        <SheetFooter className="flex-row items-center justify-end gap-2 border-t border-border px-6 py-3">
          <Button type="button" onClick={() => onOpenChange(false)} data-testid="editor-done">
            <Check />
            完成
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

/** What the page shows while the drawer is closed: the step chain, the last preview's numbers, one button. */
export function PreprocessSummary({
  ops,
  steps,
  preview,
  onOpen,
  disabled,
  hint,
}: {
  ops: PreprocessOp[];
  steps: PreprocessStep[];
  preview: PreviewPayload | null;
  onOpen: () => void;
  disabled?: boolean;
  hint?: string;
}) {
  const byId = Object.fromEntries(ops.map((o) => [o.id, o]));
  const warnings = preview?.warnings?.length ?? 0;
  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-sm">
          <span className="font-medium">{steps.length} 個步驟</span>
          {preview?.rows_in != null && preview?.rows_out != null ? (
            <span className="ml-2 font-mono text-xs text-muted-foreground tabular-nums">
              預覽：{preview.rows_in} → {preview.rows_out} 列
              {preview.columns_in && preview.columns_out
                ? `，${preview.columns_in.length} → ${preview.columns_out.length} 欄`
                : ""}
            </span>
          ) : null}
          {warnings ? (
            <span className="ml-2 inline-flex items-center gap-1 text-xs text-warning">
              <TriangleAlert className="size-3.5" />
              {warnings} 個警告
            </span>
          ) : null}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={onOpen}
          disabled={disabled}
          data-testid="open-editor"
        >
          <SlidersHorizontal />
          開啟編輯器
        </Button>
      </div>
      {steps.length ? (
        <ol className="flex flex-wrap gap-1.5">
          {steps.map((s, i) => (
            <li
              key={`${s.op}-${i}`}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs"
            >
              <span className="font-mono text-[11px] text-brand-ink">{i + 1}</span>
              <span>{byId[s.op]?.label ?? s.op}</span>
              {describeParams(s.params) ? (
                <span className="max-w-48 truncate font-mono text-[11px] text-muted-foreground">
                  {describeParams(s.params)}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-xs text-muted-foreground">{hint ?? "尚未加入步驟（可選）。"}</p>
      )}
    </div>
  );
}
