import { ListChecks } from "lucide-react";
import Link from "next/link";
import { AutoRefresh } from "@/components/features/auto-refresh";
import { KindChip } from "@/components/features/chips";
import { EmptyState } from "@/components/features/empty-state";
import { StatusBadge } from "@/components/features/status-badge";
import { RelativeTime } from "@/components/features/time";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { analysisKindLabel, jobStageLabel } from "@/i18n/zh-TW";
import { listToolJobs } from "@/lib/api";
import type { AnalysisKind } from "@/types/domain";

/** The user's preprocessing / analysis jobs (shared tool pool); refreshes itself while any job is active. */
export async function ToolJobs({ kind }: { kind?: "preprocess" | "analysis" }) {
  const jobs = (await listToolJobs()).filter((j) => !kind || j.kind === kind);
  const active = jobs.some((j) => j.status === "queued" || j.status === "scheduled" || j.status === "running");
  return (
    <Card>
      <CardHeader>
        <CardTitle>我的{kind === "analysis" ? "分析" : kind === "preprocess" ? "前處理" : "工具"}任務</CardTitle>
        <CardDescription>
          在公共的工具池排隊執行（全域佇列、資源限制、log 與其他任務相同）；點任務看即時 log、結果與下載。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <AutoRefresh active={active} />
        {jobs.length === 0 ? (
          <EmptyState icon={ListChecks} title="還沒有任務" description="上傳檔案並按「建立任務」後會列在這裡。" />
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>任務</TableHead>
                  <TableHead>狀態</TableHead>
                  <TableHead>階段</TableHead>
                  <TableHead className="text-right">建立</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.map((j) => (
                  <TableRow key={j.id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <KindChip kind={j.kind} />
                        <Link href={`/tools/jobs/${j.id}`} className="font-medium hover:text-brand-ink">
                          {j.name}
                        </Link>
                        <span className="font-mono text-xs text-subtle-foreground">#{j.id}</span>
                        {j.kind === "analysis" && j.config?.analysis ? (
                          <span className="text-xs text-muted-foreground">
                            {analysisKindLabel[j.config.analysis as AnalysisKind] ?? String(j.config.analysis)}
                          </span>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={j.status} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {j.status === "running" && j.currentStage ? jobStageLabel[j.currentStage] : (j.waitReason ?? "—")}
                      {j.status === "running" ? (
                        <span className="ml-2 font-mono text-xs tabular-nums">{j.progress}%</span>
                      ) : null}
                      {j.status === "succeeded" && j.kind === "preprocess" ? (
                        <span className="ml-2 text-xs">
                          {j.result?.downloaded_at ? "已下載並刪除" : j.result?.expired_at ? "已逾期刪除" : "可下載"}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                      <RelativeTime iso={j.createdAt} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
