"use client";

// Last-resort boundary: replaces the root layout when it (or a provider) throws, so it must render its own
// <html>/<body> and pull in the global stylesheet itself (the root layout is gone at this point).
import { TriangleAlert } from "lucide-react";
import Link from "next/link";
import { errorCopy } from "@/i18n/zh-TW";
import "./globals.css";

export default function GlobalError({
  error,
  retry,
  reset,
}: {
  error: Error & { digest?: string };
  retry?: () => void;
  reset?: () => void;
}) {
  return (
    <html lang="zh-Hant" className="dark h-full">
      <head>
        <title>{errorCopy.globalTitle}</title>
      </head>
      <body className="flex min-h-full flex-col items-center justify-center gap-4 bg-background p-6 text-center text-foreground">
        <div className="flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
          <TriangleAlert className="size-6" />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">{errorCopy.globalTitle}</h1>
        <p className="max-w-sm text-sm text-muted-foreground">{errorCopy.globalDescription}</p>
        {error.digest ? (
          <p className="font-mono text-xs text-subtle-foreground tabular-nums">
            {errorCopy.digest} {error.digest}
          </p>
        ) : null}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => (retry ?? reset)?.()}
            className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            {errorCopy.retry}
          </button>
          <Link
            href="/"
            className="inline-flex h-9 items-center rounded-md border border-input bg-background px-4 text-sm font-medium hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            {errorCopy.home}
          </Link>
        </div>
      </body>
    </html>
  );
}
