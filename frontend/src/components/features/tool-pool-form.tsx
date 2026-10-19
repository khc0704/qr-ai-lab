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
import { cn } from "@/lib/utils";
import type { ResourcePool, ToolPool } from "@/types/domain";

const FIELDS: { key: keyof ToolPool; label: string; step?: number; min?: number }[] = [
  { key: "gpuLimit", label: "GPU" },
  { key: "cpuLimit", label: "CPU 核數", step: 0.5, min: 0.5 },
  { key: "memoryLimitMb", label: "記憶體（MB）", step: 1024, min: 256 },
  { key: "storageQuotaMb", label: "儲存（MB）", step: 512, min: 64 },
  { key: "maxConcurrentJobs", label: "同時任務數（整池）", min: 1 },
  { key: "maxJobsPerUser", label: "每人同時任務數", min: 1 },
  { key: "resultTtlHours", label: "結果保留（小時）", min: 1 },
];

/** The tool pool is a slice of the total resource pool: these fields can never exceed it (the backend rejects). */
export function toolPoolCaps(pool: ResourcePool): Partial<Record<keyof ToolPool, number>> {
  return {
    gpuLimit: pool.gpuIndices.length,
    cpuLimit: pool.cpuCores,
    memoryLimitMb: pool.memoryMb,
    maxConcurrentJobs: pool.maxRunningJobs,
  };
}

export function ToolPoolForm({
  pool,
  resourcePool,
  readOnly = false,
}: {
  pool: ToolPool;
  resourcePool: ResourcePool;
  readOnly?: boolean;
}) {
  const [v, setV] = useState(pool);
  const [pending, startTransition] = useTransition();
  const caps = toolPoolCaps(resourcePool);
  const over = FIELDS.filter((f) => caps[f.key] !== undefined && v[f.key] > (caps[f.key] as number));
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
        {FIELDS.map((f) => {
          const cap = caps[f.key];
          const exceeds = cap !== undefined && v[f.key] > cap;
          return (
            <div key={f.key} className="grid gap-1">
              <Label htmlFor={`tool-${f.key}`} className="text-xs">
                {f.label}
                {cap !== undefined ? (
                  <span className="ml-1 font-mono text-[11px] font-normal text-muted-foreground tabular-nums">
                    ≤ {cap}
                  </span>
                ) : null}
              </Label>
              <Input
                id={`tool-${f.key}`}
                type="number"
                step={f.step}
                min={f.min ?? 0}
                max={cap}
                aria-invalid={exceeds || undefined}
                className={cn("text-right font-mono", exceeds && "border-destructive")}
                value={v[f.key]}
                onChange={(e) => setV({ ...v, [f.key]: Number(e.target.value) })}
              />
            </div>
          );
        })}
      </fieldset>
      {over.length ? (
        <p className="text-xs text-destructive" data-testid="tool-pool-over">
          超過總資源池：{over.map((f) => f.label).join("、")}。工具池是總資源池的一部分，不能比它大。
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          工具池佔總資源池的一部分（GPU {resourcePool.gpuIndices.length}、CPU {resourcePool.cpuCores} 核、記憶體{" "}
          {Math.round(resourcePool.memoryMb / 1024)} GB、同時 {resourcePool.maxRunningJobs}{" "}
          個任務）；調低總池時工具池會跟著縮。
        </p>
      )}
      {readOnly ? null : (
        <Button size="sm" disabled={!dirty || pending || over.length > 0} onClick={save} data-testid="save-tool-pool">
          <Save />
          儲存工具池配額
        </Button>
      )}
    </div>
  );
}
