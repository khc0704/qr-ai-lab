import { Pencil, Undo2 } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { DataTypeChip, TaskChip } from "@/components/features/chips";
import { CommentThread } from "@/components/features/comment-thread";
import { UserInline } from "@/components/features/member-avatars";
import { RequestReviewPanel } from "@/components/features/request-review-panel";
import { PageSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { dataScaleLabel, projectRoleLabel } from "@/i18n/zh-TW";
import { getProjectRequest, getResourcePool, listComments } from "@/lib/api";
import { formatDateTime, formatMb, formatRelative } from "@/lib/format";
import { getCurrentUser, isAdmin } from "@/lib/session";

async function RequestDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const req = await getProjectRequest(Number(id));
  if (!req) notFound();
  const [comments, user, pool] = await Promise.all([
    listComments("project_request", req.id),
    getCurrentUser(),
    getResourcePool(),
  ]);
  const admin = isAdmin(user);
  const mine = req.applicant.id === user.id;

  const fields: [string, React.ReactNode][] = [
    ["資料類型", <DataTypeChip key="d" dataType={req.dataType} />],
    ["任務", <TaskChip key="t" taskType={req.taskType} />],
    ["資料量級", dataScaleLabel[req.dataScale]],
    ["資料描述", req.dataDescription ?? <span className="text-subtle-foreground">未填</span>],
    [
      "資源需求",
      <span key="r" className="font-mono text-sm tabular-nums">
        {req.requestedGpu} GPU · {req.requestedCpu} CPU · {formatMb(req.requestedMemoryMb)} ·{" "}
        {formatMb(req.requestedStorageMb)} storage
      </span>,
    ],
    [
      "建議 slug",
      req.proposedSlug ? (
        <span key="s" className="font-mono text-sm">
          {req.proposedSlug}
        </span>
      ) : (
        <span className="text-subtle-foreground">未填</span>
      ),
    ],
    [
      "預計成員",
      req.members.length ? (
        <ul key="m" className="space-y-1">
          {req.members.map((m) => (
            <li key={m.email} className="font-mono text-xs">
              {m.email} <span className="font-sans text-muted-foreground">{projectRoleLabel[m.role]}</span>
            </li>
          ))}
        </ul>
      ) : (
        <span className="text-subtle-foreground">無</span>
      ),
    ],
  ];

  return (
    <>
      <PageHeader
        eyebrow={`申請 #${req.id}`}
        title={req.title}
        actions={
          mine && req.status === "rejected" ? (
            <Button variant="outline">
              <Pencil />
              修改並重送
            </Button>
          ) : mine && (req.status === "submitted" || req.status === "in_review") ? (
            <Button variant="outline">
              <Undo2 />
              撤回
            </Button>
          ) : null
        }
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>目的與背景</CardTitle>
            </CardHeader>
            <CardContent className="max-w-prose text-sm whitespace-pre-wrap">{req.purpose}</CardContent>
          </Card>
          <Card className="gap-0 p-0">
            <dl className="divide-y divide-border">
              {fields.map(([k, v]) => (
                <div key={k} className="grid gap-1 px-5 py-3 sm:grid-cols-[140px_1fr] sm:items-start">
                  <dt className="text-label">{k}</dt>
                  <dd className="text-sm">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
          {req.reviewNote ? (
            <Card
              className={
                req.status === "rejected" ? "border-destructive/30 bg-destructive/5" : "border-success/30 bg-success/5"
              }
            >
              <CardHeader>
                <CardTitle className="text-sm">審核意見</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">{req.reviewNote}</CardContent>
            </Card>
          ) : null}
          <section className="space-y-3">
            <h2 className="text-lg font-semibold tracking-tight">審核往返</h2>
            <CommentThread
              comments={comments}
              currentUser={user}
              placeholder={admin ? "要求補件或說明審核意見…" : "回覆管理員…"}
            />
          </section>
        </div>
        <aside className="space-y-4">
          <Card className="gap-0 p-0">
            <dl className="divide-y divide-border">
              <div className="flex items-center justify-between px-4 py-2.5">
                <dt className="text-label">狀態</dt>
                <dd>
                  <StatusBadge status={req.status} />
                </dd>
              </div>
              <div className="flex items-center justify-between px-4 py-2.5">
                <dt className="text-label">申請人</dt>
                <dd>
                  <UserInline user={req.applicant} />
                </dd>
              </div>
              <div className="flex items-center justify-between px-4 py-2.5">
                <dt className="text-label">審核人</dt>
                <dd>
                  {req.reviewer ? (
                    <UserInline user={req.reviewer} />
                  ) : (
                    <span className="text-sm text-subtle-foreground">尚未指派</span>
                  )}
                </dd>
              </div>
              <div className="flex items-center justify-between px-4 py-2.5">
                <dt className="text-label">送出</dt>
                <dd className="font-mono text-xs" title={formatDateTime(req.submittedAt)}>
                  {formatRelative(req.submittedAt)}
                </dd>
              </div>
              {req.reviewedAt ? (
                <div className="flex items-center justify-between px-4 py-2.5">
                  <dt className="text-label">審核</dt>
                  <dd className="font-mono text-xs">{formatRelative(req.reviewedAt)}</dd>
                </div>
              ) : null}
              {req.projectSlug ? (
                <div className="flex items-center justify-between px-4 py-2.5">
                  <dt className="text-label">專案</dt>
                  <dd>
                    <Link
                      href={`/projects/${req.projectSlug}`}
                      className="font-mono text-xs text-brand-ink hover:underline"
                    >
                      {req.projectSlug}
                    </Link>
                  </dd>
                </div>
              ) : null}
            </dl>
          </Card>
          {admin ? <RequestReviewPanel request={req} pool={pool} /> : null}
        </aside>
      </div>
    </>
  );
}

export default function ProjectRequestPage({ params }: PageProps<"/project-requests/[id]">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <RequestDetail params={params} />
    </Suspense>
  );
}
