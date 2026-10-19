import { ChartScatter, Wand2 } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";
import { StatCard } from "@/components/features/stat-card";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getToolPoolStatus } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { ToolJobs } from "./tool-jobs";

export const metadata = { title: "工具" };

const TOOLS = [
  {
    href: "/tools/preprocess",
    icon: Wand2,
    title: "資料前處理",
    description: "上傳檔案、挑步驟、即時抽樣預覽，再由任務處理整個檔案；結果打包成 zip，下載一次即刪。",
  },
  {
    href: "/tools/analyze",
    icon: ChartScatter,
    title: "資料分析",
    description:
      "表格：相關性、共線性（VIF）、對目標的解釋力與建議；影像：各機台 / 條件的 IQA 指標飄移、embedding 相似度與離群影像。",
  },
] as const;

async function PoolQuota() {
  const pool = await getToolPoolStatus();
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        label="我的工具任務"
        value={`${pool.myActiveJobs} / ${pool.maxJobsPerUser}`}
        tone={pool.myActiveJobs >= pool.maxJobsPerUser ? "warning" : "default"}
        hint="排隊 + 執行中 / 每人上限"
      />
      <StatCard
        label="工具池 GPU / CPU"
        value={`${pool.gpuLimit} / ${pool.cpuLimit}`}
        hint="所有人共用，由管理員設定"
      />
      <StatCard label="記憶體上限" value={formatBytes(pool.memoryLimitMb * 1024 * 1024)} />
      <StatCard
        label="整池同時執行"
        value={`${pool.maxConcurrentJobs} 個任務`}
        hint={`結果保留 ${pool.resultTtlHours} 小時`}
      />
    </div>
  );
}

export default function ToolsPage() {
  return (
    <>
      <PageHeader
        title="工具"
        description="不需要專案就能用的資料工具：任務在公共的工具池排隊執行，不佔用任何專案配額，和其他任務一樣受資源限制、有 log；本服務不保存資料。"
      />
      <div className="grid gap-4 md:grid-cols-2">
        {TOOLS.map((t) => (
          <Card key={t.href}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <t.icon className="size-5 text-signal" aria-hidden />
                {t.title}
              </CardTitle>
              <CardDescription>{t.description}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" size="sm" asChild>
                <Link href={t.href}>開啟{t.title}</Link>
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
      <Suspense fallback={<Skeleton className="h-24 w-full" />}>
        <PoolQuota />
      </Suspense>
      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <ToolJobs />
      </Suspense>
    </>
  );
}
