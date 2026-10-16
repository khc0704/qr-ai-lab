import { Database, Info, Plus } from "lucide-react";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { SourceKindChip } from "@/components/features/chips";
import { EmptyState } from "@/components/features/empty-state";
import { UserInline } from "@/components/features/member-avatars";
import { TableSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { RelativeTime } from "@/components/features/time";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { dataFormatLabel, jobCopy } from "@/i18n/zh-TW";
import { getProject, listDataSources } from "@/lib/api";
import { canProject, projectRole } from "@/lib/roles";
import { getCurrentUser } from "@/lib/session";
import { NewDataSourceDialog } from "./new-data-source-dialog";
import { SourceRowActions } from "./source-row-actions";

async function Sources({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [project, user] = await Promise.all([getProject(slug), getCurrentUser()]);
  if (!project) notFound();
  const sources = await listDataSources(project.slug);
  const canEdit = canProject(projectRole(project, user), "edit");
  return (
    <>
      <Alert>
        <Info />
        <AlertDescription>{jobCopy.dataSourceNotice}</AlertDescription>
      </Alert>
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs text-muted-foreground tabular-nums">{sources.length} 個資料來源</span>
        {canEdit ? (
          <NewDataSourceDialog
            slug={project.slug}
            trigger={
              <Button size="sm">
                <Plus />
                新增資料來源
              </Button>
            }
          />
        ) : (
          <span className="text-xs text-muted-foreground">檢視者無法新增資料來源</span>
        )}
      </div>
      {sources.length === 0 ? (
        <EmptyState
          icon={Database}
          title="還沒有資料來源"
          description="新增你的 MinIO 路徑或 URL，建立任務時就能直接選用。"
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名稱</TableHead>
                <TableHead>種類</TableHead>
                <TableHead>位置</TableHead>
                <TableHead>格式</TableHead>
                <TableHead>最近檢查</TableHead>
                <TableHead>建立者</TableHead>
                <TableHead className="w-28" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell>
                    <SourceKindChip kind={s.kind} />
                  </TableCell>
                  <TableCell
                    className="max-w-xs truncate font-mono text-xs text-muted-foreground"
                    title={s.kind === "minio" ? `${s.endpoint}/${s.bucket}/${s.objectPath}` : s.url}
                  >
                    {s.kind === "minio" ? `${s.bucket}/${s.objectPath}` : s.url}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{dataFormatLabel[s.format]}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={s.lastCheckOk == null ? "pending" : s.lastCheckOk ? "ok" : "error"} />
                      <span className="text-xs text-muted-foreground">{s.lastCheckMessage}</span>
                      {s.lastCheckedAt ? (
                        <RelativeTime iso={s.lastCheckedAt} className="font-mono text-[11px] text-subtle-foreground" />
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <UserInline user={s.createdBy} />
                  </TableCell>
                  <TableCell className="text-right">
                    <SourceRowActions slug={project.slug} id={s.id} name={s.name} canEdit={canEdit} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}

export default function DataSourcesPage({ params }: PageProps<"/projects/[slug]/data-sources">) {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <Sources params={params} />
    </Suspense>
  );
}
