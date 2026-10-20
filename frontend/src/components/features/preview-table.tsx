"use client";

// The prediction rows of an inference result. With the job at hand a row opens the sample it came from: an
// inline row shows itself, an uploaded file is read from the browser's own copy (lib/local-data.ts).
import { useState } from "react";
import { SampleViewer, type SampleTarget } from "@/components/features/sample-viewer";
import { VerdictBadge, verdictTone } from "@/components/features/verdict-badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatMetric } from "@/lib/format";
import { withBase } from "@/lib/base-path";
import { jobKey } from "@/lib/local-data";
import { cn } from "@/lib/utils";
import type { Job } from "@/types/domain";

type Row = Record<string, unknown>;

export function cellText(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : formatMetric(v);
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "true" : "false";
  return JSON.stringify(v);
}

/** Build the viewer target for a result row; null when nothing local can back it (data source input). */
/** Overlay the trainer wrote for a row: `attention` (DINO families) or `map` (image-quality maps), a path under
 * the job's output/ folder, fetched through the download proxy. */
export function overlayFor(job: Job, row: Row): { overlayUrl?: string; overlayLabel?: string } {
  const rel = typeof row.attention === "string" ? row.attention : typeof row.map === "string" ? row.map : undefined;
  if (!rel || !/^[\w./-]+\.(png|jpe?g|webp)$/i.test(rel) || rel.includes("..")) return {};
  const encoded = rel.split("/").map(encodeURIComponent).join("/");
  return {
    overlayUrl: withBase(`/api/download/jobs/${job.id}/output/${encoded}`),
    overlayLabel: typeof row.attention === "string" ? "模型關注的區塊" : "偏離基準最多的區塊",
  };
}

export function sampleTargetFor(job: Job, row: Row, index: number): SampleTarget | null {
  const id = row.id === undefined || row.id === null ? String(index) : String(row.id);
  // the trainer numbers every prediction row in input order; the id may be an id-column value instead
  const ri = Number(row.row_index);
  const rowIndex = Number.isInteger(ri) && ri >= 0 ? ri : Number.isInteger(Number(id)) ? Number(id) : undefined;
  if (job.input.kind === "inline") {
    const rows = job.input.rows ?? [];
    const inlineRow = (rowIndex !== undefined ? rows[rowIndex] : undefined) ?? rows[index];
    return inlineRow ? { ref: { id }, inlineRow } : null;
  }
  if (job.input.kind !== "upload") return null;
  const idColumn = typeof job.input.spec.id_column === "string" ? job.input.spec.id_column : undefined;
  return { ref: { id, index: rowIndex, idColumn }, ...overlayFor(job, row) };
}

export function PreviewTable({ rows, columns, job }: { rows: Row[]; columns: string[]; job?: Job }) {
  const [target, setTarget] = useState<SampleTarget | null>(null);
  const clickable = Boolean(job && (job.input.kind === "inline" || job.input.kind === "upload"));
  const open = (row: Row, i: number) => {
    if (!job) return;
    const t = sampleTargetFor(job, row, i);
    if (t) setTarget(t);
  };
  return (
    <>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((c) => (
                <TableHead key={c} className="font-mono text-xs whitespace-nowrap">
                  {c}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r, i) => (
              <TableRow
                key={i}
                className={cn(clickable && "cursor-pointer")}
                onClick={clickable ? () => open(r, i) : undefined}
                tabIndex={clickable ? 0 : undefined}
                onKeyDown={clickable ? (e) => (e.key === "Enter" ? open(r, i) : undefined) : undefined}
                data-testid={clickable ? "result-row" : undefined}
              >
                {columns.map((c) => (
                  <TableCell
                    key={c}
                    className="max-w-56 truncate font-mono text-xs tabular-nums"
                    title={cellText(r[c])}
                  >
                    {typeof r[c] === "string" && verdictTone[r[c] as string] ? (
                      <VerdictBadge verdict={r[c] as string} />
                    ) : (
                      cellText(r[c])
                    )}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {clickable ? (
        <p className="px-4 py-2 text-[11px] text-muted-foreground">點一列查看那筆樣本（影像、曲線或欄位值）。</p>
      ) : null}
      {job ? (
        <SampleViewer
          open={target !== null}
          onOpenChange={(o) => (o ? undefined : setTarget(null))}
          dataKey={job.input.kind === "upload" ? jobKey(job.id) : undefined}
          target={target}
          fingerprint={{
            name: job.input.originalFilename,
            size: job.input.fingerprint?.sizeBytes ?? job.input.sizeBytes,
            sha256: job.input.fingerprint?.sha256,
          }}
        />
      ) : null}
    </>
  );
}
