import { PageHeader } from "@/components/layout/page-header";
import { getResourcePool, listProjects } from "@/lib/api";
import { QuotasTable } from "./quotas-table";

export default async function AdminQuotasPage() {
  const [projects, pool] = await Promise.all([listProjects({ includeArchived: true }), getResourcePool()]);
  return (
    <>
      <PageHeader
        title="專案配額"
        description="每個專案同時可用的上限。合計超過資源池時仍可儲存，但會提示；實際排程以資源池為準。"
      />
      <QuotasTable
        pool={pool}
        rows={projects.map((p) => ({
          slug: p.slug,
          name: p.name,
          status: p.status,
          gpu: p.gpuLimit,
          cpu: p.cpuLimit,
          memoryMb: p.memoryLimitMb,
          storageMb: p.storageQuotaMb,
          maxJobs: p.maxConcurrentJobs,
          usedBytes: p.storageUsedBytes,
        }))}
      />
    </>
  );
}
