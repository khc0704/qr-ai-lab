import { QueueTable } from "@/components/features/queue-table";
import { PageHeader } from "@/components/layout/page-header";
import { getJobLog, getQueue, getResourcePool } from "@/lib/api";
import type { LogLine } from "@/types/domain";

export default async function AdminQueuePage() {
  const [{ running, queued }, pool] = await Promise.all([getQueue(), getResourcePool()]);
  const logs: Record<number, LogLine[]> = {};
  for (const j of [...running, ...queued]) logs[j.id] = await getJobLog(j.id, 300);
  return (
    <>
      <PageHeader
        title="佇列"
        description={`單一全域佇列，訓練與推論共用。資源池：${pool.gpuIndices.length} GPU · ${pool.cpuCores} CPU · 最多 ${pool.maxRunningJobs} 個同時執行${pool.allowBackfill ? "，允許 backfill" : "，嚴格依序"}。`}
      />
      <QueueTable running={running} queued={queued} logs={logs} />
    </>
  );
}
