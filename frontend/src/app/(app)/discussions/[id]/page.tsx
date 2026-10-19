import { notFound } from "next/navigation";
import { Suspense } from "react";
import { IssueAdminActions } from "@/components/features/issue-admin-actions";
import { RelativeTime } from "@/components/features/time";
import { UserInline } from "@/components/features/member-avatars";
import { PageSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { issueTypeLabel } from "@/i18n/zh-TW";
import { getIssue, listComments } from "@/lib/api";
import { can, getCurrentUser, isAdmin } from "@/lib/session";
import Link from "next/link";
import { IssueThread } from "./issue-thread";

async function IssueDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const issue = await getIssue(Number(id));
  if (!issue) notFound();
  const [comments, user] = await Promise.all([listComments("issue", issue.id), getCurrentUser()]);
  const admin = isAdmin(user);
  // The backend is the authority (PATCH /issues/{id} checks author-or-admin); this only decides whether to show the editor.
  const canEdit = admin || issue.author.id === user.id;

  const rows: [string, React.ReactNode][] = [
    ["狀態", <StatusBadge key="s" status={issue.status} />],
    ["類型", issueTypeLabel[issue.type]],
    ["作者", <UserInline key="a" user={issue.author} />],
    [
      "指派",
      issue.assignee ? (
        <UserInline key="g" user={issue.assignee} />
      ) : (
        <span className="text-subtle-foreground">未指派</span>
      ),
    ],
    [
      "關聯專案",
      issue.projectSlug ? (
        <Link
          key="p"
          href={`/projects/${issue.projectSlug}`}
          className="font-mono text-xs text-brand-ink hover:underline"
        >
          {issue.projectSlug}
        </Link>
      ) : (
        <span className="text-subtle-foreground">無</span>
      ),
    ],
    ["建立", <RelativeTime key="c" iso={issue.createdAt} className="font-mono text-xs" />],
  ];

  return (
    <>
      <PageHeader
        eyebrow={`#${issue.id} · ${issueTypeLabel[issue.type]}`}
        title={issue.title}
        actions={
          admin ? (
            <IssueAdminActions id={issue.id} status={issue.status} canDelete={can(user, "issues.moderate")} />
          ) : null
        }
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <IssueThread issue={issue} comments={comments} currentUser={user} canEdit={canEdit} />
        <aside className="space-y-4">
          <Card className="gap-0 p-0">
            <dl className="divide-y divide-border">
              {rows.map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-3 px-4 py-2.5">
                  <dt className="text-label">{k}</dt>
                  <dd className="text-sm">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </aside>
      </div>
    </>
  );
}

export default function IssuePage({ params }: PageProps<"/discussions/[id]">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <IssueDetail params={params} />
    </Suspense>
  );
}
