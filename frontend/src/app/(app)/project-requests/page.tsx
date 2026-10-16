import { ClipboardList, Plus } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";
import { EmptyState } from "@/components/features/empty-state";
import { pageFromParam, pageHref, Pagination } from "@/components/features/pagination";
import { RequestTable } from "@/components/features/request-table";
import { TableSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { listProjectRequestsPage } from "@/lib/api";
import { getCurrentUser, isAdmin } from "@/lib/session";

const PAGE_SIZE = 20;

async function Requests({ searchParams }: { searchParams: Promise<{ page?: string | string[] }> }) {
  const sp = await searchParams;
  const page = pageFromParam(sp.page);
  // The backend limits non-admins to their own applications, so the same call serves both views.
  const [user, requests] = await Promise.all([
    getCurrentUser(),
    listProjectRequestsPage({ page, pageSize: PAGE_SIZE }),
  ]);
  const admin = isAdmin(user);
  return (
    <>
      <PageHeader
        title="專案申請"
        description={admin ? "全部申請；審核請到管理 → 申請審核，或直接點進申請。" : "你提出的專案申請與審核進度。"}
        actions={
          <Button asChild>
            <Link href="/project-requests/new">
              <Plus />
              新申請
            </Link>
          </Button>
        }
      />
      {requests.items.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title={requests.total === 0 ? "還沒有申請" : "這一頁沒有申請"}
          description={
            requests.total === 0 ? "填寫題目、資料類型與資源需求，管理員核准後會自動建立專案。" : "回到第一頁查看。"
          }
          dots
          action={
            requests.total === 0 ? (
              <Button asChild>
                <Link href="/project-requests/new">新申請</Link>
              </Button>
            ) : (
              <Button variant="outline" asChild>
                <Link href="/project-requests">第一頁</Link>
              </Button>
            )
          }
        />
      ) : (
        <RequestTable requests={requests.items} showApplicant={admin} />
      )}
      <Pagination
        page={requests.page}
        pageSize={requests.pageSize}
        total={requests.total}
        href={(p) => pageHref("/project-requests", {}, p)}
      />
    </>
  );
}

export default function ProjectRequestsPage({ searchParams }: PageProps<"/project-requests">) {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <Requests searchParams={searchParams} />
    </Suspense>
  );
}
