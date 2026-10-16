import { ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";
import { EmptyState } from "@/components/features/empty-state";
import { pageFromParam, pageHref, Pagination } from "@/components/features/pagination";
import { RequestTable } from "@/components/features/request-table";
import { TableSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { listProjectRequestsPage } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { RequestStatus } from "@/types/domain";

const tabs: { value: "pending" | RequestStatus | "all"; label: string }[] = [
  { value: "pending", label: "待審" },
  { value: "approved", label: "已核准" },
  { value: "rejected", label: "已退回" },
  { value: "all", label: "全部" },
];

const PAGE_SIZE = 20;

async function List({ searchParams }: { searchParams: Promise<{ status?: string; page?: string | string[] }> }) {
  const sp = await searchParams;
  const status = (tabs.some((t) => t.value === sp.status) ? sp.status : "pending") as (typeof tabs)[number]["value"];
  const page = pageFromParam(sp.page);
  const requests = await listProjectRequestsPage({
    status: status === "all" ? undefined : status === "pending" ? ["submitted", "in_review"] : [status],
    page,
    pageSize: PAGE_SIZE,
  });
  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b border-border">
        {tabs.map((t) => (
          <Link
            key={t.value}
            href={`/admin/requests?status=${t.value}`}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
              status === t.value
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </Link>
        ))}
      </div>
      {requests.items.length === 0 ? (
        <EmptyState icon={ClipboardCheck} title={status === "pending" ? "沒有待審的申請" : "沒有符合的申請"} />
      ) : (
        <RequestTable requests={requests.items} showApplicant />
      )}
      <Pagination
        page={requests.page}
        pageSize={requests.pageSize}
        total={requests.total}
        href={(p) => pageHref("/admin/requests", { status }, p)}
      />
    </div>
  );
}

export default function AdminRequestsPage({ searchParams }: PageProps<"/admin/requests">) {
  return (
    <>
      <PageHeader title="申請審核" description="點進申請即可開始審核、核准或退回。" />
      <Suspense fallback={<TableSkeleton />}>
        <List searchParams={searchParams} />
      </Suspense>
    </>
  );
}
