/** Formatting helpers. Numbers are rendered with font-mono tabular-nums by the caller. */

/** Fixed "now" for mock data so SSR and client output match. Replace with a client <RelativeTime> when real data arrives. */
export const MOCK_NOW = "2026-10-15T08:30:00Z";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

export function formatMb(mb: number): string {
  return mb >= 1024 ? `${(mb / 1024).toFixed(mb % 1024 === 0 ? 0 : 1)} GB` : `${mb} MB`;
}

export function formatRelative(iso: string, now: string = MOCK_NOW): string {
  const diff = (new Date(now).getTime() - new Date(iso).getTime()) / 1000;
  const abs = Math.abs(diff);
  const suffix = diff >= 0 ? "前" : "後";
  if (abs < 60) return `${Math.round(abs)} 秒${suffix}`;
  if (abs < 3600) return `${Math.round(abs / 60)} 分鐘${suffix}`;
  if (abs < 86400) return `${Math.round(abs / 3600)} 小時${suffix}`;
  return `${Math.round(abs / 86400)} 天${suffix}`;
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

export function formatDuration(startIso: string, endIso: string = MOCK_NOW): string {
  const s = Math.max(0, (new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

export function formatPercent(v: number, digits = 0): string {
  return `${v.toFixed(digits)}%`;
}

export function formatMetric(v: number): string {
  return Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(3);
}

export function initials(name: string): string {
  const t = name.trim();
  if (!t) return "?";
  if (/^[A-Za-z]/.test(t)) {
    const parts = t.split(/\s+/);
    return (parts.length > 1 ? parts[0][0] + parts[1][0] : t.slice(0, 2)).toUpperCase();
  }
  return t.slice(0, 1); // CJK: one character fits the small avatars
}
