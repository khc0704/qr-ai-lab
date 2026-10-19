import { Download, PackageCheck } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatBytes } from "@/lib/format";
import type { Job } from "@/types/domain";
import { withBase } from "@/lib/base-path";

/** Result of a preprocessing job: summary, and a one-shot download of the zip. */
export function PreprocessJobResults({ job }: { job: Job }) {
  const r = (job.result ?? {}) as Record<string, unknown>;
  const steps = Array.isArray(r.steps) ? (r.steps as string[]) : [];
  const files = Array.isArray(r.files) ? (r.files as string[]) : [];
  const gone = r.downloaded_at ? "已下載並從伺服器刪除。" : r.expired_at ? "逾期未下載，已刪除。" : null;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <PackageCheck className="size-4 text-brand-ink" />
            前處理結果
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {job.status !== "succeeded" ? (
            <p className="text-muted-foreground">任務完成後這裡會列出步驟、檔案與下載按鈕。</p>
          ) : (
            <>
              <ol className="space-y-1 font-mono text-xs">
                {steps.map((s, i) => (
                  <li key={i}>
                    {i + 1}. {s}
                  </li>
                ))}
              </ol>
              <div className="font-mono text-xs text-muted-foreground">
                檔案：{files.join("、") || "—"} · 前 {JSON.stringify(r.before ?? {})} → 後{" "}
                {JSON.stringify(r.after ?? {})}
              </div>
              {gone ? (
                <Alert>
                  <AlertDescription>{gone}</AlertDescription>
                </Alert>
              ) : (
                <Button asChild data-testid="tool-download">
                  <a href={withBase(`/api/download/jobs/${job.id}/download`)} download>
                    <Download />
                    下載結果 zip{typeof r.zip_size_bytes === "number" ? `（${formatBytes(r.zip_size_bytes)}）` : ""}
                  </a>
                </Button>
              )}
              <p className="text-xs text-muted-foreground">下載一次後伺服器即刪除；沒下載的結果在到期後自動刪除。</p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
