import { ClipboardList, Plus } from "lucide-react";
import Link from "next/link";
import { EmptyState } from "@/components/features/empty-state";
import { RequestTable } from "@/components/features/request-table";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { listProjectRequests } from "@/lib/api";
import { getCurrentUser, isAdmin } from "@/lib/session";

export default async function ProjectRequestsPage() {
  const user = await getCurrentUser();
  const admin = isAdmin(user);
  const requests = await listProjectRequests(admin ? undefined : { applicantId: user.id });
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
      {requests.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title="還沒有申請"
          description="填寫題目、資料類型與資源需求，管理員核准後會自動建立專案。"
          dots
          action={
            <Button asChild>
              <Link href="/project-requests/new">新申請</Link>
            </Button>
          }
        />
      ) : (
        <RequestTable requests={requests} showApplicant={admin} />
      )}
    </>
  );
}
