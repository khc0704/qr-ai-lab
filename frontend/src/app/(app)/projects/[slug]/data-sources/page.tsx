import { Database, Info, Plus, RefreshCw } from "lucide-react";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { SourceKindChip } from "@/components/features/chips";
import { EmptyState } from "@/components/features/empty-state";
import { UserInline } from "@/components/features/member-avatars";
import { TableSkeleton } from "@/components/features/skeletons";
import { StatusBadge } from "@/components/features/status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { dataFormatLabel } from "@/i18n/zh-TW";
import { getProject, listDataSources } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { NewDataSourceDialog } from "./new-data-source-dialog";

async function Sources({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const project = await getProject(slug);
  if (!project) notFound();
  const sources = await listDataSources(project.id);
  return (
    <>
      <Alert>
        <Info />
        <AlertDescription>
          本服務不保存資料，只記錄連線資訊；任務執行時由任務容器直接向你的 MinIO / URL
          抓取，結束即刪除副本。一次性上傳請在「新建訓練」中進行。
        </AlertDescription>
      </Alert>
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs text-muted-foreground tabular-nums">{sources.length} 個資料來源</span>
        <NewDataSourceDialog
          trigger={
            <Button size="sm">
              <Plus />
              新增資料來源
            </Button>
          }
        />
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
                      <StatusBadge status={s.lastCheckOk ? "ok" : "error"} />
                      <span className="text-xs text-muted-foreground">{s.lastCheckMessage}</span>
                      {s.lastCheckedAt ? (
                        <span className="font-mono text-[11px] text-subtle-foreground">
                          {formatRelative(s.lastCheckedAt)}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <UserInline user={s.createdBy} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm">
                      <RefreshCw />
                      檢查連線
                    </Button>
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
