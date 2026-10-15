import { PageHeader } from "@/components/layout/page-header";
import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { getProjectRequest, getResourcePool } from "@/lib/api";
import { NewRequestForm } from "./new-request-form";

async function FormWithPool({ searchParams }: { searchParams: Promise<{ from?: string }> }) {
  const sp = await searchParams;
  const [pool, from] = await Promise.all([getResourcePool(), sp.from ? getProjectRequest(Number(sp.from)) : undefined]);
  return (
    <NewRequestForm
      poolGpu={pool.gpuIndices.length}
      poolCpu={pool.cpuCores}
      poolMemoryMb={pool.memoryMb}
      initial={from}
    />
  );
}

export default function NewProjectRequestPage({ searchParams }: PageProps<"/project-requests/new">) {
  return (
    <>
      <PageHeader title="新專案申請" description="管理員會依資料量與資源池審核；核准後自動建立專案並加入成員。" />
      <Suspense fallback={<PageSkeleton />}>
        <FormWithPool searchParams={searchParams} />
      </Suspense>
    </>
  );
}
