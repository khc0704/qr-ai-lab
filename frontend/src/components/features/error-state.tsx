"use client";

// Shared body for the route error boundaries (error.tsx files): EmptyState look, retry + home, and the digest
// so a user can quote it when reporting. Error boundaries must be client components.
import { TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { EmptyState } from "@/components/features/empty-state";
import { Button } from "@/components/ui/button";
import { errorCopy } from "@/i18n/zh-TW";

export function ErrorState({
  error,
  retry,
  title = errorCopy.title,
  description = errorCopy.description,
  homeHref = "/",
}: {
  error: Error & { digest?: string };
  retry: () => void;
  title?: string;
  description?: string;
  homeHref?: string;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <EmptyState
      icon={TriangleAlert}
      title={title}
      description={description}
      action={
        <div className="flex flex-col items-center gap-3">
          <div className="flex gap-2">
            <Button onClick={retry}>{errorCopy.retry}</Button>
            <Button variant="outline" asChild>
              <Link href={homeHref}>{errorCopy.home}</Link>
            </Button>
          </div>
          {error.digest ? (
            <span className="font-mono text-xs text-subtle-foreground tabular-nums">
              {errorCopy.digest} {error.digest}
            </span>
          ) : null}
        </div>
      }
    />
  );
}
