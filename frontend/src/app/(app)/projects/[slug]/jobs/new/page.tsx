import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { isApproved } from "@/lib/roles";
import { getCatalog, getJob, getProject, listArtifacts, listDataSources, listPreprocessOps } from "@/lib/api";
import { modelPreprocessOps } from "@/lib/preprocess-steps";
import { NewJobWizard } from "./new-job-wizard";

async function Wizard({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ kind?: string; from?: string }>;
}) {
  const [{ slug }, sp] = await Promise.all([params, searchParams]);
  const project = await getProject(slug);
  if (!project) notFound();
  if (!isApproved(project)) redirect(`/projects/${project.slug}/application`);
  const [sources, models, catalog, ops, from] = await Promise.all([
    listDataSources(project.slug),
    listArtifacts(project.slug, "model"),
    getCatalog(),
    listPreprocessOps(project.dataType),
    sp.from ? getJob(Number(sp.from)) : undefined,
  ]);
  const cloneKind = from?.kind;
  const kind = sp.kind === "inference" || cloneKind === "inference" ? "inference" : "train";
  // Keyed by kind: switching between ?kind=train and ?kind=inference re-renders this route without remounting,
  // and a step index left over from the longer wizard would outrun the shorter one (blank page, no active step).
  return (
    <NewJobWizard
      key={kind}
      kind={kind}
      project={{
        slug: project.slug,
        dataType: project.dataType,
        taskType: project.taskType,
        gpuLimit: project.gpuLimit,
        cpuLimit: project.cpuLimit,
        memoryLimitMb: project.memoryLimitMb,
        defaultTimeout: project.defaultJobTimeoutMinutes ?? 240,
      }}
      sources={sources.map((s) => ({ id: s.id, name: s.name, kind: s.kind, format: s.format, ok: s.lastCheckOk }))}
      models={models.map((m) => ({
        id: m.id,
        name: m.name,
        version: m.version,
        family: m.modelFamily,
        isDefault: m.isDefault,
        inferenceModes: ((m.metadata?.inference_modes as string[] | undefined) ?? []) as string[],
        preprocess: modelPreprocessOps(m.metadata),
      }))}
      catalog={catalog}
      ops={ops}
      cloneFrom={from && from.projectSlug === project.slug ? from : undefined}
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
