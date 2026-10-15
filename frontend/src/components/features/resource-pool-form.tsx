"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Save } from "lucide-react";
import { useState, useTransition } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ResourceMeter } from "@/components/features/resource-meter";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { updateResourcePoolAction } from "@/lib/actions";
import { formatMb } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { NodeStatus, ResourcePool } from "@/types/domain";

export function ResourcePoolForm({
  pool,
  node,
  readOnly = false,
}: {
  pool: ResourcePool;
  node: NodeStatus;
  readOnly?: boolean;
}) {
  const schema = z.object({
    gpuIndices: z.array(z.number()),
    cpuCores: z.number().int().min(1).max(node.cpuCores, `實體只有 ${node.cpuCores} 核`),
    memoryMb: z
      .number()
      .int()
      .min(1024)
      .max(node.memoryMb, `實體只有 ${formatMb(node.memoryMb)}`),
    maxRunningJobs: z.number().int().min(1).max(64),
    allowBackfill: z.boolean(),
    gpuShare: z.boolean(),
  });
  type Values = z.infer<typeof schema>;
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: pool, mode: "onChange" });
  const [confirm, setConfirm] = useState<Values | null>(null);
  const [pending, startTransition] = useTransition();
  const values = useWatch({ control: form.control });
  const save = () => {
    const v = confirm;
    if (!v) return;
    startTransition(async () => {
      const r = await updateResourcePoolAction(v);
      if (!r.ok) toast.error(r.error);
      else {
        toast.success("資源池已更新");
        form.reset(v);
      }
      setConfirm(null);
    });
  };

  return (
    <Form {...form}>
      <form className="space-y-6" onSubmit={form.handleSubmit((v) => setConfirm(v))}>
        <fieldset disabled={readOnly} className="contents">
          <FormField
            control={form.control}
            name="gpuIndices"
            render={({ field }) => (
              <FormItem>
                <FormLabel>可供實驗室使用的 GPU</FormLabel>
                <FormDescription>未勾選的 GPU 不會被任何任務排程（例如保留給其他團隊）。</FormDescription>
                <div className="grid gap-2 sm:grid-cols-2">
                  {node.gpus.map((g) => {
                    const checked = field.value.includes(g.index);
                    return (
                      <label
                        key={g.index}
                        className={cn(
                          "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors",
                          checked ? "border-primary/50 bg-primary/5" : "border-border hover:bg-accent/40",
                        )}
                      >
                        <Checkbox
                          checked={checked}
                          onCheckedChange={(c) =>
                            field.onChange(
                              c ? [...field.value, g.index].sort() : field.value.filter((i) => i !== g.index),
                            )
                          }
                          className="mt-0.5"
                        />
                        <div className="min-w-0 flex-1 space-y-2">
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="font-mono text-sm">GPU {g.index}</span>
                            <span className="truncate text-xs text-muted-foreground">{g.name}</span>
                          </div>
                          <ResourceMeter
                            label="記憶體"
                            used={g.memoryUsedMb}
                            total={g.memoryTotalMb}
                            format={formatMb}
                            compact
                          />
                          <div className="flex justify-between font-mono text-[11px] text-muted-foreground tabular-nums">
                            <span>使用率 {g.utilization}%</span>
                            <span>{g.jobId ? `任務 #${g.jobId}` : "閒置"}</span>
                          </div>
                        </div>
                      </label>
                    );
                  })}
                </div>
                <FormMessage />
              </FormItem>
            )}
          />
          <div className="grid gap-4 sm:grid-cols-3">
            <FormField
              control={form.control}
              name="cpuCores"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>CPU 核數</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      className="text-right font-mono"
                      {...field}
                      onChange={(e) => field.onChange(Number(e.target.value))}
                    />
                  </FormControl>
                  <FormDescription>實體 {node.cpuCores} 核</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="memoryMb"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Memory (MB)</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      step={1024}
                      className="text-right font-mono"
                      {...field}
                      onChange={(e) => field.onChange(Number(e.target.value))}
                    />
                  </FormControl>
                  <FormDescription>實體 {formatMb(node.memoryMb)}</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="maxRunningJobs"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>最大同時任務數</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      className="text-right font-mono"
                      {...field}
                      onChange={(e) => field.onChange(Number(e.target.value))}
                    />
                  </FormControl>
                  <FormDescription>目前執行中 {node.allocated.runningJobs}</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
          <FormField
            control={form.control}
            name="gpuShare"
            render={({ field }) => (
              <FormItem className="flex items-center justify-between rounded-lg border border-border p-4">
                <div className="space-y-0.5">
                  <FormLabel>依顯存共用 GPU</FormLabel>
                  <FormDescription>
                    任務建立時填了「每張 GPU 需要的顯存」的任務，可以和其他任務共用一張 GPU（以 pynvml
                    讀到的剩餘顯存為準，程序內以 set_per_process_memory_fraction 自我限制）。關閉則一張 GPU
                    一次只給一個任務。
                  </FormDescription>
                </div>
                <FormControl>
                  <Switch checked={field.value} onCheckedChange={field.onChange} aria-label="依顯存共用 GPU" />
                </FormControl>
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="allowBackfill"
            render={({ field }) => (
              <FormItem className="flex items-center justify-between rounded-lg border border-border p-4">
                <div className="space-y-0.5">
                  <FormLabel>允許 backfill</FormLabel>
                  <FormDescription>
                    佇列首位因資源不足無法啟動時，讓後面放得下的任務先跑。關閉則嚴格依序。
                  </FormDescription>
                </div>
                <FormControl>
                  <Switch checked={field.value} onCheckedChange={field.onChange} />
                </FormControl>
              </FormItem>
            )}
          />
          <div className="flex items-center justify-between gap-4 rounded-lg bg-muted/60 p-4">
            <div className="space-y-1 text-xs text-muted-foreground">
              <div>
                目前已配置：
                <span className="font-mono text-foreground tabular-nums">
                  {node.allocated.gpu} GPU · {node.allocated.cpu} CPU · {formatMb(node.allocated.memoryMb)}
                </span>
              </div>
              <div>
                新池總量：
                <span className="font-mono text-foreground tabular-nums">
                  {values.gpuIndices?.length ?? 0} GPU · {values.cpuCores ?? 0} CPU · {formatMb(values.memoryMb || 0)}
                </span>
                ，變更只影響之後啟動的任務。
              </div>
            </div>
            {readOnly ? null : (
              <Button type="submit" disabled={!form.formState.isValid || !form.formState.isDirty}>
                <Save />
                儲存資源池
              </Button>
            )}
          </div>
        </fieldset>
      </form>
      <AlertDialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>更新總資源池？</AlertDialogTitle>
            <AlertDialogDescription>
              GPU {confirm?.gpuIndices.join(", ") || "無"} · {confirm?.cpuCores} CPU ·{" "}
              {formatMb(confirm?.memoryMb ?? 0)} · 最多 {confirm?.maxRunningJobs} 個任務。此操作會寫入稽核紀錄。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction disabled={pending} onClick={save}>
              確認更新
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Form>
  );
}
