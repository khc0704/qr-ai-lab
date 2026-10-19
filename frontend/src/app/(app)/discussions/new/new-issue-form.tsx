"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Send } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { MarkdownEditor } from "@/components/features/markdown-editor";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { common, discussionCopy, issueTypeLabel } from "@/i18n/zh-TW";
import { createIssueAction } from "@/lib/actions";
import { issueFormSchema, type IssueFormValues } from "@/lib/schemas";
import type { IssueType } from "@/types/domain";

const ISSUE_TYPES = Object.keys(issueTypeLabel) as IssueType[];

/**
 * Full-width two-column form: the title and a tall Markdown editor on the left, the settings (type, related
 * project, submit) and writing guidance for the chosen type on the right. Stacks on narrow screens.
 */
export function NewIssueForm({ projects }: { projects: { slug: string; name: string }[] }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const form = useForm<IssueFormValues>({
    resolver: zodResolver(issueFormSchema),
    defaultValues: { type: "question", title: "", body: "" },
  });
  const type = useWatch({ control: form.control, name: "type" });
  return (
    <Form {...form}>
      <form
        className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]"
        onSubmit={form.handleSubmit((v) =>
          startTransition(async () => {
            const r = await createIssueAction({
              type: v.type,
              title: v.title,
              body: v.body,
              project_slug: v.projectSlug || null,
            });
            if (!r.ok) {
              toast.error(r.error);
              return;
            }
            toast.success(discussionCopy.created(r.data.id));
            router.push(`/discussions/${r.data.id}`);
          }),
        )}
      >
        <Card>
          <CardContent className="grid gap-5">
            <FormField
              control={form.control}
              name="title"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{discussionCopy.fieldTitle}</FormLabel>
                  <FormControl>
                    <Input placeholder={discussionCopy.titlePlaceholder} {...field} />
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
                  <FormLabel>{discussionCopy.fieldBody}</FormLabel>
                  <FormControl>
                    <MarkdownEditor
                      name={field.name}
                      value={field.value}
                      onChange={field.onChange}
                      ref={field.ref}
                      minRows={18}
                      placeholder={discussionCopy.bodyPlaceholder}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>
        <aside className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>{discussionCopy.settings}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <FormField
                control={form.control}
                name="type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{discussionCopy.fieldType}</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {ISSUE_TYPES.map((k) => (
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
                name="projectSlug"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{discussionCopy.fieldProject}</FormLabel>
                    <Select value={field.value ?? ""} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder={discussionCopy.noProject} />
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
              <div className="grid gap-2 pt-2">
                <Button type="submit" disabled={pending}>
                  <Send />
                  {discussionCopy.create}
                </Button>
                <Button type="button" variant="outline" disabled={pending} onClick={() => router.back()}>
                  {common.cancel}
                </Button>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{discussionCopy.guidanceTitle}</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="list-disc space-y-1.5 pl-4 text-sm text-muted-foreground">
                {discussionCopy.guidance[type ?? "question"].map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </aside>
      </form>
    </Form>
  );
}
