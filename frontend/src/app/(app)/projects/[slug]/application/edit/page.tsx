import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { getCatalog, getProject, getResourcePool } from "@/lib/api";
import { supportedTasks } from "@/lib/catalog";
import { getCurrentUser, isAdmin } from "@/lib/session";
import { ApplyForm } from "../../../new/apply-form";

async function EditApplication({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [project, user, pool, catalog] = await Promise.all([
    getProject(slug),
    getCurrentUser(),
    getResourcePool(),
    getCatalog(),
  ]);
  if (!project || !project.application) notFound();
  if (project.owner.id !== user.id && !isAdmin(user)) notFound();
  if (project.status !== "pending" && project.status !== "rejected") redirect(`/projects/${slug}/application`);
  return (
    <ApplyForm
      poolGpu={pool.gpuIndices.length}
      poolCpu={pool.cpuCores}
      poolMemoryMb={pool.memoryMb}
      tasksByType={supportedTasks(catalog)}
      initial={project}
    />
  );
}

export default function EditApplicationPage({ params }: PageProps<"/projects/[slug]/application/edit">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <EditApplication params={params} />
    </Suspense>
  );
}
