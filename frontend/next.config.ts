import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // https://qrit.tsmc.com/ai-lab style deployments: NEXT_PUBLIC_BASE_PATH=/ai-lab must be set for BOTH `next build`
  // (compiled into the client bundle, see src/lib/base-path.ts) and `next start` (this file is evaluated again then).
  basePath: process.env.NEXT_PUBLIC_BASE_PATH?.replace(/\/+$/, "") || undefined,
  // `next dev` only serves its own resources (/_next/*: HMR websocket, dev overlay, Turbopack chunks requested
  // with an Origin header) to localhost. Browsing the dev server from another machine needs that machine's
  // address of this host here, e.g. NEXT_DEV_ALLOWED_ORIGINS=192.168.1.20,devbox.local (comma-separated hosts,
  // wildcards like *.corp allowed). Production builds ignore it.
  allowedDevOrigins: (process.env.NEXT_DEV_ALLOWED_ORIGINS ?? "")
    .split(",")
    .map((h) => h.trim())
    .filter(Boolean),
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
