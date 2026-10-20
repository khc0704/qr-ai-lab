import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { getCatalog, getResourcePool } from "@/lib/api";
import { supportedTasks } from "@/lib/catalog";
import { ApplyForm } from "./apply-form";

export const metadata = { title: "專案申請" };

async function Apply() {
  const [pool, catalog] = await Promise.all([getResourcePool(), getCatalog()]);
  return (
    <ApplyForm
      poolGpu={pool.gpuIndices.length}
      poolCpu={pool.cpuCores}
      poolMemoryMb={pool.memoryMb}
      tasksByType={supportedTasks(catalog)}
    />
  );
}

export default function NewProjectPage() {
  return (
    <>
      <PageHeader
        title="專案申請"
        description="送出後專案立刻以「申請中」建立，管理員核准並設定配額後，資料來源、任務等分頁才會開放。"
      />
      <Suspense fallback={<PageSkeleton />}>
        <Apply />
      </Suspense>
    </>
  );
}
