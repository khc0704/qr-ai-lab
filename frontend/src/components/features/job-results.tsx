// Server-rendered inference results: summary stats, the IQA "compare" verdict table, and the first
// rows of predictions. Everything else is in the downloadable CSV / JSONL.
import { PreviewTable } from "@/components/features/preview-table";
import { VerdictBadge } from "@/components/features/verdict-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { jobCopy } from "@/i18n/zh-TW";
import { formatMetric } from "@/lib/format";
import { PREVIEW_HIDDEN_COLUMNS } from "@/lib/results";
import type { Job } from "@/types/domain";

type Row = Record<string, unknown>;

const HIDDEN = new Set([
  "mode",
  "model_artifact_id",
  "preview",
  "preview_truncated",
  "artifacts",
  "per_metric",
  "advice",
  "paired",
  "stopped",
]);

const DIRECTION_LABEL: Record<string, string> = { high: "比基準高", low: "比基準低" };

const PAIRED_LABEL: Record<string, string> = {
  n: "配對張數",
  psnr_mean: "PSNR 平均（dB）",
  ssim_mean: "SSIM 平均",
  ssim_min: "SSIM 最低",
  ms_ssim_mean: "MS-SSIM 平均",
  gmsd_mean: "GMSD 平均（越低越像）",
};

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
  const advice = Array.isArray(result.advice) ? (result.advice as Row[]) : [];
  const paired = result.paired && typeof result.paired === "object" ? (result.paired as Row) : null;
  const preview = Array.isArray(result.preview) ? (result.preview as Row[]) : [];
  const columns = preview.length
    ? Array.from(new Set(preview.flatMap((r) => Object.keys(r))))
        .filter((c) => !PREVIEW_HIDDEN_COLUMNS.has(c))
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
      {advice.length ? (
        <Card data-testid="iqa-advice">
          <CardHeader>
            <CardTitle>建議調整</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-3 text-sm">
              {advice.map((a) => (
                <li key={String(a.aspect)} className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{cell(a.label)}</span>
                    <span className="rounded-sm bg-warning/10 px-1.5 text-xs text-warning">
                      {DIRECTION_LABEL[String(a.direction)] ?? cell(a.direction)}
                    </span>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {Array.isArray(a.metrics) ? a.metrics.join(" · ") : ""}
                    </span>
                  </div>
                  <p className="text-muted-foreground">{cell(a.advice)}</p>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-muted-foreground">
              依偏離最多的指標分組；單張影像「偏離基準最多的區塊」在預測結果列點開樣本即可看到。
            </p>
          </CardContent>
        </Card>
      ) : null}
      {paired ? (
        <Card data-testid="iqa-paired">
          <CardHeader>
            <CardTitle className="flex items-center gap-3">
              與參考影像逐張比對（全參考）
              {typeof paired.verdict === "string" ? <VerdictBadge verdict={paired.verdict} /> : null}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-x-6 gap-y-1 font-mono text-xs tabular-nums sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(paired)
                .filter(([k]) => k !== "verdict")
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3 border-b border-border/60 py-1">
                    <dt className="text-muted-foreground">{PAIRED_LABEL[k] ?? k}</dt>
                    <dd className="text-right">{cell(v)}</dd>
                  </div>
                ))}
            </dl>
            <p className="mt-3 text-xs text-muted-foreground">
              每張影像先以相位相關對位，再算 PSNR / SSIM / MS-SSIM /
              GMSD；逐張數值與位移在預測結果列，差異最大的區塊在樣本檢視器。
            </p>
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
