"use client";

import { Save, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { StatusBadge } from "@/components/features/status-badge";
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
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatBytes, formatMb } from "@/lib/format";
import type { ProjectStatus, ResourcePool } from "@/types/domain";

interface Row {
  slug: string;
  name: string;
  status: ProjectStatus;
  gpu: number;
  cpu: number;
  memoryMb: number;
  storageMb: number;
  maxJobs: number;
  usedBytes: number;
}

export function QuotasTable({ rows: initial, pool }: { rows: Row[]; pool: ResourcePool }) {
  const [rows, setRows] = useState(initial);
  const [confirm, setConfirm] = useState(false);
  const dirty = JSON.stringify(rows) !== JSON.stringify(initial);
  const active = rows.filter((r) => r.status === "active");
  const sum = {
    gpu: active.reduce((s, r) => s + r.gpu, 0),
    cpu: active.reduce((s, r) => s + r.cpu, 0),
    memoryMb: active.reduce((s, r) => s + r.memoryMb, 0),
  };
  const over = sum.gpu > pool.gpuIndices.length || sum.cpu > pool.cpuCores || sum.memoryMb > pool.memoryMb;
  const set = (slug: string, key: keyof Row, v: number) =>
    setRows((p) => p.map((r) => (r.slug === slug ? { ...r, [key]: v } : r)));
  const cell = (r: Row, key: "gpu" | "cpu" | "memoryMb" | "storageMb" | "maxJobs", step = 1) => (
    <TableCell className="text-right">
      <Input
        type="number"
        step={step}
        value={r[key]}
        disabled={r.status === "archived"}
        onChange={(e) => set(r.slug, key, Number(e.target.value))}
        className="ml-auto h-8 w-24 text-right font-mono text-xs"
      />
    </TableCell>
  );
  return (
    <div className="space-y-4">
      {over ? (
        <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
          <TriangleAlert className="size-4" />
          進行中專案的配額合計{" "}
          <span className="font-mono tabular-nums">
            {sum.gpu} GPU · {sum.cpu} CPU · {formatMb(sum.memoryMb)}
          </span>{" "}
          超過資源池{" "}
          <span className="font-mono tabular-nums">
            {pool.gpuIndices.length} GPU · {pool.cpuCores} CPU · {formatMb(pool.memoryMb)}
          </span>
          ；排程時以資源池為準。
        </div>
      ) : null}
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>專案</TableHead>
              <TableHead>狀態</TableHead>
              <TableHead className="text-right">GPU</TableHead>
              <TableHead className="text-right">CPU</TableHead>
              <TableHead className="text-right">Memory (MB)</TableHead>
              <TableHead className="text-right">Storage (MB)</TableHead>
              <TableHead className="text-right">同時任務</TableHead>
              <TableHead className="text-right">已用儲存</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.slug}>
                <TableCell>
                  <Link href={`/projects/${r.slug}`} className="font-medium hover:text-brand-ink">
                    {r.name}
                  </Link>{" "}
                  <span className="font-mono text-xs text-subtle-foreground">{r.slug}</span>
                </TableCell>
                <TableCell>
                  <StatusBadge status={r.status} />
                </TableCell>
                {cell(r, "gpu")}
                {cell(r, "cpu")}
                {cell(r, "memoryMb", 1024)}
                {cell(r, "storageMb", 1024)}
                {cell(r, "maxJobs")}
                <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                  {formatBytes(r.usedBytes)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="flex justify-end">
        <Button disabled={!dirty} onClick={() => setConfirm(true)}>
          <Save />
          儲存配額
        </Button>
      </div>
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>更新專案配額？</AlertDialogTitle>
            <AlertDialogDescription>變更會寫入稽核紀錄，並影響之後排程的任務。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction onClick={() => toast.success("配額已更新（接上 backend 後生效）")}>
              確認
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
