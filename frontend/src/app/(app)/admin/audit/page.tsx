import { ScrollText } from "lucide-react";
import { Suspense } from "react";
import { EmptyState } from "@/components/features/empty-state";
import { UserInline } from "@/components/features/member-avatars";
import { pageFromParam, pageHref, Pagination } from "@/components/features/pagination";
import { TableSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listAuditLogsPage } from "@/lib/api";
import { RelativeTime } from "@/components/features/time";

const PAGE_SIZE = 50;

async function AuditList({ searchParams }: { searchParams: Promise<{ page?: string | string[] }> }) {
  const sp = await searchParams;
  const page = pageFromParam(sp.page);
  const logs = await listAuditLogsPage({ page, pageSize: PAGE_SIZE });
  if (logs.items.length === 0) {
    return <EmptyState icon={ScrollText} title="還沒有稽核紀錄" description="管理員操作與任務狀態變更會記錄在這裡。" />;
  }
  return (
    <>
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-44">時間</TableHead>
              <TableHead>操作者</TableHead>
              <TableHead>動作</TableHead>
              <TableHead>對象</TableHead>
              <TableHead>理由 / 內容</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {logs.items.map((l) => (
              <TableRow key={l.id}>
                <TableCell className="font-mono text-xs text-muted-foreground tabular-nums">
                  <RelativeTime iso={l.createdAt} />
                </TableCell>
                <TableCell>
                  {l.actor ? (
                    <UserInline user={l.actor} />
                  ) : (
                    <span className="text-sm text-muted-foreground">system</span>
                  )}
                </TableCell>
                <TableCell>
                  <span className="rounded-sm bg-muted px-1.5 py-0.5 font-mono text-xs">{l.action}</span>
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {l.targetType}
                  {l.targetId ? ` #${l.targetId}` : ""}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">{l.reason ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Pagination
        page={logs.page}
        pageSize={logs.pageSize}
        total={logs.total}
        href={(p) => pageHref("/admin/audit", {}, p)}
      />
    </>
  );
}

export default function AdminAuditPage({ searchParams }: PageProps<"/admin/audit">) {
  return (
    <>
      <PageHeader title="稽核紀錄" description="所有管理員操作與任務狀態變更。" />
      <Suspense fallback={<TableSkeleton />}>
        <AuditList searchParams={searchParams} />
      </Suspense>
    </>
  );
}
