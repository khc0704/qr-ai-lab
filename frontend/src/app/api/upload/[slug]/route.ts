// Multipart upload proxy: browser → this route → backend (adds the Bearer token the browser never sees).
import { NextResponse, type NextRequest } from "next/server";
import { BACKEND_URL, getToken } from "@/lib/backend";

export async function POST(request: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: { code: "UNAUTHORIZED", message: "請先登入" } }, { status: 401 });
  const { slug } = await params;
  const form = await request.formData();
  const res = await fetch(`${BACKEND_URL}/api/v1/projects/${encodeURIComponent(slug)}/uploads`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}` },
    body: form,
  });
  const text = await res.text();
  return new NextResponse(text, { status: res.status, headers: { "content-type": "application/json" } });
}
