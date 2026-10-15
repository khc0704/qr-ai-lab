import { UserInline } from "@/components/features/member-avatars";
import { PageHeader } from "@/components/layout/page-header";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listAuditLogs } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";

export default async function AdminAuditPage() {
  const logs = await listAuditLogs();
  return (
    <>
      <PageHeader title="稽核紀錄" description="所有管理員操作與任務狀態變更。" />
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
            {logs.map((l) => (
              <TableRow key={l.id}>
                <TableCell
                  className="font-mono text-xs text-muted-foreground tabular-nums"
                  title={formatDateTime(l.createdAt)}
                >
                  {formatRelative(l.createdAt)}
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
    </>
  );
}
