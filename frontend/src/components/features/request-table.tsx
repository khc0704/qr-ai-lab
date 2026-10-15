import Link from "next/link";
import { DataTypeChip, TaskChip } from "@/components/features/chips";
import { UserInline } from "@/components/features/member-avatars";
import { StatusBadge } from "@/components/features/status-badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RelativeTime } from "@/components/features/time";
import { formatMb } from "@/lib/format";
import type { ProjectRequest } from "@/types/domain";

export function RequestTable({ requests, showApplicant }: { requests: ProjectRequest[]; showApplicant: boolean }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-16 text-right">#</TableHead>
            <TableHead>題目</TableHead>
            <TableHead>資料 / 任務</TableHead>
            <TableHead>資源需求</TableHead>
            <TableHead>狀態</TableHead>
            {showApplicant ? <TableHead>申請人</TableHead> : null}
            <TableHead className="text-right">送出</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {requests.map((r) => (
            <TableRow key={r.id}>
              <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">{r.id}</TableCell>
              <TableCell>
                <Link href={`/project-requests/${r.id}`} className="font-medium hover:text-brand-ink">
                  {r.title}
                </Link>
                {r.projectSlug ? (
                  <Link
                    href={`/projects/${r.projectSlug}`}
                    className="ml-2 font-mono text-[11px] text-brand-ink hover:underline"
                  >
                    {r.projectSlug}
                  </Link>
                ) : null}
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  <DataTypeChip dataType={r.dataType} />
                  <TaskChip taskType={r.taskType} />
                </div>
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground tabular-nums">
                {r.requestedGpu} GPU · {r.requestedCpu} CPU · {formatMb(r.requestedMemoryMb)} ·{" "}
                {formatMb(r.requestedStorageMb)}
              </TableCell>
              <TableCell>
                <StatusBadge status={r.status} />
              </TableCell>
              {showApplicant ? (
                <TableCell>
                  <UserInline user={r.applicant} />
                </TableCell>
              ) : null}
              <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                <RelativeTime iso={r.submittedAt} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
