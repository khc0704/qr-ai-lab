import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { ProjectLifecycleCard } from "@/components/features/project-lifecycle-card";
import { ProjectQuotaForm } from "@/components/features/project-quota-form";
import { getProject, getResourcePool } from "@/lib/api";
import { canProject, isApproved, projectRole } from "@/lib/roles";
import { can, getCurrentUser } from "@/lib/session";
import { ProjectSettingsForm } from "./project-settings-form";

async function Settings({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [project, user] = await Promise.all([getProject(slug), getCurrentUser()]);
  if (!project) notFound();
  if (!isApproved(project)) redirect(`/projects/${project.slug}/application`);
  const canEdit = canProject(projectRole(project, user), "settings");
  const pool = can(user, "quota.manage") ? await getResourcePool() : null;
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      {pool ? <ProjectQuotaForm project={project} pool={pool} /> : null}
      <ProjectLifecycleCard project={project} canEdit={canEdit} />
      <ProjectSettingsForm
        name={project.name}
        description={project.description}
        slug={project.slug}
        archived={project.status === "archived"}
        canEdit={canEdit}
        canDelete={can(user, "projects.delete")}
      />
    </div>
  );
}

export default function SettingsPage({ params }: PageProps<"/projects/[slug]/settings">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Settings params={params} />
    </Suspense>
  );
}
