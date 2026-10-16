"use client";

import { LoaderCircle } from "lucide-react";
import { useState, useTransition, type ReactNode } from "react";
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
import { dataFormatLabel, jobCopy } from "@/i18n/zh-TW";
import { createDataSourceAction } from "@/lib/actions";
import type { DataFormat } from "@/types/domain";

function parseHeaders(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const i = line.indexOf(":");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
}

export function NewDataSourceDialog({ slug, trigger }: { slug: string; trigger: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"minio" | "url">("minio");
  const [format, setFormat] = useState<DataFormat>("csv");
  const [f, setF] = useState({ name: "", endpoint: "", bucket: "", path: "", ak: "", sk: "", url: "", headers: "" });
  const [pending, startTransition] = useTransition();
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });
  const valid = kind === "minio" ? f.name && f.endpoint && f.bucket && f.path : f.name && f.url;

  const submit = () =>
    startTransition(async () => {
      const body =
        kind === "minio"
          ? {
              name: f.name,
              kind,
              endpoint: f.endpoint,
              bucket: f.bucket,
              object_path: f.path,
              access_key: f.ak || null,
              secret_key: f.sk || null,
              format,
            }
          : { name: f.name, kind, url: f.url, headers: f.headers ? parseHeaders(f.headers) : null, format };
      const r = await createDataSourceAction(slug, body);
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      toast.success("已新增資料來源並檢查連線");
      setOpen(false);
      setF({ name: "", endpoint: "", bucket: "", path: "", ak: "", sk: "", url: "", headers: "" });
    });

  const formatSelect = (id: string) => (
    <div className="grid gap-2">
      <Label htmlFor={id}>格式</Label>
      <Select value={format} onValueChange={(v) => setFormat(v as DataFormat)}>
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(dataFormatLabel) as DataFormat[]).map((x) => (
            <SelectItem key={x} value={x}>
              {dataFormatLabel[x]}
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
          <DialogDescription>{jobCopy.dataSourceCredentials}</DialogDescription>
        </DialogHeader>
        <Tabs value={kind} onValueChange={(v) => setKind(v as "minio" | "url")}>
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
              <Input id="ds-name" placeholder="例：line3-camera-2026q3" value={f.name} onChange={set("name")} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="ds-endpoint">Endpoint</Label>
              <Input
                id="ds-endpoint"
                className="font-mono"
                placeholder="https://minio.example.com"
                value={f.endpoint}
                onChange={set("endpoint")}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="ds-bucket">Bucket</Label>
                <Input id="ds-bucket" className="font-mono" value={f.bucket} onChange={set("bucket")} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ds-path">物件 / 前綴</Label>
                <Input
                  id="ds-path"
                  className="font-mono"
                  placeholder="path/to/data/"
                  value={f.path}
                  onChange={set("path")}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ds-ak">Access key</Label>
                <Input
                  id="ds-ak"
                  type="password"
                  autoComplete="off"
                  className="font-mono"
                  value={f.ak}
                  onChange={set("ak")}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ds-sk">Secret key</Label>
                <Input
                  id="ds-sk"
                  type="password"
                  autoComplete="off"
                  className="font-mono"
                  value={f.sk}
                  onChange={set("sk")}
                />
              </div>
            </div>
            {formatSelect("ds-format-minio")}
          </TabsContent>
          <TabsContent value="url" className="grid gap-4 pt-4">
            <div className="grid gap-2">
              <Label htmlFor="du-name">名稱</Label>
              <Input id="du-name" placeholder="例：mes-yield-export" value={f.name} onChange={set("name")} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="du-url">URL</Label>
              <Input
                id="du-url"
                className="font-mono"
                placeholder="https://…/data.csv"
                value={f.url}
                onChange={set("url")}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="du-headers">Headers（可選，每行一個）</Label>
              <Textarea
                id="du-headers"
                className="font-mono text-xs"
                rows={3}
                placeholder="Authorization: Bearer …"
                value={f.headers}
                onChange={set("headers")}
              />
            </div>
            {formatSelect("ds-format-url")}
          </TabsContent>
        </Tabs>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button onClick={submit} disabled={!valid || pending}>
            {pending ? <LoaderCircle className="animate-spin" /> : null}
            儲存並檢查連線
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
