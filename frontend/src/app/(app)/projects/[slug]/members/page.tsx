import { notFound } from "next/navigation";
import { Suspense } from "react";
import { TableSkeleton } from "@/components/features/skeletons";
import { getProject } from "@/lib/api";
import { MembersTable } from "./members-table";

async function Members({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const project = await getProject(slug);
  if (!project) notFound();
  return <MembersTable members={project.members} />;
}

export default function MembersPage({ params }: PageProps<"/projects/[slug]/members">) {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <Members params={params} />
    </Suspense>
  );
}
