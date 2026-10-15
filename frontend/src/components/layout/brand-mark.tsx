import { cn } from "@/lib/utils";

/** 品牌標誌：橘色方塊 + 幾何 Q。只用 token，SVG 以 currentColor 著色。 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-glow-sm",
        className,
      )}
    >
      <svg
        viewBox="0 0 24 24"
        className="size-5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="7" />
        <path d="M15 15l4.5 4.5" />
        <path d="M9 12h6" />
      </svg>
    </span>
  );
}
