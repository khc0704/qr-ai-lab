"use client";

// Error boundary for the login group (no app shell): same look, centred on the page.
import { ErrorState } from "@/components/features/error-state";
import { errorCopy } from "@/i18n/zh-TW";

export default function AuthError({
  error,
  retry,
  reset,
}: {
  error: Error & { digest?: string };
  retry?: () => void;
  reset?: () => void;
}) {
  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <div className="w-full max-w-md">
        <ErrorState
          error={error}
          retry={() => (retry ?? reset)?.()}
          title={errorCopy.authTitle}
          description={errorCopy.authDescription}
          homeHref="/login"
        />
      </div>
    </div>
  );
}
