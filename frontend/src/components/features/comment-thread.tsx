"use client";

import { Pencil, Save, Send } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Markdown } from "@/components/features/markdown";
import { MarkdownEditor } from "@/components/features/markdown-editor";
import { UserAvatar } from "@/components/features/member-avatars";
import { RelativeTime } from "@/components/features/time";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { common, discussionCopy } from "@/i18n/zh-TW";
import { addCommentAction, updateCommentAction } from "@/lib/actions";
import { isEdited } from "@/lib/format";
import { isAdminRole } from "@/lib/roles";
import type { Comment, User } from "@/types/domain";

export function CommentThread({
  comments,
  currentUser,
  target,
  targetId,
  placeholder = discussionCopy.composerPlaceholder,
  composer = true,
  editable = true,
}: {
  comments: Comment[];
  currentUser: User;
  /** "application" = the review thread of a project's application; `targetId` is then the project slug. */
  target: "issue" | "application";
  targetId: number | string;
  placeholder?: string;
  /** Show the reply box (the issue page hides it while the thread body is being edited). */
  composer?: boolean;
  /** Allow inline editing of comments (issues only: the backend has no edit endpoint for application comments). */
  editable?: boolean;
}) {
  const [text, setText] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, startTransition] = useTransition();
  const admin = isAdminRole(currentUser.role);
  const canEdit = (c: Comment) =>
    editable && target === "issue" && c.kind === "comment" && (admin || c.author?.id === currentUser.id);

  const send = () =>
    startTransition(async () => {
      const r = await addCommentAction(target, targetId, text.trim());
      if (!r.ok) toast.error(r.error);
      else setText("");
    });
  const startEdit = (c: Comment) => {
    setDraft(c.body);
    setEditingId(c.id);
  };
  const saveEdit = (c: Comment) =>
    startTransition(async () => {
      const r = await updateCommentAction(Number(targetId), c.id, draft.trim());
      if (!r.ok) toast.error(r.error);
      else {
        toast.success(discussionCopy.commentUpdated);
        setEditingId(null);
      }
    });

  return (
    <div className="space-y-4">
      <ol className="relative space-y-4 before:absolute before:top-2 before:bottom-2 before:left-[13px] before:w-px before:bg-border">
        {comments.map((c) =>
          c.kind === "system" ? (
            <li key={c.id} className="relative flex items-center gap-3 pl-9">
              <span className="absolute left-[9px] size-2.5 rounded-full border-2 border-card bg-border-strong" />
              <span className="text-label tracking-normal normal-case">{c.body}</span>
              <RelativeTime iso={c.createdAt} className="font-mono text-[11px] text-subtle-foreground" />
            </li>
          ) : (
            <li key={c.id} className="relative flex gap-3">
              {c.author ? <UserAvatar user={c.author} className="relative z-10 ring-4 ring-background" /> : null}
              <Card className="flex-1 gap-2 p-4">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-medium">{c.author?.displayName}</span>
                  {isAdminRole(c.author?.role) ? (
                    <span className="rounded-sm bg-primary/10 px-1.5 text-[11px] font-medium text-brand-ink">
                      {discussionCopy.adminTag}
                    </span>
                  ) : null}
                  <RelativeTime iso={c.createdAt} className="font-mono text-[11px] text-subtle-foreground" />
                  {c.updatedAt && isEdited(c.createdAt, c.updatedAt) ? (
                    <span className="font-mono text-[11px] text-subtle-foreground">
                      · {discussionCopy.edited} <RelativeTime iso={c.updatedAt} />
                    </span>
                  ) : null}
                  {canEdit(c) && editingId === null ? (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          className="ml-auto text-muted-foreground"
                          aria-label={discussionCopy.editComment}
                          onClick={() => startEdit(c)}
                        >
                          <Pencil />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>{discussionCopy.editComment}</TooltipContent>
                    </Tooltip>
                  ) : null}
                </div>
                {editingId === c.id ? (
                  <div className="space-y-2">
                    <MarkdownEditor
                      value={draft}
                      onChange={setDraft}
                      minRows={4}
                      aria-label={discussionCopy.editComment}
                    />
                    <div className="flex justify-end gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={pending}
                        onClick={() => setEditingId(null)}
                      >
                        {common.cancel}
                      </Button>
                      <Button type="button" size="sm" disabled={!draft.trim() || pending} onClick={() => saveEdit(c)}>
                        <Save />
                        {common.save}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <Markdown source={c.body} />
                )}
              </Card>
            </li>
          ),
        )}
      </ol>
      {composer && editingId === null ? (
        <div className="flex gap-3">
          <UserAvatar user={currentUser} />
          <div className="flex-1 space-y-2">
            <MarkdownEditor
              value={text}
              onChange={setText}
              placeholder={placeholder}
              minRows={4}
              aria-label={discussionCopy.composer}
            />
            <div className="flex justify-end">
              <Button size="sm" disabled={!text.trim() || pending} onClick={send}>
                <Send />
                {discussionCopy.send}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
