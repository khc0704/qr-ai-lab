import { Box } from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";
import { FamilyText } from "@/components/features/chips";
import { EmptyState } from "@/components/features/empty-state";
import { TableSkeleton } from "@/components/features/skeletons";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getProject, listArtifacts } from "@/lib/api";
import { RelativeTime } from "@/components/features/time";
import { formatBytes, formatMetric } from "@/lib/format";
import { canProject, isApproved, projectRole } from "@/lib/roles";
import { getCurrentUser } from "@/lib/session";
import { ModelRowActions } from "./model-row-actions";

async function Models({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [project, user] = await Promise.all([getProject(slug), getCurrentUser()]);
  if (!project) notFound();
  if (!isApproved(project)) redirect(`/projects/${project.slug}/application`);
  const models = await listArtifacts(project.slug, "model");
  const role = projectRole(project, user);
  const canSetDefault = canProject(role, "edit");
  const canDelete = canProject(role, "manage");
  if (models.length === 0)
    return (
      <EmptyState
        icon={Box}
        title="還沒有模型"
        description="訓練任務成功後，模型會出現在這裡；設為預設後可用於推論。"
        dots
      />
    );
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>名稱</TableHead>
            <TableHead>家族</TableHead>
            <TableHead>指標</TableHead>
            <TableHead className="text-right">大小</TableHead>
            <TableHead>來源任務</TableHead>
            <TableHead className="text-right">建立</TableHead>
            <TableHead className="w-44" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {models.map((m) => (
            <TableRow key={m.id} className={m.isDefault ? "bg-primary/5" : undefined}>
              <TableCell>
                <span className="font-medium">{m.name}</span>{" "}
                <span className="font-mono text-xs text-muted-foreground">v{m.version}</span>
                {m.isDefault ? (
                  <span className="ml-2 rounded-sm bg-primary/10 px-1.5 text-[11px] text-brand-ink">預設</span>
                ) : null}
              </TableCell>
              <TableCell>
                <FamilyText family={m.modelFamily} />
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground tabular-nums">
                {Object.entries(m.metrics ?? {})
                  .map(([k, v]) => `${k}=${formatMetric(v)}`)
                  .join("  ") || "—"}
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">{formatBytes(m.sizeBytes)}</TableCell>
              <TableCell>
                <Link
                  href={`/projects/${slug}/jobs/${m.jobId}`}
                  className="font-mono text-xs text-brand-ink hover:underline"
                >
                  #{m.jobId}
                </Link>
              </TableCell>
              <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                <RelativeTime iso={m.createdAt} />
              </TableCell>
              <TableCell className="text-right">
                <ModelRowActions
                  id={m.id}
                  name={m.name}
                  isDefault={m.isDefault}
                  slug={project.slug}
                  canSetDefault={canSetDefault}
                  canDelete={canDelete}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function ModelsPage({ params }: PageProps<"/projects/[slug]/models">) {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <Models params={params} />
    </Suspense>
  );
}
