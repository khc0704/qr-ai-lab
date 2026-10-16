// Weight upload proxy (admin): browser → this route → backend model zoo (adds the Bearer token).
// The body is streamed, not buffered (see src/lib/upload-proxy.ts).
import type { NextRequest } from "next/server";
import { proxyUpload } from "@/lib/upload-proxy";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxyUpload(request, `/admin/model-zoo/${encodeURIComponent(id)}/upload`);
}
