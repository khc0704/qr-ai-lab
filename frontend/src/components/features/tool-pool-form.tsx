"use client";

// superadmin: quota of the shared tool pool (preprocessing / analysis jobs), the per-user limit and how long a
// result stays downloadable.
import { Save } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { updateToolPoolAction } from "@/lib/actions";
import type { ToolPool } from "@/types/domain";

const FIELDS: { key: keyof ToolPool; label: string; step?: number; min?: number }[] = [
  { key: "gpuLimit", label: "GPU" },
  { key: "cpuLimit", label: "CPU 核數", step: 0.5, min: 0.5 },
  { key: "memoryLimitMb", label: "記憶體（MB）", step: 1024, min: 256 },
  { key: "storageQuotaMb", label: "儲存（MB）", step: 512, min: 64 },
  { key: "maxConcurrentJobs", label: "同時任務數（整池）", min: 1 },
  { key: "maxJobsPerUser", label: "每人同時任務數", min: 1 },
  { key: "resultTtlHours", label: "結果保留（小時）", min: 1 },
];

export function ToolPoolForm({ pool, readOnly = false }: { pool: ToolPool; readOnly?: boolean }) {
  const [v, setV] = useState(pool);
  const [pending, startTransition] = useTransition();
  const dirty = JSON.stringify(v) !== JSON.stringify(pool);
  const save = () =>
    startTransition(async () => {
      const r = await updateToolPoolAction(v);
      if (!r.ok) toast.error(r.error);
      else toast.success("工具池配額已更新");
    });
  return (
    <div className="space-y-3">
      <fieldset disabled={readOnly} className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {FIELDS.map((f) => (
          <div key={f.key} className="grid gap-1">
            <Label htmlFor={`tool-${f.key}`} className="text-xs">
              {f.label}
            </Label>
            <Input
              id={`tool-${f.key}`}
              type="number"
              step={f.step}
              min={f.min ?? 0}
              className="text-right font-mono"
              value={v[f.key]}
              onChange={(e) => setV({ ...v, [f.key]: Number(e.target.value) })}
            />
          </div>
        ))}
      </fieldset>
      {readOnly ? null : (
        <Button size="sm" disabled={!dirty || pending} onClick={save} data-testid="save-tool-pool">
          <Save />
          儲存工具池配額
        </Button>
      )}
    </div>
  );
}
