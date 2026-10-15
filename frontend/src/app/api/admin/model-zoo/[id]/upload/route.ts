// Weight upload proxy (admin): browser → this route → backend model zoo (adds the Bearer token).
import { NextResponse, type NextRequest } from "next/server";
import { BACKEND_URL, getToken } from "@/lib/backend";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: { code: "UNAUTHORIZED", message: "請先登入" } }, { status: 401 });
  const { id } = await params;
  const form = await request.formData();
  const res = await fetch(`${BACKEND_URL}/api/v1/admin/model-zoo/${encodeURIComponent(id)}/upload`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}` },
    body: form,
  });
  const text = await res.text();
  return new NextResponse(text, { status: res.status, headers: { "content-type": "application/json" } });
}
