import { ListChecks } from "lucide-react";
import { Suspense } from "react";
import { EmptyState } from "@/components/features/empty-state";
import { pageFromParam, pageHref, Pagination } from "@/components/features/pagination";
import { TableSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { listAdminJobsPage } from "@/lib/api";
import type { Job } from "@/types/domain";
import { JobsFilters, type JobsFilterValues } from "./jobs-filters";
import { JobsTable } from "./jobs-table";

const PAGE_SIZE = 50;
const STATUS_GROUPS: Record<string, Job["status"][]> = {
  active: ["queued", "scheduled", "running"],
  finished: ["succeeded", "failed", "cancelled"],
  succeeded: ["succeeded"],
  failed: ["failed"],
  cancelled: ["cancelled"],
};
const KINDS = new Set<string>(["train", "inference", "preprocess", "analysis"]);

const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";

async function AdminJobs({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const page = pageFromParam(sp.page);
  const values: JobsFilterValues = {
    status: first(sp.status),
    kind: first(sp.kind),
    project: first(sp.project).trim(),
    q: first(sp.q).trim(),
    ephemeral: first(sp.ephemeral),
  };
  const jobs = await listAdminJobsPage({
    page,
    pageSize: PAGE_SIZE,
    status: STATUS_GROUPS[values.status],
    kind: KINDS.has(values.kind) ? (values.kind as Job["kind"]) : undefined,
    project: values.project || undefined,
    q: values.q || undefined,
    ephemeral: values.ephemeral === "only" ? true : values.ephemeral === "none" ? false : undefined,
  });
  const params = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v || undefined]));
  return (
    <>
      <PageHeader
        title="任務管理"
        description="所有專案的任務，含工具池任務與一次性推論。已結束的任務可以單筆或整批刪除：任務紀錄、log、輸出與它產生的模型 / 報告會一併刪除；執行中的任務請到「佇列」中斷，還被推論任務引用的模型會跳過並說明原因。"
        eyebrow={<span className="font-mono normal-case">{jobs.total} 個任務</span>}
      />
      <JobsFilters key={JSON.stringify(values)} values={values} />
      {jobs.items.length === 0 ? (
        <EmptyState icon={ListChecks} title="沒有符合的任務" description="換個篩選條件，或回到第一頁。" />
      ) : (
        <JobsTable key={jobs.items.map((j) => j.id).join(",")} jobs={jobs.items} />
      )}
      <Pagination
        page={jobs.page}
        pageSize={jobs.pageSize}
        total={jobs.total}
        href={(p) => pageHref("/admin/jobs", params, p)}
      />
    </>
  );
}

export default function AdminJobsPage({ searchParams }: PageProps<"/admin/jobs">) {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <AdminJobs searchParams={searchParams} />
    </Suspense>
  );
}
