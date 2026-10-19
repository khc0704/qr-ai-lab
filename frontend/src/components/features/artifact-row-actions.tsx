"use client";

import { Download, Star } from "lucide-react";
import { useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { setDefaultArtifactAction } from "@/lib/actions";
import { withBase } from "@/lib/base-path";

export function ArtifactRowActions({
  id,
  slug,
  kind,
  isDefault,
  canSetDefault = true,
}: {
  id: number;
  slug: string;
  kind: string;
  isDefault: boolean;
  /** Project role `edit` (member+); viewers only download. */
  canSetDefault?: boolean;
}) {
  const [pending, start] = useTransition();
  return (
    <div className="flex justify-end gap-1">
      {kind === "model" && !isDefault && canSetDefault ? (
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
        <a href={withBase(`/api/download/artifacts/${id}/download`)} download>
          <Download />
        </a>
      </Button>
    </div>
  );
}
