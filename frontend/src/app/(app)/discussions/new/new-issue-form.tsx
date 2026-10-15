"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Send } from "lucide-react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { issueTypeLabel } from "@/i18n/zh-TW";

const schema = z.object({
  type: z.enum(["question", "bug", "feature"]),
  title: z.string().min(4, "至少 4 個字").max(200),
  body: z.string().min(10, "請多描述一些（至少 10 個字）"),
  projectSlug: z.string().optional(),
});

export function NewIssueForm({ projects }: { projects: { slug: string; name: string }[] }) {
  const router = useRouter();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { type: "question", title: "", body: "" },
  });
  return (
    <Form {...form}>
      <form
        className="mx-auto w-full max-w-2xl space-y-6"
        onSubmit={form.handleSubmit(() => {
          toast.success("已建立問題（接上 backend 後會寫入）");
          router.push("/discussions");
        })}
      >
        <Card>
          <CardHeader>
            <CardTitle>基本</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <FormField
              control={form.control}
              name="type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>類型</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger className="w-48">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {(Object.keys(issueTypeLabel) as (keyof typeof issueTypeLabel)[]).map((k) => (
                        <SelectItem key={k} value={k}>
                          {issueTypeLabel[k]}
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
              name="title"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>標題</FormLabel>
                  <FormControl>
                    <Input placeholder="一句話說明問題" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="body"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>內容</FormLabel>
                  <FormControl>
                    <Textarea rows={8} placeholder="重現步驟、預期結果、實際結果；支援 Markdown" {...field} />
                  </FormControl>
                  <FormDescription>支援 Markdown。</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="projectSlug"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>關聯專案（可選）</FormLabel>
                  <Select value={field.value ?? ""} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger className="w-72">
                        <SelectValue placeholder="不關聯" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {projects.map((p) => (
                        <SelectItem key={p.slug} value={p.slug}>
                          {p.name} <span className="font-mono text-xs text-muted-foreground">{p.slug}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormItem>
              )}
            />
          </CardContent>
        </Card>
        <div className="sticky bottom-0 flex justify-end gap-2 border-t border-border bg-background/80 py-3 backdrop-blur">
          <Button type="button" variant="outline" onClick={() => router.back()}>
            取消
          </Button>
          <Button type="submit">
            <Send />
            建立問題
          </Button>
        </div>
      </form>
    </Form>
  );
}
