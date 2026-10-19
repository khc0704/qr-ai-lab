import { ChartLine, ClipboardCheck, Cpu, HardDrive, ListOrdered, MemoryStick, Timer } from "lucide-react";
import Link from "next/link";
import { GpuCards } from "@/components/features/gpu-cards";
import { ResourceMeter } from "@/components/features/resource-meter";
import { ResourcePoolForm } from "@/components/features/resource-pool-form";
import { ToolDefaultsForm } from "@/components/features/tool-defaults-form";
import { StatCard } from "@/components/features/stat-card";
import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getAdminOverview, getNodeStatus, getResourcePool, getToolDefaults } from "@/lib/api";
import { formatMb } from "@/lib/format";
import { can, getCurrentUser } from "@/lib/session";

async function Dashboard() {
  const [overview, pool, node, me, toolDefaults] = await Promise.all([
    getAdminOverview(),
    getResourcePool(),
    getNodeStatus(),
    getCurrentUser(),
    getToolDefaults(),
  ]);
  const canManagePool = can(me, "pool.manage");
  const canResetGpu = can(me, "gpu.reset");
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
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle>GPU</CardTitle>
                  <CardDescription>
                    驅動程式讀到的顯存與排程器保留的份額；任務建立時填「每張 GPU 需要的顯存」即可多個任務共用一張。
                    {canResetGpu ? "「重置」可強制釋放卡住的顯存。" : ""}
                  </CardDescription>
                </div>
                <Button variant="outline" size="sm" asChild>
                  <Link href="/admin/usage">
                    <ChartLine />
                    使用率歷史
                  </Link>
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <GpuCards gpus={node.gpus} poolIndices={pool.gpuIndices} canReset={canResetGpu} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>總資源池</CardTitle>
              <CardDescription>
                Scheduler 以此為容量上限。變更只影響之後啟動的任務，並寫入稽核紀錄。
                {!canManagePool ? "只有 superadmin 可以調整；你目前只能檢視。" : ""}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResourcePoolForm pool={pool} node={node} readOnly={!canManagePool} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>工具預設（個人工作區配額）</CardTitle>
              <CardDescription>
                每位使用者第一次用「資料前處理 /
                資料分析」時會建立一個個人工作區，配額用這裡的值；已建立的工作區在「專案配額」頁個別調整。結果保留時間是前處理
                zip 沒被下載時的壽命。
                {!canManagePool ? "只有 superadmin 可以調整。" : ""}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ToolDefaultsForm defaults={toolDefaults} readOnly={!canManagePool} />
            </CardContent>
          </Card>
        </div>
        <aside className="space-y-4">
          {node.runner ? (
            <Card className="gap-3 p-5" data-testid="runner-card">
              <div className="text-label">任務執行方式</div>
              <div className="text-sm font-medium">
                {node.runner.kind === "systemd" ? "systemd-run cgroup scope" : "主機子程序（subprocess）"}
              </div>
              <p className="text-xs text-muted-foreground">{node.runner.note}</p>
              <ul className="grid grid-cols-3 gap-1 font-mono text-xs">
                {(
                  [
                    ["記憶體", node.runner.enforces.memory ? "cgroup" : node.runner.memoryWatchdog ? "watchdog" : null],
                    ["CPU", node.runner.enforces.cpu ? "cgroup" : "threads"],
                    [
                      "核心",
                      node.runner.enforces.cpuset ? (node.runner.kind === "systemd" ? "cgroup" : "affinity") : null,
                    ],
                  ] as const
                ).map(([k, how]) => (
                  <li key={k} className="rounded-md bg-muted px-2 py-1">
                    <span className="text-muted-foreground">{k}</span>{" "}
                    <span
                      className={
                        how === "cgroup" || how === "affinity"
                          ? "text-success"
                          : how
                            ? "text-warning"
                            : "text-muted-foreground"
                      }
                    >
                      {how ?? "—"}
                    </span>
                  </li>
                ))}
              </ul>
              <div className="truncate font-mono text-[11px] text-muted-foreground" title={node.runner.trainerPython}>
                {node.runner.trainerPython}
              </div>
              <div className="text-[11px] text-muted-foreground">
                離線：HF_HUB_OFFLINE / YOLO_OFFLINE 已設定，權重只讀模型庫
              </div>
            </Card>
          ) : null}
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

export default function AdminDashboardPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Dashboard />
    </Suspense>
  );
}
