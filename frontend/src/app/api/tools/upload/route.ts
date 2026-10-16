// Standalone tool upload proxy: browser → this route → backend /tools/uploads (adds the token).
// The multipart body is streamed through untouched, so the Dropzone appends `data_type` as a form field
// itself (`fields` prop); the file is a temp file on the backend, never a database row.
import type { NextRequest } from "next/server";
import { proxyUpload } from "@/lib/upload-proxy";

export async function POST(request: NextRequest) {
  return proxyUpload(request, "/tools/uploads");
}
