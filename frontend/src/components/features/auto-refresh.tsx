"use client";

// Re-renders the server tree every few seconds while something is still running (tool job lists).
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export function AutoRefresh({ active, intervalMs = 5000 }: { active: boolean; intervalMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(t);
  }, [active, intervalMs, router]);
  return null;
}
