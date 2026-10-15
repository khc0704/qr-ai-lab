"use client";

import { Archive, Save } from "lucide-react";
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export function ProjectSettingsForm({
  name,
  description,
  slug,
  archived,
}: {
  name: string;
  description: string;
  slug: string;
  archived: boolean;
}) {
  const [n, setN] = useState(name);
  const [d, setD] = useState(description);
  const [open, setOpen] = useState(false);
  const dirty = n !== name || d !== description;
  return (
    <div className="mx-auto w-full max-w-2xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>基本</CardTitle>
          <CardDescription>
            slug <span className="font-mono text-foreground">{slug}</span> 建立後不可更改（對應網址與資料夾）。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="p-name">名稱</Label>
            <Input id="p-name" value={n} onChange={(e) => setN(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="p-desc">描述</Label>
            <Textarea id="p-desc" rows={4} value={d} onChange={(e) => setD(e.target.value)} />
          </div>
          <div className="flex justify-end">
            <Button disabled={!dirty} onClick={() => toast.success("已儲存專案設定")}>
              <Save />
              儲存
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card className="border-destructive/30">
        <CardHeader>
          <CardTitle>封存專案</CardTitle>
          <CardDescription>封存後不能建立任務，產物與 log 保留可讀；管理員可解除封存。</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" disabled={archived} onClick={() => setOpen(true)}>
            <Archive />
            {archived ? "已封存" : "封存專案"}
          </Button>
        </CardContent>
      </Card>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>封存 {name}？</AlertDialogTitle>
            <AlertDialogDescription>執行中的任務會先被取消。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => toast.success("專案已封存")}
            >
              封存
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
