import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  dots = false,
  className,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  dots?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative flex flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-16 text-center",
        className,
      )}
    >
      {dots ? (
        <div className="pointer-events-none absolute inset-0 rounded-xl bg-dots [mask-image:radial-gradient(ellipse_at_center,black,transparent_70%)]" />
      ) : null}
      <div className="relative flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
        <Icon className="size-6" />
      </div>
      <h3 className="relative mt-4 text-base font-medium">{title}</h3>
      {description ? <p className="relative mt-1 max-w-sm text-sm text-muted-foreground">{description}</p> : null}
      {action ? <div className="relative mt-5">{action}</div> : null}
    </div>
  );
}
