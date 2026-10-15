"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { BookOpen, Send, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { dataScaleLabel, dataTypeLabel, projectRoleLabel, taskTypeLabel } from "@/i18n/zh-TW";
import { formatMb } from "@/lib/format";
import type { DataScale, DataType, ProjectRole, TaskType } from "@/types/domain";

const sop: Record<DataType, string> = {
  TABULAR:
    "Excel / CSV 表格。預測類別選「分類」，預測數值選「迴歸」。1k 列以下建議線性或隨機森林，1k 列以上 XGBoost 通常最準；不需要 GPU。",
  IMAGE:
    "圖片。分類（良/不良）、物件偵測（框出位置）或分割（像素區域）。每類建議 ≥ 50 張（偵測 ≥ 200 張）；需要 1 張 GPU。",
  SEQUENCE:
    "隨時間變化的訊號。多半只有正常樣本時選「異常偵測」，以 Patch Autoencoder 重建誤差判斷；≥ 500 條序列；GPU 1 張或 CPU 皆可。",
  TEXT: "文字。分類用 BERT 接分類頭；< 300 筆時系統會先用 TF-IDF 基準線；需要 1 張 GPU。",
  SPECTRUM: "一筆樣本一條光譜。處理方式同序列，切 patch 後做異常偵測或迴歸；小資料 CPU 即可。",
};

const schema = z.object({
  title: z.string().min(4, "至少 4 個字").max(200),
  purpose: z.string().min(20, "請說明目的與背景（至少 20 個字）"),
  dataType: z.enum(["TABULAR", "IMAGE", "SEQUENCE", "TEXT", "SPECTRUM"]),
  taskType: z.enum(["classification", "regression", "detection", "segmentation", "anomaly_detection"]),
  dataScale: z.enum(["tiny", "small", "medium", "large"]),
  dataDescription: z.string().optional(),
  requestedGpu: z.number().int().min(0),
  requestedCpu: z.number().min(1),
  requestedMemoryMb: z.number().int().min(1024),
  requestedStorageMb: z.number().int().min(1024),
  proposedSlug: z
    .string()
    .regex(/^[a-z0-9][a-z0-9-]{1,62}$/, "小寫英數與連字號，2–63 字")
    .optional()
    .or(z.literal("")),
  members: z.array(
    z.object({ email: z.string().email("email 格式不正確"), role: z.enum(["maintainer", "member", "viewer"]) }),
  ),
});
type Values = z.infer<typeof schema>;

