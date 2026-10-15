import { notFound } from "next/navigation";
import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { getProject, listArtifacts, listDataSources } from "@/lib/api";
import { NewJobWizard } from "./new-job-wizard";

async function Wizard({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ kind?: string }>;
}) {
  const [{ slug }, sp] = await Promise.all([params, searchParams]);
  const project = await getProject(slug);
  if (!project) notFound();
  const [sources, models] = await Promise.all([listDataSources(project.id), listArtifacts(project.id, "model")]);
  return (
    <NewJobWizard
      kind={sp.kind === "inference" ? "inference" : "train"}
      project={{
        slug: project.slug,
        dataType: project.dataType,
        taskType: project.taskType,
        gpuLimit: project.gpuLimit,
        cpuLimit: project.cpuLimit,
        memoryLimitMb: project.memoryLimitMb,
      }}
      sources={sources.map((s) => ({ id: s.id, name: s.name, kind: s.kind, format: s.format, ok: s.lastCheckOk }))}
      models={models.map((m) => ({
        id: m.id,
        name: m.name,
        version: m.version,
        family: m.modelFamily,
        isDefault: m.isDefault,
      }))}
    />
  );
}

export default function NewJobPage({ params, searchParams }: PageProps<"/projects/[slug]/jobs/new">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Wizard params={params} searchParams={searchParams} />
    </Suspense>
  );
}
