import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { NewIssueForm } from "./new-issue-form";
import { listProjects } from "@/lib/api";

async function NewIssue() {
  const projects = await listProjects();
  return (
    <>
      <PageHeader title="新問題" description="描述問題或建議；若與某個專案有關，可選擇關聯。" />
      <NewIssueForm projects={projects.map((p) => ({ slug: p.slug, name: p.name }))} />
    </>
  );
}

export default function NewIssuePage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <NewIssue />
    </Suspense>
  );
}
