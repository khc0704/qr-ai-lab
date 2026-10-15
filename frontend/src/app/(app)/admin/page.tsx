import { ClipboardCheck, Cpu, HardDrive, ListOrdered, MemoryStick, Timer } from "lucide-react";
import Link from "next/link";
import { ResourceMeter } from "@/components/features/resource-meter";
import { ResourcePoolForm } from "@/components/features/resource-pool-form";
import { StatCard } from "@/components/features/stat-card";
import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getAdminOverview, getNodeStatus, getResourcePool } from "@/lib/api";
import { formatMb } from "@/lib/format";

export default async function AdminDashboardPage() {
  const [overview, pool, node] = await Promise.all([getAdminOverview(), getResourcePool(), getNodeStatus()]);
  const diskPct = Math.round(((node.diskTotalGb - node.diskFreeGb) / node.diskTotalGb) * 100);
  return (
    <>
      <PageHeader
        title="管理員 Dashboard"
        description="總資源池、節點狀態與待辦。資源池是所有專案合計可用的上限，專案配額之和不應超過它。"
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="待審申請"
          value={overview.pendingRequests}
          icon={ClipboardCheck}
          tone={overview.pendingRequests > 0 ? "warning" : "default"}
          hint={
            <Link href="/admin/requests" className="text-brand-ink hover:underline">
              前往審核
            </Link>
          }
        />
        <StatCard
          label="佇列中"
          value={overview.queued}
          icon={ListOrdered}
          hint={
            <Link href="/admin/queue" className="text-brand-ink hover:underline">
              管理佇列
            </Link>
          }
        />
        <StatCard
          label="執行中"
          value={overview.running}
          icon={Timer}
          tone="signal"
          hint={`上限 ${pool.maxRunningJobs}`}
        />
        <StatCard
          label="資源池 GPU 使用率"
          value={`${overview.poolUtilization}%`}
          icon={HardDrive}
          tone={overview.poolUtilization >= 90 ? "destructive" : overview.poolUtilization >= 70 ? "warning" : "default"}
          hint={`${overview.poolGpuUsed} / ${overview.poolGpuTotal} GPU 已配置`}
        />
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader>
            <CardTitle>總資源池</CardTitle>
            <CardDescription>Scheduler 以此為容量上限。變更只影響之後啟動的任務，並寫入稽核紀錄。</CardDescription>
          </CardHeader>
          <CardContent>
            <ResourcePoolForm pool={pool} node={node} />
          </CardContent>
        </Card>
        <aside className="space-y-4">
          <Card className="gap-4 p-5">
            <div className="text-label">節點實體狀態</div>
            <ResourceMeter
              label="CPU"
              used={node.cpuUsedCores}
              total={node.cpuCores}
              format={(n) => n.toFixed(1)}
              unit="核"
            />
            <ResourceMeter label="Memory" used={node.memoryUsedMb} total={node.memoryMb} format={formatMb} />
            <ResourceMeter
              label="磁碟（DATA_ROOT）"
              used={node.diskTotalGb - node.diskFreeGb}
              total={node.diskTotalGb}
              unit="GB"
            />
            <p className="text-xs text-muted-foreground">
              磁碟剩餘 {node.diskFreeGb} GB（{100 - diskPct}%）。低於 10% 時新任務不排程。
            </p>
          </Card>
          <Card className="gap-3 p-5">
            <div className="text-label">已配置給任務</div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-sm tabular-nums">
              <dt className="inline-flex items-center gap-1 text-muted-foreground">
                <HardDrive className="size-3.5" />
                GPU
              </dt>
              <dd className="text-right">
                {node.allocated.gpu} / {pool.gpuIndices.length}
              </dd>
              <dt className="inline-flex items-center gap-1 text-muted-foreground">
                <Cpu className="size-3.5" />
                CPU
              </dt>
              <dd className="text-right">
                {node.allocated.cpu} / {pool.cpuCores}
              </dd>
              <dt className="inline-flex items-center gap-1 text-muted-foreground">
                <MemoryStick className="size-3.5" />
                Mem
              </dt>
              <dd className="text-right">
                {formatMb(node.allocated.memoryMb)} / {formatMb(pool.memoryMb)}
              </dd>
            </dl>
          </Card>
        </aside>
      </div>
    </>
  );
}
