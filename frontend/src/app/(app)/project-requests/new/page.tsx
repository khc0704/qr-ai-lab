import { PageHeader } from "@/components/layout/page-header";
import { getResourcePool } from "@/lib/api";
import { NewRequestForm } from "./new-request-form";

export default async function NewProjectRequestPage() {
  const pool = await getResourcePool();
  return (
    <>
      <PageHeader title="新專案申請" description="管理員會依資料量與資源池審核；核准後自動建立專案並加入成員。" />
      <NewRequestForm poolGpu={pool.gpuIndices.length} poolCpu={pool.cpuCores} poolMemoryMb={pool.memoryMb} />
    </>
  );
}
