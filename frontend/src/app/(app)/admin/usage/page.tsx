import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { getUsageHistory } from "@/lib/api";
import type { UsageRange } from "@/types/domain";
import { UsageCharts } from "./usage-charts";

const RANGES: { value: UsageRange; label: string }[] = [
  { value: "1h", label: "1 小時" },
  { value: "6h", label: "6 小時" },
  { value: "24h", label: "24 小時" },
  { value: "7d", label: "7 天" },
  { value: "30d", label: "30 天" },
];

async function Usage({ searchParams }: { searchParams: Promise<{ range?: string }> }) {
  const sp = await searchParams;
  const range = (RANGES.some((r) => r.value === sp.range) ? sp.range : "24h") as UsageRange;
  const history = await getUsageHistory(range);
  return (
    <>
      <PageHeader
        title="資源使用率歷史"
        description={`排程器每 ${history.sampleIntervalS} 秒取樣節點、資源池與各專案的配置；圖表依區間分桶平均（${history.bucketS >= 3600 ? `${history.bucketS / 3600} 小時` : `${history.bucketS / 60} 分鐘`}）。`}
        actions={
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="時間範圍">
            {RANGES.map((r) => (
              <Button key={r.value} variant={r.value === range ? "secondary" : "ghost"} size="sm" asChild>
                <a href={`/admin/usage?range=${r.value}`} role="tab" aria-selected={r.value === range}>
                  {r.label}
                </a>
              </Button>
            ))}
          </div>
        }
      />
      <UsageCharts history={history} />
    </>
  );
}

export default function UsagePage({ searchParams }: PageProps<"/admin/usage">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Usage searchParams={searchParams} />
    </Suspense>
  );
}

export const metadata = { title: "資源使用率歷史" };
