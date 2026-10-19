import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ApplicationOwnerActions } from "@/components/features/application-owner-actions";
import { ApplicationReviewPanel } from "@/components/features/application-review-panel";
import { DataTypeChip, TaskChip } from "@/components/features/chips";
import { Markdown } from "@/components/features/markdown";
import { CommentThread } from "@/components/features/comment-thread";
import { UserInline } from "@/components/features/member-avatars";
import { PageSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { RelativeTime } from "@/components/features/time";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { dataScaleLabel, projectRoleLabel, projectStatusHint } from "@/i18n/zh-TW";
import { getProject, getResourcePool, listComments } from "@/lib/api";
import { formatMb } from "@/lib/format";
import { getCurrentUser, isAdmin } from "@/lib/session";

async function Application({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [project, user] = await Promise.all([getProject(slug), getCurrentUser()]);
  if (!project || !project.application) notFound();
  const app = project.application;
  const [comments, pool] = await Promise.all([listComments("application", project.slug), getResourcePool()]);
  const admin = isAdmin(user);
  const mine = project.owner.id === user.id;
  const underReview = project.status === "pending" || project.status === "in_review";

  const fields: [string, React.ReactNode][] = [
    ["資料類型", <DataTypeChip key="d" dataType={project.dataType} />],
    ["任務", <TaskChip key="t" taskType={project.taskType} />],
    ["資料量級", dataScaleLabel[app.dataScale]],
    [
      "資料描述",
      app.dataDescription ? (
        <span className="whitespace-pre-wrap">{app.dataDescription}</span>
      ) : (
        <span className="text-subtle-foreground">未填</span>
      ),
    ],
    [
      "資源需求",
      <span key="r" className="font-mono text-sm tabular-nums">
        {app.requestedGpu} GPU · {app.requestedCpu} CPU · {formatMb(app.requestedMemoryMb)} ·{" "}
        {formatMb(app.requestedStorageMb)} storage
      </span>,
    ],
    [
      "預計成員",
      app.members.length ? (
        <ul key="m" className="space-y-1">
          {app.members.map((m) => (
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
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-6">
        {underReview || project.status === "rejected" ? (
          <Alert>
            <AlertTitle>{projectStatusHint[project.status]}</AlertTitle>
            <AlertDescription>
              {project.status === "rejected"
                ? "依審核意見修改後重新送出，管理員會再次審核。"
                : "核准後「資料來源」「任務」「模型」「成員」「設定」分頁才會開放；這裡可以和管理員往返討論。"}
            </AlertDescription>
          </Alert>
        ) : null}
        {mine ? <ApplicationOwnerActions project={project} /> : null}
        <Card>
          <CardHeader>
            <CardTitle>目的與背景</CardTitle>
          </CardHeader>
          <CardContent>
            <Markdown source={app.purpose} className="max-w-prose" />
          </CardContent>
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
        {app.reviewNote ? (
          <Card
            className={
              project.status === "rejected"
                ? "border-destructive/30 bg-destructive/5"
                : "border-success/30 bg-success/5"
            }
          >
            <CardHeader>
              <CardTitle className="text-sm">審核意見</CardTitle>
            </CardHeader>
            <CardContent>
              <Markdown source={app.reviewNote} className="text-sm" />
            </CardContent>
          </Card>
        ) : null}
        <section className="space-y-3">
          <h2 className="text-lg font-semibold tracking-tight">審核往返</h2>
          <CommentThread
            comments={comments}
            currentUser={user}
            target="application"
            targetId={project.slug}
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
                <StatusBadge status={project.status} />
              </dd>
            </div>
            <div className="flex items-center justify-between px-4 py-2.5">
              <dt className="text-label">申請人</dt>
              <dd>
                <UserInline user={project.owner} />
              </dd>
            </div>
            <div className="flex items-center justify-between px-4 py-2.5">
              <dt className="text-label">審核人</dt>
              <dd>
                {app.reviewer ? (
                  <UserInline user={app.reviewer} />
                ) : (
                  <span className="text-sm text-subtle-foreground">尚未指派</span>
                )}
              </dd>
            </div>
            <div className="flex items-center justify-between px-4 py-2.5">
              <dt className="text-label">送出</dt>
              <dd className="font-mono text-xs">
                <RelativeTime iso={app.submittedAt} />
              </dd>
            </div>
            {app.reviewedAt ? (
              <div className="flex items-center justify-between px-4 py-2.5">
                <dt className="text-label">審核</dt>
                <dd className="font-mono text-xs">
                  <RelativeTime iso={app.reviewedAt} />
                </dd>
              </div>
            ) : null}
            {project.approvedAt ? (
              <div className="flex items-center justify-between px-4 py-2.5">
                <dt className="text-label">核准</dt>
                <dd className="font-mono text-xs">
                  <RelativeTime iso={project.approvedAt} />
                </dd>
              </div>
            ) : null}
          </dl>
        </Card>
        {admin ? <ApplicationReviewPanel project={project} pool={pool} /> : null}
      </aside>
    </div>
  );
}

export default function ApplicationPage({ params }: PageProps<"/projects/[slug]/application">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Application params={params} />
    </Suspense>
  );
}
