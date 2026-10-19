"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Pencil, Save } from "lucide-react";
import { useState, useTransition } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { CommentThread } from "@/components/features/comment-thread";
import { Markdown } from "@/components/features/markdown";
import { MarkdownEditor } from "@/components/features/markdown-editor";
import { UserInline } from "@/components/features/member-avatars";
import { RelativeTime } from "@/components/features/time";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { common, discussionCopy, issueTypeLabel } from "@/i18n/zh-TW";
import { updateIssueAction } from "@/lib/actions";
import { isEdited } from "@/lib/format";
import { issueEditFormSchema, type IssueEditFormValues } from "@/lib/schemas";
import type { Comment, Issue, IssueType, User } from "@/types/domain";

const ISSUE_TYPES = Object.keys(issueTypeLabel) as IssueType[];

/**
 * Left column of the issue page: the Markdown body (view, or an inline edit form for the author / an admin)
 * and the comment thread. While the body is being edited the reply box and comment editing are hidden, so one
 * screen keeps a single primary button.
 */
export function IssueThread({
  issue,
  comments,
  currentUser,
  canEdit,
}: {
  issue: Issue;
  comments: Comment[];
  currentUser: User;
  canEdit: boolean;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <div className="space-y-6">
      {editing ? (
        <IssueEditForm issue={issue} onDone={() => setEditing(false)} />
      ) : (
        <Card className="gap-3">
          <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <UserInline user={issue.author} />
              <RelativeTime iso={issue.createdAt} className="font-mono text-[11px] text-subtle-foreground" />
              {isEdited(issue.createdAt, issue.updatedAt) ? (
                <span className="font-mono text-[11px] text-subtle-foreground">
                  · {discussionCopy.edited} <RelativeTime iso={issue.updatedAt} />
                </span>
              ) : null}
            </div>
            {canEdit ? (
              <Button type="button" variant="outline" size="sm" onClick={() => setEditing(true)}>
                <Pencil />
                {discussionCopy.edit}
              </Button>
            ) : null}
          </CardHeader>
          <CardContent>
            {issue.body.trim() ? (
              <Markdown source={issue.body} className="max-w-prose" />
            ) : (
              <p className="text-sm text-subtle-foreground">{discussionCopy.noBody}</p>
            )}
          </CardContent>
        </Card>
      )}
      {issue.resolutionNote ? (
        <Card className="border-success/30 bg-success/10">
          <CardContent className="text-sm">
            <span className="mr-2 text-label">{discussionCopy.resolution}</span>
            {issue.resolutionNote}
          </CardContent>
        </Card>
      ) : null}
      <CommentThread
        comments={comments}
        currentUser={currentUser}
        target="issue"
        targetId={issue.id}
        composer={!editing}
        editable={!editing}
      />
    </div>
  );
}

function IssueEditForm({ issue, onDone }: { issue: Issue; onDone: () => void }) {
  const [pending, startTransition] = useTransition();
  const form = useForm<IssueEditFormValues>({
    resolver: zodResolver(issueEditFormSchema),
    defaultValues: { type: issue.type, title: issue.title, body: issue.body },
  });
  const submit = (v: IssueEditFormValues) =>
    startTransition(async () => {
      const r = await updateIssueAction(issue.id, { type: v.type, title: v.title, body: v.body });
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      toast.success(discussionCopy.updated);
      onDone();
    });
  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(submit)}>
        <Card>
          <CardContent className="grid gap-4">
            <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_11rem]">
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
            </div>
            <FormField
              control={form.control}
              name="body"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{discussionCopy.fieldBody}</FormLabel>
                  <FormControl>
                    <MarkdownEditor value={field.value} onChange={field.onChange} ref={field.ref} minRows={12} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
          <CardFooter className="justify-end gap-2">
            <Button type="button" variant="outline" disabled={pending} onClick={onDone}>
              {common.cancel}
            </Button>
            <Button type="submit" disabled={pending}>
              <Save />
              {common.save}
            </Button>
          </CardFooter>
        </Card>
      </form>
    </Form>
  );
}
