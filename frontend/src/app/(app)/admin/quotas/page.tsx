import { Suspense } from "react";
import { TableSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { getResourcePool, listProjects } from "@/lib/api";
import { can, getCurrentUser } from "@/lib/session";
import { QuotasTable } from "./quotas-table";

async function Quotas() {
  const [projects, pool, me] = await Promise.all([
    listProjects({ includeArchived: true, includePersonal: true }),
    getResourcePool(),
    getCurrentUser(),
  ]);
  const readOnly = !can(me, "quota.manage");
  return (
    <>
      <PageHeader
        title="專案配額"
        description={`每個專案同時可用的上限。合計超過資源池時仍可儲存，但會提示；實際排程以資源池為準。${readOnly ? "只有 superadmin 可以調整；你目前只能檢視。" : ""}`}
      />
      <QuotasTable
        pool={pool}
        readOnly={readOnly}
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

export default function AdminQuotasPage() {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <Quotas />
    </Suspense>
  );
}
