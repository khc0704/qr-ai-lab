"use client";

// superadmin: quota every personal workspace (tool jobs) is created with, and how long a result stays downloadable.
import { Save } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { updateToolDefaultsAction } from "@/lib/actions";
import type { ToolDefaults } from "@/types/domain";

const FIELDS: { key: keyof ToolDefaults; label: string; step?: number }[] = [
  { key: "gpuLimit", label: "GPU" },
  { key: "cpuLimit", label: "CPU 核數", step: 0.5 },
  { key: "memoryLimitMb", label: "記憶體（MB）", step: 1024 },
  { key: "storageQuotaMb", label: "儲存（MB）", step: 512 },
  { key: "maxConcurrentJobs", label: "同時任務數" },
  { key: "resultTtlHours", label: "結果保留（小時）" },
];

export function ToolDefaultsForm({ defaults, readOnly = false }: { defaults: ToolDefaults; readOnly?: boolean }) {
  const [v, setV] = useState(defaults);
  const [pending, startTransition] = useTransition();
  const dirty = JSON.stringify(v) !== JSON.stringify(defaults);
  const save = () =>
    startTransition(async () => {
      const r = await updateToolDefaultsAction(v);
      if (!r.ok) toast.error(r.error);
      else toast.success("工具預設已更新");
    });
  return (
    <div className="space-y-3">
      <fieldset disabled={readOnly} className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {FIELDS.map((f) => (
          <div key={f.key} className="grid gap-1">
            <Label htmlFor={`tool-${f.key}`} className="text-xs">
              {f.label}
            </Label>
            <Input
              id={`tool-${f.key}`}
              type="number"
              step={f.step}
              min={0}
              className="text-right font-mono"
              value={v[f.key]}
              onChange={(e) => setV({ ...v, [f.key]: Number(e.target.value) })}
            />
          </div>
        ))}
      </fieldset>
      {readOnly ? null : (
        <Button size="sm" disabled={!dirty || pending} onClick={save}>
          <Save />
          儲存工具預設
        </Button>
      )}
    </div>
  );
}
