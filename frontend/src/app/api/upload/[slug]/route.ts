// Multipart upload proxy: browser → this route → backend (adds the Bearer token the browser never sees).
// The body is streamed, not buffered (see src/lib/upload-proxy.ts).
import type { NextRequest } from "next/server";
import { proxyUpload } from "@/lib/upload-proxy";

export async function POST(request: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyUpload(request, `/projects/${encodeURIComponent(slug)}/uploads`);
}
