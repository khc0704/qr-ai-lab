"use client";

import { Send } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { UserAvatar } from "@/components/features/member-avatars";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { RelativeTime } from "@/components/features/time";
import { addCommentAction } from "@/lib/actions";
import type { Comment, User } from "@/types/domain";

export function CommentThread({
  comments,
  currentUser,
  target,
  targetId,
  placeholder = "留言…",
}: {
  comments: Comment[];
  currentUser: User;
  target: "issue" | "project_request";
  targetId: number;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [pending, startTransition] = useTransition();
  const send = () =>
    startTransition(async () => {
      const r = await addCommentAction(target, targetId, text.trim());
      if (!r.ok) toast.error(r.error);
      else setText("");
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
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-medium">{c.author?.displayName}</span>
                  {c.author?.role === "admin" ? (
                    <span className="rounded-sm bg-primary/10 px-1.5 text-[11px] font-medium text-brand-ink">
                      管理員
                    </span>
                  ) : null}
                  <RelativeTime iso={c.createdAt} className="font-mono text-[11px] text-subtle-foreground" />
                </div>
                <p className="text-sm whitespace-pre-wrap">{c.body}</p>
              </Card>
            </li>
          ),
        )}
      </ol>
      <div className="flex gap-3">
        <UserAvatar user={currentUser} />
        <div className="flex-1 space-y-2">
          <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} rows={3} />
          <div className="flex justify-end">
            <Button size="sm" disabled={!text.trim() || pending} onClick={send}>
              <Send />
              送出
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
