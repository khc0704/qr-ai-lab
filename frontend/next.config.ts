import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // https://qrit.tsmc.com/ai-lab style deployments: NEXT_PUBLIC_BASE_PATH=/ai-lab must be set for BOTH `next build`
  // (compiled into the client bundle, see src/lib/base-path.ts) and `next start` (this file is evaluated again then).
  basePath: process.env.NEXT_PUBLIC_BASE_PATH?.replace(/\/+$/, "") || undefined,
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
