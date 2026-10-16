// Prev / next pager for the backend's `{items,total,page,page_size}` lists (DESIGN.md §8.5: bottom right).
// Server-renderable: plain Links, no state. Pages read `?page=` with `pageFromParam` inside their Suspense tree.
import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { pagination as copy } from "@/i18n/zh-TW";
import { cn } from "@/lib/utils";

/** `?page=` as a positive integer; anything else is page 1. */
export function pageFromParam(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 ? n : 1;
}

/** Build `href` for a page while keeping the other query parameters. */
export function pageHref(basePath: string, params: Record<string, string | undefined>, page: number): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) sp.set(k, v);
  if (page > 1) sp.set("page", String(page));
  else sp.delete("page");
  const s = sp.toString();
  return s ? `${basePath}?${s}` : basePath;
}

export function Pagination({
  page,
  pageSize,
  total,
  href,
  className,
}: {
  page: number;
  pageSize: number;
  total: number;
  href: (page: number) => string;
  className?: string;
}) {
  const pages = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
  const current = Math.min(Math.max(1, page), pages);
  if (pages <= 1) return null;
  const nav = (target: number, label: string, Icon: typeof ChevronLeft, disabled: boolean) =>
    disabled ? (
      <Button variant="outline" size="icon-sm" aria-label={label} disabled>
        <Icon />
      </Button>
    ) : (
      <Button variant="outline" size="icon-sm" aria-label={label} asChild>
        <Link href={href(target)} rel={target < current ? "prev" : "next"}>
          <Icon />
        </Link>
      </Button>
    );
  return (
    <nav aria-label="分頁" className={cn("flex items-center justify-end gap-3", className)}>
      <span className="font-mono text-xs text-muted-foreground tabular-nums">
        {copy.summary(current, pages, total)}
      </span>
      <div className="flex items-center gap-1">
        {nav(current - 1, copy.previous, ChevronLeft, current <= 1)}
        {nav(current + 1, copy.next, ChevronRight, current >= pages)}
      </div>
    </nav>
  );
}
