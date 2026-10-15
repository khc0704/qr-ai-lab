"use client";

// Relative times and running durations need a clock. Server components cannot call Date.now() under
// Cache Components, so these islands render the absolute time on the server and switch to a live
// relative value after hydration (useSyncExternalStore with a null server snapshot → no mismatch).
import { useSyncExternalStore } from "react";
import { formatDateTime, formatDuration, formatRelative } from "@/lib/format";

const subscribe = (cb: () => void) => {
  const id = setInterval(cb, 30_000);
  return () => clearInterval(id);
};
const useNow = () =>
  useSyncExternalStore(
    subscribe,
    () => Math.floor(Date.now() / 1000),
    () => null,
  );

export function RelativeTime({ iso, className }: { iso: string; className?: string }) {
  const now = useNow();
  return (
    <time dateTime={iso} title={formatDateTime(iso)} className={className}>
      {now === null ? formatDateTime(iso) : formatRelative(iso, new Date(now * 1000).toISOString())}
    </time>
  );
}

export function Duration({ start, end, className }: { start: string; end?: string; className?: string }) {
  const now = useNow();
  const endIso = end ?? (now === null ? start : new Date(now * 1000).toISOString());
  return <span className={className}>{formatDuration(start, endIso)}</span>;
}
