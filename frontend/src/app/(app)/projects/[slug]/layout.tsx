import { Settings2 } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense, type ReactNode } from "react";
import { DataTypeChip, TaskChip } from "@/components/features/chips";
import { MemberAvatars } from "@/components/features/member-avatars";
import { StatusBadge } from "@/components/features/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getProject } from "@/lib/api";
import { ProjectTabs } from "./project-tabs";

async function ProjectHeader({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const project = await getProject(slug);
  if (!project) notFound();
  return (
    <PageHeader
      eyebrow={<span className="font-mono normal-case">{project.slug}</span>}
      title={
        <span className="inline-flex items-center gap-3">
          {project.name}
          <StatusBadge status={project.status} />
        </span>
      }
      description={project.description}
      actions={
        <>
          <MemberAvatars users={project.members.map((m) => m.user)} />
          <Button variant="outline" size="sm" asChild>
            <Link href={`/projects/${project.slug}/settings`}>
              <Settings2 />
              設定
            </Link>
          </Button>
        </>
      }
    >
      <div className="flex flex-wrap gap-1.5">
        <DataTypeChip dataType={project.dataType} />
        <TaskChip taskType={project.taskType} />
      </div>
      <ProjectTabs slug={project.slug} />
    </PageHeader>
  );
}

export default function ProjectLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ slug: string }>;
}) {
  return (
    <>
      <Suspense
        fallback={
          <div className="space-y-3">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-4 w-96" />
            <Skeleton className="h-9 w-full" />
          </div>
        }
      >
        <ProjectHeader params={params} />
      </Suspense>
      {children}
    </>
  );
}
