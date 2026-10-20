// Server-rendered inference results: summary stats, the IQA "compare" verdict table, and the first
// rows of predictions. Everything else is in the downloadable CSV / JSONL.
import { PreviewTable } from "@/components/features/preview-table";
import { VerdictBadge } from "@/components/features/verdict-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { jobCopy } from "@/i18n/zh-TW";
import { formatMetric } from "@/lib/format";
import type { Job } from "@/types/domain";

type Row = Record<string, unknown>;

const HIDDEN = new Set([
  "mode",
  "model_artifact_id",
  "preview",
  "preview_truncated",
  "artifacts",
  "per_metric",
  "stopped",
]);

function cell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : formatMetric(v);
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "true" : "false";
  return JSON.stringify(v);
}

export function JobResults({ result, job }: { result: Record<string, unknown>; job?: Job }) {
  const summary = Object.entries(result).filter(([k]) => !HIDDEN.has(k));
  const perMetric = Array.isArray(result.per_metric) ? (result.per_metric as Row[]) : [];
  const preview = Array.isArray(result.preview) ? (result.preview as Row[]) : [];
  const columns = preview.length
    ? Array.from(new Set(preview.flatMap((r) => Object.keys(r))))
        .filter((c) => c !== "row_index")
        .slice(0, 12)
    : [];
  const verdict = typeof result.verdict === "string" ? result.verdict : undefined;
  const stoppedNote =
    result.stopped === "deadline"
      ? jobCopy.stoppedDeadline
      : result.stopped === "cancelled"
        ? jobCopy.stoppedCancelled
        : undefined;

  return (
    <div className="space-y-4">
      {stoppedNote ? <p className="text-xs text-muted-foreground">{stoppedNote}</p> : null}
      {summary.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-3">
              結果摘要 {verdict ? <VerdictBadge verdict={verdict} /> : null}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-x-6 gap-y-1 font-mono text-xs tabular-nums sm:grid-cols-2 lg:grid-cols-3">
              {summary.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 border-b border-border/60 py-1">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="truncate text-right" title={cell(v)}>
                    {cell(v)}
                  </dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      ) : null}
      {perMetric.length ? (
        <Card>
          <CardHeader>
            <CardTitle>機台比對：逐指標</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>指標</TableHead>
                  <TableHead className="text-right">golden 中位數</TableHead>
                  <TableHead className="text-right">容許範圍</TableHead>
                  <TableHead className="text-right">測試中位數</TableHead>
                  <TableHead className="text-right">效應量</TableHead>
                  <TableHead className="text-right">p 值</TableHead>
                  <TableHead className="text-right">範圍內比例</TableHead>
                  <TableHead>判定</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {perMetric.map((m) => (
                  <TableRow key={String(m.metric)}>
                    <TableCell>
                      <div className="font-medium">{cell(m.label)}</div>
                      <div className="font-mono text-xs text-muted-foreground">{cell(m.metric)}</div>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">{cell(m.golden_median)}</TableCell>
                    <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                      {cell(m.golden_low)} ~ {cell(m.golden_high)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">{cell(m.test_median)}</TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">{cell(m.effect)}</TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">{cell(m.p_value)}</TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {typeof m.in_range_ratio === "number" ? `${Math.round(m.in_range_ratio * 100)}%` : "—"}
                    </TableCell>
                    <TableCell>
                      <VerdictBadge verdict={String(m.verdict)} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
      {preview.length ? (
        <Card>
          <CardHeader>
            <CardTitle>
              預測結果{result.preview_truncated ? "預覽" : ""}{" "}
              <span className="font-mono text-xs font-normal text-muted-foreground">
                {result.preview_truncated ? `前 ${preview.length} 筆，完整結果在 CSV` : `${preview.length} 筆`}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <PreviewTable rows={preview} columns={columns} job={job} />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
