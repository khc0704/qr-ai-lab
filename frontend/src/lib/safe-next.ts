// Guards every post-login redirect target (`?next=`, Auth.js `redirectTo`). Only a same-origin absolute path
// is accepted: it must start with exactly one "/" and the second character must not be "/" or "\", because
// browsers resolve "//evil.com" and "/\evil.com" as protocol-relative URLs (open redirect). Anything with a
// scheme, a backslash, control characters or whitespace is rejected too. Client-safe: no server imports.

const SAFE_PATH = /^\/(?![/\\])/;
const SCHEME = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;

export function safeNext(value: unknown, fallback = "/"): string {
  if (typeof value !== "string") return fallback;
  const v = value.trim();
  if (!v || v.length > 2048) return fallback;
  if (!SAFE_PATH.test(v)) return fallback;
  if (SCHEME.test(v) || v.includes("\\") || /[\u0000-\u001f\u007f\s]/.test(v)) return fallback;
  // Belt and braces: resolving against a throwaway origin must stay on that origin.
  try {
    const u = new URL(v, "http://qr.invalid");
    if (u.origin !== "http://qr.invalid") return fallback;
    return `${u.pathname}${u.search}${u.hash}`;
  } catch {
    return fallback;
  }
}
