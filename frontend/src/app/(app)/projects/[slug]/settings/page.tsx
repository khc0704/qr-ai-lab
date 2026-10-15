import { notFound } from "next/navigation";
import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { getProject } from "@/lib/api";
import { ProjectSettingsForm } from "./project-settings-form";

async function Settings({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const project = await getProject(slug);
  if (!project) notFound();
  return (
    <ProjectSettingsForm
      name={project.name}
      description={project.description}
      slug={project.slug}
      archived={project.status === "archived"}
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
