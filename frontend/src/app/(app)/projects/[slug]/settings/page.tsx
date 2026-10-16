import { notFound } from "next/navigation";
import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { getProject } from "@/lib/api";
import { canProject, projectRole } from "@/lib/roles";
import { can, getCurrentUser } from "@/lib/session";
import { ProjectSettingsForm } from "./project-settings-form";

async function Settings({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [project, user] = await Promise.all([getProject(slug), getCurrentUser()]);
  if (!project) notFound();
  return (
    <ProjectSettingsForm
      name={project.name}
      description={project.description}
      slug={project.slug}
      archived={project.status === "archived"}
      canEdit={canProject(projectRole(project, user), "settings")}
      canDelete={can(user, "projects.delete")}
    />
  );
}

export default function SettingsPage({ params }: PageProps<"/projects/[slug]/settings">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Settings params={params} />
    </Suspense>
  );
}
