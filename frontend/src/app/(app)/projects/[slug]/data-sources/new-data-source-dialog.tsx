"use client";

import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { dataFormatLabel } from "@/i18n/zh-TW";
import type { DataFormat } from "@/types/domain";

export function NewDataSourceDialog({ trigger }: { trigger: ReactNode }) {
  const [open, setOpen] = useState(false);
  const formatSelect = (id: string) => (
    <div className="grid gap-2">
      <Label htmlFor={id}>格式</Label>
      <Select defaultValue="csv">
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(dataFormatLabel) as DataFormat[]).map((f) => (
            <SelectItem key={f} value={f}>
              {dataFormatLabel[f]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>新增資料來源</DialogTitle>
          <DialogDescription>憑證會加密儲存，只在任務容器內使用，不會顯示給任何人。</DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="minio">
          <TabsList className="w-full">
            <TabsTrigger value="minio" className="flex-1">
              MinIO / S3
            </TabsTrigger>
            <TabsTrigger value="url" className="flex-1">
              URL
            </TabsTrigger>
          </TabsList>
          <TabsContent value="minio" className="grid gap-4 pt-4">
            <div className="grid gap-2">
              <Label htmlFor="ds-name">名稱</Label>
              <Input id="ds-name" placeholder="例：line3-camera-2026q3" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="ds-endpoint">Endpoint</Label>
              <Input id="ds-endpoint" className="font-mono" placeholder="https://minio.example.com" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="ds-bucket">Bucket</Label>
                <Input id="ds-bucket" className="font-mono" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ds-path">物件 / 前綴</Label>
                <Input id="ds-path" className="font-mono" placeholder="path/to/data/" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ds-ak">Access key</Label>
                <Input id="ds-ak" type="password" autoComplete="off" className="font-mono" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ds-sk">Secret key</Label>
                <Input id="ds-sk" type="password" autoComplete="off" className="font-mono" />
              </div>
            </div>
            {formatSelect("ds-format-minio")}
          </TabsContent>
          <TabsContent value="url" className="grid gap-4 pt-4">
            <div className="grid gap-2">
              <Label htmlFor="du-name">名稱</Label>
              <Input id="du-name" placeholder="例：mes-yield-export" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="du-url">URL</Label>
              <Input id="du-url" className="font-mono" placeholder="https://…/data.csv" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="du-headers">Headers（可選，每行一個）</Label>
              <Textarea id="du-headers" className="font-mono text-xs" rows={3} placeholder="Authorization: Bearer …" />
            </div>
            {formatSelect("ds-format-url")}
          </TabsContent>
        </Tabs>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            onClick={() => {
              setOpen(false);
              toast.success("已新增資料來源（接上 backend 後會寫入）");
            }}
          >
            儲存並檢查連線
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
