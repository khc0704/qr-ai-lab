import { MessageSquarePlus, MessagesSquare } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";
import { EmptyState } from "@/components/features/empty-state";
import { UserAvatar } from "@/components/features/member-avatars";
import { TableSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { issueTypeLabel } from "@/i18n/zh-TW";
import { listIssues } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { IssueStatus, IssueType } from "@/types/domain";

const statusTabs: { value: IssueStatus | "all"; label: string }[] = [
  { value: "open", label: "開放" },
  { value: "closed", label: "已關閉" },
  { value: "all", label: "全部" },
];

async function IssueList({ searchParams }: { searchParams: Promise<{ status?: string; type?: string }> }) {
  const sp = await searchParams;
  const status = (statusTabs.some((t) => t.value === sp.status) ? sp.status : "open") as IssueStatus | "all";
  const type = sp.type as IssueType | undefined;
  const issues = await listIssues({ status: status === "all" ? undefined : status, type });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 border-b border-border">
        {statusTabs.map((t) => (
          <Link
            key={t.value}
            href={`/discussions?status=${t.value}${type ? `&type=${type}` : ""}`}
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
        <div className="ml-auto flex items-center gap-1 pb-2">
          {(["question", "bug", "feature"] as IssueType[]).map((t) => (
            <Link
              key={t}
              href={`/discussions?status=${status}${type === t ? "" : `&type=${t}`}`}
              className={cn(
                "rounded-md border px-2 py-0.5 text-xs transition-colors",
                type === t
                  ? "border-primary/50 bg-primary/10 text-brand-ink"
                  : "border-border text-muted-foreground hover:bg-accent",
              )}
            >
              {issueTypeLabel[t]}
            </Link>
          ))}
        </div>
      </div>
      {issues.length === 0 ? (
        <EmptyState icon={MessagesSquare} title="沒有符合的問題" description="換個篩選條件，或開一個新問題。" />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16 text-right">#</TableHead>
                <TableHead>標題</TableHead>
                <TableHead>類型</TableHead>
                <TableHead>狀態</TableHead>
                <TableHead>作者</TableHead>
                <TableHead className="text-right">留言</TableHead>
                <TableHead className="text-right">建立</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {issues.map((i) => (
                <TableRow key={i.id}>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                    {i.id}
                  </TableCell>
                  <TableCell>
                    <Link href={`/discussions/${i.id}`} className="font-medium hover:text-brand-ink">
                      {i.title}
                    </Link>
                    {i.projectSlug ? (
                      <span className="ml-2 rounded-sm bg-muted px-1.5 font-mono text-[11px] text-muted-foreground">
                        {i.projectSlug}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{issueTypeLabel[i.type]}</TableCell>
                  <TableCell>
                    <StatusBadge status={i.status} />
                  </TableCell>
                  <TableCell>
                    <span className="inline-flex items-center gap-2">
                      <UserAvatar user={i.author} className="size-6" />
                      {i.author.displayName}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">{i.commentCount}</TableCell>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                    {formatRelative(i.createdAt)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export default function DiscussionsPage({ searchParams }: PageProps<"/discussions">) {
  return (
    <>
      <PageHeader
        title="討論區"
        description="問答、錯誤回報與功能建議。專案申請請到「專案申請」。"
        actions={
          <Button asChild>
            <Link href="/discussions/new">
              <MessageSquarePlus />
              新問題
            </Link>
          </Button>
        }
      />
      <Suspense fallback={<TableSkeleton />}>
        <IssueList searchParams={searchParams} />
      </Suspense>
    </>
  );
}
