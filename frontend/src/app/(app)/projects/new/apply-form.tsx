"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { BookOpen, Send, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { MarkdownEditor } from "@/components/features/markdown-editor";
import { UserPicker } from "@/components/features/user-picker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { dataScaleLabel, dataTypeLabel, projectRoleLabel, taskTypeLabel } from "@/i18n/zh-TW";
import { applyProjectAction, updateApplicationAction } from "@/lib/actions";
import { applicationFormSchema } from "@/lib/schemas";
import { formatMb } from "@/lib/format";
import type { DataScale, DataType, Project, ProjectRole, TaskType, UserLookup } from "@/types/domain";

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

const schema = applicationFormSchema.extend({
  members: z.array(
    z.object({
      email: z.string().email("請從清單選擇使用者"),
      role: z.enum(["maintainer", "member", "viewer"]),
      displayName: z.string().optional(),
      userId: z.number().optional(),
    }),
  ),
});
type Values = z.infer<typeof schema>;

/** Apply for a new project, or (with `initial`) edit a pending / rejected application and resubmit it. */
export function ApplyForm({
  poolGpu,
  poolCpu,
  poolMemoryMb,
  initial,
}: {
  poolGpu: number;
  poolCpu: number;
  poolMemoryMb: number;
  initial?: Project;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const app = initial?.application;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: initial?.name ?? "",
      purpose: app?.purpose ?? "",
      dataType: initial?.dataType ?? "TABULAR",
      taskType: initial?.taskType ?? "classification",
      dataScale: app?.dataScale ?? "small",
      dataDescription: app?.dataDescription ?? "",
      requestedGpu: app?.requestedGpu ?? 0,
      requestedCpu: app?.requestedCpu ?? 2,
      requestedMemoryMb: app?.requestedMemoryMb ?? 4096,
      requestedStorageMb: app?.requestedStorageMb ?? 10240,
      proposedSlug: "",
      members: (app?.members ?? []).filter((m) => m.role !== "owner") as Values["members"],
    },
  });
  const members = useFieldArray({ control: form.control, name: "members" });
  const dataType = useWatch({ control: form.control, name: "dataType" });
  const chosen = useWatch({ control: form.control, name: "members" });
  const num = (field: { onChange: (v: number) => void }) => (e: React.ChangeEvent<HTMLInputElement>) =>
    field.onChange(Number(e.target.value));

  const submit = (v: Values) =>
    startTransition(async () => {
      const body = {
        title: v.title,
        purpose: v.purpose,
        data_type: v.dataType,
        task_type: v.taskType,
        data_scale: v.dataScale,
        data_description: v.dataDescription || null,
        requested_gpu: v.requestedGpu,
        requested_cpu: v.requestedCpu,
        requested_memory_mb: v.requestedMemoryMb,
        requested_storage_mb: v.requestedStorageMb,
        proposed_slug: initial ? null : v.proposedSlug || null,
        members: v.members.map((m) => ({ email: m.email, role: m.role })),
      };
      const r = initial ? await updateApplicationAction(initial.slug, body) : await applyProjectAction(body);
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      toast.success(initial ? "申請已更新並重新送出" : `申請已送出，專案 ${r.data.slug} 等待管理員審核`);
      router.push(`/projects/${r.data.slug}/application`);
    });

  return (
    <Form {...form}>
      <form className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]" onSubmit={form.handleSubmit(submit)}>
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>題目與目的</CardTitle>
              <CardDescription>管理員依這裡判斷專案是否成立；目的與背景支援 Markdown。</CardDescription>
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
                      <MarkdownEditor
                        name={field.name}
                        minRows={12}
                        placeholder="要解決什麼問題、現況指標、期望達到的目標"
                        value={field.value}
                        onChange={field.onChange}
                        ref={field.ref}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="dataDescription"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>資料描述</FormLabel>
                    <FormControl>
                      <Textarea
                        rows={4}
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
              <CardTitle>資源需求</CardTitle>
              <CardDescription>
                目前總資源池：
                <span className="font-mono text-foreground tabular-nums">
                  {poolGpu} GPU · {poolCpu} CPU · {formatMb(poolMemoryMb)}
                </span>
                ；申請量不得超過。核准時管理員會據此設定專案配額。
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
        </div>

        <aside className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div className="space-y-1">
                <CardTitle>資料與任務</CardTitle>
                <CardDescription>不確定怎麼選？看 SOP。</CardDescription>
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
            <CardContent className="grid gap-4">
              <FormField
                control={form.control}
                name="dataType"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>資料類型</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className="w-full">
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
                        <SelectTrigger className="w-full">
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
                        <SelectTrigger className="w-full">
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
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>成員{initial ? "" : "與 slug"}</CardTitle>
              <CardDescription>申請人自動成為擁有者；成員在核准時加入，之後可在「成員」分頁調整。</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              {initial ? null : (
                <FormField
                  control={form.control}
                  name="proposedSlug"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>建議 slug（可選）</FormLabel>
                      <FormControl>
                        <Input placeholder="lowercase-with-dashes" className="font-mono" {...field} />
                      </FormControl>
                      <FormDescription>用於網址與專案資料夾名稱；留空由題目產生。</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
              <div className="space-y-2">
                <FormLabel>預計成員</FormLabel>
                {members.fields.map((m, i) => (
                  <div key={m.id} className="flex items-start gap-2">
                    <div className="min-w-0 flex-1 rounded-md border border-border px-2 py-1.5 text-sm">
                      <div className="truncate">{chosen?.[i]?.displayName || chosen?.[i]?.email}</div>
                      <div className="truncate font-mono text-[11px] text-subtle-foreground">{chosen?.[i]?.email}</div>
                    </div>
                    <FormField
                      control={form.control}
                      name={`members.${i}.role`}
                      render={({ field }) => (
                        <FormItem>
                          <Select value={field.value} onValueChange={field.onChange}>
                            <FormControl>
                              <SelectTrigger className="w-28">
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
                <UserPicker
                  value={null}
                  placeholder="輸入帳號或姓名加入成員…"
                  excludeIds={(chosen ?? []).map((m) => m.userId ?? -1)}
                  onChange={(u: UserLookup | null) => {
                    if (!u) return;
                    if ((chosen ?? []).some((m) => m.email === u.email)) return;
                    members.append({ email: u.email, role: "member", displayName: u.displayName, userId: u.id });
                  }}
                />
              </div>
            </CardContent>
          </Card>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => router.back()}>
              取消
            </Button>
            <Button type="submit" disabled={pending} data-testid="submit-application">
              <Send />
              {initial ? "重新送出申請" : "送出申請"}
            </Button>
          </div>
        </aside>
      </form>
    </Form>
  );
}
