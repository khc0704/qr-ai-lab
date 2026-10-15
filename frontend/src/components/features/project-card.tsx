import Link from "next/link";
import { DataTypeChip, TaskChip } from "@/components/features/chips";
import { MemberAvatars } from "@/components/features/member-avatars";
import { ResourceMeter } from "@/components/features/resource-meter";
import { StatusBadge } from "@/components/features/status-badge";
import { Card } from "@/components/ui/card";
import { formatBytes, formatMb, formatRelative } from "@/lib/format";
import type { Job, Project } from "@/types/domain";

export function ProjectCard({ project, latestJob }: { project: Project; latestJob?: Job }) {
  return (
    <Link
      href={`/projects/${project.slug}`}
      className="group block rounded-xl focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <Card className="h-full gap-4 p-5 transition-colors group-hover:border-border-strong group-hover:bg-accent/40">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-base font-medium">{project.name}</div>
            <div className="font-mono text-xs text-subtle-foreground">{project.slug}</div>
          </div>
          <StatusBadge status={project.status} />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <DataTypeChip dataType={project.dataType} />
          <TaskChip taskType={project.taskType} />
        </div>
        <div className="grid gap-2">
          <ResourceMeter label="GPU" used={project.usage.gpu} total={project.gpuLimit} compact />
          <ResourceMeter label="CPU" used={project.usage.cpu} total={project.cpuLimit} compact />
          <ResourceMeter
            label="Memory"
            used={project.usage.memoryMb}
            total={project.memoryLimitMb}
            format={formatMb}
            compact
          />
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
          <MemberAvatars users={project.members.map((m) => m.user)} />
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-mono tabular-nums">{formatBytes(project.storageUsedBytes)}</span>
            {latestJob ? (
              <>
                <StatusBadge status={latestJob.status} />
                <span className="font-mono text-[11px] text-subtle-foreground">
                  {formatRelative(latestJob.createdAt)}
                </span>
              </>
            ) : null}
          </div>
        </div>
      </Card>
    </Link>
  );
}