export function NewRequestForm({
  poolGpu,
  poolCpu,
  poolMemoryMb,
}: {
  poolGpu: number;
  poolCpu: number;
  poolMemoryMb: number;
}) {
  const router = useRouter();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: "",
      purpose: "",
      dataType: "TABULAR",
      taskType: "classification",
      dataScale: "small",
      dataDescription: "",
      requestedGpu: 0,
      requestedCpu: 2,
      requestedMemoryMb: 4096,
      requestedStorageMb: 10240,
      proposedSlug: "",
      members: [],
    },
  });
  const members = useFieldArray({ control: form.control, name: "members" });
  const dataType = useWatch({ control: form.control, name: "dataType" });
  const num = (field: { onChange: (v: number) => void }) => (e: React.ChangeEvent<HTMLInputElement>) =>
    field.onChange(Number(e.target.value));

  return (
    <Form {...form}>
      <form
        className="mx-auto w-full max-w-2xl space-y-6"
        onSubmit={form.handleSubmit(() => {
          toast.success("申請已送出（接上 backend 後會寫入）");
          router.push("/project-requests");
        })}
      >
        <Card>
          <CardHeader>
            <CardTitle>基本</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <FormField
              control={form.control}
              name="title"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>題目</FormLabel>
                  <FormControl>
                    <Input placeholder="例：焊點缺陷分類" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="purpose"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>目的與背景</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={5}
                      placeholder="要解決什麼問題、現況指標、期望達到的目標；支援 Markdown"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div className="space-y-1">
              <CardTitle>資料</CardTitle>
              <CardDescription>不確定怎麼選？開右側 SOP。</CardDescription>
            </div>
            <Sheet>
              <SheetTrigger asChild>
                <Button type="button" variant="outline" size="sm">
                  <BookOpen />
                  SOP
                </Button>
              </SheetTrigger>
              <SheetContent className="w-full sm:max-w-md">
                <SheetHeader>
                  <SheetTitle>如何選資料類型與任務</SheetTitle>
                  <SheetDescription>依你的資料長相選類型；想得到的答案決定任務。</SheetDescription>
                </SheetHeader>
                <div className="space-y-4 px-4 pb-4 text-sm">
                  {(Object.keys(sop) as DataType[]).map((k) => (
                    <div
                      key={k}
                      className={
                        k === dataType
                          ? "rounded-lg border border-primary/40 bg-primary/5 p-3"
                          : "rounded-lg border border-border p-3"
                      }
                    >
                      <div className="mb-1 font-mono text-xs text-brand-ink">
                        {k} · {dataTypeLabel[k]}
                      </div>
                      <p className="text-muted-foreground">{sop[k]}</p>
                    </div>
                  ))}
                </div>
              </SheetContent>
            </Sheet>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <FormField
              control={form.control}
              name="dataType"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>資料類型</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {(Object.keys(dataTypeLabel) as DataType[]).map((k) => (
                        <SelectItem key={k} value={k}>
                          {k} · {dataTypeLabel[k]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="taskType"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>任務</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {(Object.keys(taskTypeLabel) as TaskType[]).map((k) => (
                        <SelectItem key={k} value={k}>
                          {taskTypeLabel[k]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="dataScale"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>資料量級</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {(Object.keys(dataScaleLabel) as DataScale[]).map((k) => (
                        <SelectItem key={k} value={k}>
                          {dataScaleLabel[k]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="dataDescription"
              render={({ field }) => (
                <FormItem className="sm:col-span-2">
                  <FormLabel>資料描述</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={3}
                      placeholder="來源（MinIO / URL / 自行上傳）、格式、欄位或標註方式、數量"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>資源</CardTitle>
            <CardDescription>
              目前總資源池：
              <span className="font-mono text-foreground tabular-nums">
                {poolGpu} GPU · {poolCpu} CPU · {formatMb(poolMemoryMb)}
              </span>
              ；申請量不得超過。
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-4">
            <FormField
              control={form.control}
              name="requestedGpu"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>GPU</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      min={0}
                      max={poolGpu}
                      className="text-right font-mono"
                      {...field}
                      onChange={num(field)}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="requestedCpu"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>CPU 核</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      min={1}
                      max={poolCpu}
                      className="text-right font-mono"
                      {...field}
                      onChange={num(field)}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="requestedMemoryMb"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Memory (MB)</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      step={1024}
                      className="text-right font-mono"
                      {...field}
                      onChange={num(field)}
                    />
                  </FormControl>
                  <FormDescription>{formatMb(field.value || 0)}</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="requestedStorageMb"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Storage (MB)</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      step={1024}
                      className="text-right font-mono"
                      {...field}
                      onChange={num(field)}
                    />
                  </FormControl>
                  <FormDescription>{formatMb(field.value || 0)}</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>成員與 slug</CardTitle>
            <CardDescription>申請人自動成為擁有者。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <FormField
              control={form.control}
              name="proposedSlug"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>建議 slug（可選）</FormLabel>
                  <FormControl>
                    <Input placeholder="lowercase-with-dashes" className="font-mono" {...field} />
                  </FormControl>
                  <FormDescription>用於網址與專案資料夾名稱，管理員可改。</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="space-y-2">
              <FormLabel>預計成員</FormLabel>
              {members.fields.map((m, i) => (
                <div key={m.id} className="flex items-start gap-2">
                  <FormField
                    control={form.control}
                    name={`members.${i}.email`}
                    render={({ field }) => (
                      <FormItem className="flex-1">
                        <FormControl>
                          <Input placeholder="name@example.com" className="font-mono" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name={`members.${i}.role`}
                    render={({ field }) => (
                      <FormItem>
                        <Select value={field.value} onValueChange={field.onChange}>
                          <FormControl>
                            <SelectTrigger className="w-32">
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {(["maintainer", "member", "viewer"] as ProjectRole[]).map((r) => (
                              <SelectItem key={r} value={r}>
                                {projectRoleLabel[r]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </FormItem>
                    )}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="移除成員"
                    onClick={() => members.remove(i)}
                  >
                    <X />
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => members.append({ email: "", role: "member" })}
              >
                新增成員
              </Button>
            </div>
          </CardContent>
        </Card>

        <div className="sticky bottom-0 flex justify-end gap-2 border-t border-border bg-background/80 py-3 backdrop-blur">
          <Button type="button" variant="outline" onClick={() => router.back()}>
            取消
          </Button>
          <Button type="submit">
            <Send />
            送出申請
          </Button>
        </div>
      </form>
    </Form>
  );
}
