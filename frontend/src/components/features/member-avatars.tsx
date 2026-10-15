import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { initials } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { User } from "@/types/domain";

export function UserAvatar({ user, className }: { user: User; className?: string }) {
  return (
    <Avatar className={cn("size-7", className)}>
      <AvatarFallback className={cn("text-[11px]", user.role === "admin" && "ring-1 ring-primary/50")}>
        {initials(user.displayName)}
      </AvatarFallback>
    </Avatar>
  );
}

export function MemberAvatars({ users, max = 4 }: { users: User[]; max?: number }) {
  const shown = users.slice(0, max);
  const rest = users.length - shown.length;
  return (
    <div className="flex items-center -space-x-2">
      {shown.map((u) => (
        <Tooltip key={u.id}>
          <TooltipTrigger asChild>
            <span>
              <UserAvatar user={u} className="ring-2 ring-card" />
            </span>
          </TooltipTrigger>
          <TooltipContent>{u.displayName}</TooltipContent>
        </Tooltip>
      ))}
      {rest > 0 ? (
        <span className="flex size-7 items-center justify-center rounded-full bg-muted font-mono text-[11px] text-muted-foreground ring-2 ring-card">
          +{rest}
        </span>
      ) : null}
    </div>
  );
}

export function UserInline({ user, className }: { user: User; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <UserAvatar user={user} className="size-6" />
      <span className="text-sm">{user.displayName}</span>
    </span>
  );
}
