// Standalone preprocessing tool upload proxy: browser → this route → backend /tools/uploads (adds the token).
// The data_type comes from the query string; the file is a temp file on the backend, never a database row.
import { NextResponse, type NextRequest } from "next/server";
import { BACKEND_URL, getToken } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: { code: "UNAUTHORIZED", message: "請先登入" } }, { status: 401 });
  const form = await request.formData();
  const dataType = request.nextUrl.searchParams.get("data_type") ?? "";
  form.set("data_type", dataType);
  const res = await fetch(`${BACKEND_URL}/api/v1/tools/uploads`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}` },
    body: form,
  });
  const text = await res.text();
  return new NextResponse(text, { status: res.status, headers: { "content-type": "application/json" } });
}
