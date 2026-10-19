// The site may live under a path prefix (https://qrit.tsmc.com/ai-lab). Next.js applies `basePath` to <Link>,
// router.push and redirect() by itself; anything that builds a URL by hand (plain <a href>, fetch, EventSource,
// Auth.js endpoints) must go through withBase(). NEXT_PUBLIC_BASE_PATH is inlined at build time (next.config.ts).
export const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");

export function withBase(path: string): string {
  return `${BASE_PATH}${path.startsWith("/") ? path : `/${path}`}`;
}
