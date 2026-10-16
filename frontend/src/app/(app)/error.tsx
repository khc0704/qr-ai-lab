"use client";

// Error boundary for every page inside the app shell (the shell itself keeps rendering). Next.js 16 passes
// `retry` (re-fetch + re-render); `reset` is the older alias and is accepted for compatibility.
import { ErrorState } from "@/components/features/error-state";

export default function AppError({
  error,
  retry,
  reset,
}: {
  error: Error & { digest?: string };
  retry?: () => void;
  reset?: () => void;
}) {
  return <ErrorState error={error} retry={() => (retry ?? reset)?.()} />;
}
