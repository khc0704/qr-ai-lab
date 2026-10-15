import { FolderKanban } from "lucide-react";
import { EmptyState } from "@/components/features/empty-state";
import { ProjectCard } from "@/components/features/project-card";
import { PageHeader } from "@/components/layout/page-header";
import { listJobs, listProjects } from "@/lib/api";

export default async function ProjectsPage() {
  const [projects, jobs] = await Promise.all([listProjects({ includeArchived: true }), listJobs()]);
  const active = projects.filter((p) => p.status === "active");
  const archived = projects.filter((p) => p.status === "archived");
  return (
    <>
      <PageHeader title="專案" description="你有權限的專案。新專案請透過「專案申請」建立。" />
      {active.length === 0 ? (
        <EmptyState icon={FolderKanban} title="沒有專案" dots />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {active.map((p) => (
            <ProjectCard key={p.id} project={p} latestJob={jobs.find((j) => j.projectId === p.id)} />
          ))}
        </div>
      )}
      {archived.length ? (
        <section className="space-y-3">
          <h2 className="text-label">已封存</h2>
          <div className="grid gap-4 opacity-70 md:grid-cols-2 xl:grid-cols-3">
            {archived.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}
