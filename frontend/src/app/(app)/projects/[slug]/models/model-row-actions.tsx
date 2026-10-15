"use client";

import { Download, Star, Trash2 } from "lucide-react";
import { useState } from "react";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function ModelRowActions({ id, name, isDefault }: { id: number; name: string; isDefault: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex justify-end gap-1">
      {!isDefault ? (
        <Button variant="ghost" size="sm" onClick={() => toast.success(`已將 ${name} 設為預設模型`)}>
          <Star />
          設為預設
        </Button>
      ) : null}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="下載"
            onClick={() => toast.message("下載（接上 backend 後啟用）")}
          >
            <Download />
          </Button>
        </TooltipTrigger>
        <TooltipContent>下載</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label="刪除" onClick={() => setOpen(true)}>
            <Trash2 />
          </Button>
        </TooltipTrigger>
        <TooltipContent>刪除</TooltipContent>
      </Tooltip>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>刪除模型 {name}？</AlertDialogTitle>
            <AlertDialogDescription>
              檔案會從專案資料夾移除並釋放配額；引用它的推論紀錄需先刪除。此操作無法復原。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => toast.success(`已刪除模型 #${id}`)}
            >
              刪除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
