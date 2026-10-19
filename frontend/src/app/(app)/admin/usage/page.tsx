import Link from "next/link";
import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Info } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { getNodeStatus, getUsageHistory } from "@/lib/api";
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
  const [history, node] = await Promise.all([getUsageHistory(range), getNodeStatus()]);
  return (
    <>
      <PageHeader
        title="資源使用率歷史"
        description={`排程器每 ${history.sampleIntervalS} 秒取樣節點、資源池與各專案的配置；圖表依區間分桶平均（${history.bucketS >= 3600 ? `${history.bucketS / 3600} 小時` : `${history.bucketS / 60} 分鐘`}）。`}
        actions={
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="時間範圍">
            {RANGES.map((r) => (
              <Button key={r.value} variant={r.value === range ? "secondary" : "ghost"} size="sm" asChild>
                <Link href={`/admin/usage?range=${r.value}`} role="tab" aria-selected={r.value === range}>
                  {r.label}
                </Link>
              </Button>
            ))}
          </div>
        }
      />
      {node.platform === "wsl2" ? (
        <Alert>
          <Info />
          <AlertTitle>這台 backend 跑在 WSL2 裡</AlertTitle>
          <AlertDescription>
            節點的 CPU 核數與記憶體是 WSL 虛擬機看到的量（由 .wslconfig 決定，預設只有主機記憶體的一半），和 Windows
            工作管理員的數字不會一致；GPU 透過 NVIDIA driver 讀到的是真實數值。正式伺服器（原生 Ubuntu）沒有這個差異。
          </AlertDescription>
        </Alert>
      ) : null}
      <Alert>
        <Info />
        <AlertTitle>怎麼讀這張圖</AlertTitle>
        <AlertDescription>
          「配置」是排程器給任務保留的量（任務申請的 CPU / 記憶體 / GPU），「實測」是任務程序與驅動程式實際回報的量；
          CPU 實測是每個取樣區間內的平均使用率，剛重啟後的第一筆取樣以啟動至今為區間。
        </AlertDescription>
      </Alert>
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
