"use client";

// owner / admin: 結束 (completed) ↔ 重新開啟 (active). Archiving lives in the settings form below it.
import { CircleCheckBig, RotateCcw } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { projectStatusHint } from "@/i18n/zh-TW";
import { completeProjectAction, reopenProjectAction } from "@/lib/actions";
import type { Project } from "@/types/domain";

export function ProjectLifecycleCard({ project, canEdit }: { project: Project; canEdit: boolean }) {
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  if (project.status !== "active" && project.status !== "completed") return null;
  const complete = () =>
    startTransition(async () => {
      const r = await completeProjectAction(project.slug);
      if (!r.ok) toast.error(r.error);
      else toast.success("專案已結束");
      setOpen(false);
    });
  const reopen = () =>
    startTransition(async () => {
      const r = await reopenProjectAction(project.slug);
      if (!r.ok) toast.error(r.error);
      else toast.success("專案已重新開啟");
    });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{project.status === "active" ? "結束專案" : "重新開啟專案"}</CardTitle>
        <CardDescription>
          {project.status === "active"
            ? "結束後不再接受新任務，產物、log 與儲存用量保留；擁有者或管理員可以重新開啟。"
            : projectStatusHint.completed}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {project.status === "active" ? (
          <Button variant="outline" disabled={!canEdit || pending} onClick={() => setOpen(true)}>
            <CircleCheckBig />
            結束專案
          </Button>
        ) : (
          <Button variant="outline" disabled={!canEdit || pending} onClick={reopen}>
            <RotateCcw />
            重新開啟
          </Button>
        )}
      </CardContent>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>結束 {project.name}？</AlertDialogTitle>
            <AlertDialogDescription>還有任務在排隊或執行時會被拒絕，請先取消它們。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction disabled={pending} onClick={complete}>
              結束專案
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
