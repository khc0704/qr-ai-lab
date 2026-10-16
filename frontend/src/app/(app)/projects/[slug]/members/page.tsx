import { notFound } from "next/navigation";
import { Suspense } from "react";
import { TableSkeleton } from "@/components/features/skeletons";
import { getProject } from "@/lib/api";
import { canProject, projectRole } from "@/lib/roles";
import { getCurrentUser } from "@/lib/session";
import { MembersTable } from "./members-table";

async function Members({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [project, user] = await Promise.all([getProject(slug), getCurrentUser()]);
  if (!project) notFound();
  const canManage = canProject(projectRole(project, user), "manage");
  return <MembersTable slug={project.slug} members={project.members} canManage={canManage} />;
}

export default function MembersPage({ params }: PageProps<"/projects/[slug]/members">) {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <Members params={params} />
    </Suspense>
  );
}
