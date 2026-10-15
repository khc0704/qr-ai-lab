"use client";

import { Download, Star } from "lucide-react";
import { useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { setDefaultArtifactAction } from "@/lib/actions";

export function ArtifactRowActions({
  id,
  slug,
  kind,
  isDefault,
}: {
  id: number;
  slug: string;
  kind: string;
  isDefault: boolean;
}) {
  const [pending, start] = useTransition();
  return (
    <div className="flex justify-end gap-1">
      {kind === "model" && !isDefault ? (
        <Button
          variant="ghost"
          size="sm"
          disabled={pending}
          onClick={() =>
            start(async () => {
              const r = await setDefaultArtifactAction(id, slug, true);
              if (r.ok) toast.success("已設為專案預設模型");
              else toast.error(r.error);
            })
          }
        >
          <Star />
          設為預設
        </Button>
      ) : null}
      <Button variant="ghost" size="icon-sm" aria-label="下載" asChild>
        <a href={`/api/download/artifacts/${id}/download`} download>
          <Download />
        </a>
      </Button>
    </div>
  );
}
