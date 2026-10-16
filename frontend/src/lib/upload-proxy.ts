// Shared body of the three multipart upload proxies (/api/upload/{slug}, /api/tools/upload,
// /api/admin/model-zoo/{id}/upload): the browser's request body is piped straight to the backend
// (`duplex: "half"`, no buffering of multi-GB files in the Next.js process) with the Bearer token the browser
// never sees; the backend's JSON answer is relayed as-is, and a non-JSON upstream error (nginx 413 HTML, a
// crashed backend) is wrapped so the Dropzone always gets `{detail:{code,message}}`.
import "server-only";

import { NextResponse } from "next/server";
import { BACKEND_URL, getToken } from "@/lib/backend";

export async function proxyUpload(request: Request, backendPath: string): Promise<Response> {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: { code: "UNAUTHORIZED", message: "請先登入" } }, { status: 401 });
  const contentType = request.headers.get("content-type");
  if (!contentType?.toLowerCase().startsWith("multipart/form-data")) {
    return NextResponse.json({ detail: { code: "BAD_REQUEST", message: "需要 multipart/form-data" } }, { status: 400 });
  }
  const headers: Record<string, string> = { authorization: `Bearer ${token}`, "content-type": contentType };
  const length = request.headers.get("content-length");
  if (length) headers["content-length"] = length;
  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}/api/v1${backendPath}`, {
      method: "POST",
      headers,
      body: request.body,
      // Node's fetch requires this to stream a request body.
      duplex: "half",
      cache: "no-store",
      signal: request.signal,
    } as RequestInit & { duplex: "half" });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return NextResponse.json(
      { detail: { code: "UPSTREAM_UNREACHABLE", message: `無法連線到後端：${message}` } },
      { status: 502 },
    );
  }
  const text = await res.text();
  const upstreamType = res.headers.get("content-type") ?? "";
  if (upstreamType.includes("application/json")) {
    return new NextResponse(text, { status: res.status, headers: { "content-type": "application/json" } });
  }
  const message = res.status === 413 ? "檔案超過伺服器允許的大小" : text.slice(0, 200) || `HTTP ${res.status}`;
  return NextResponse.json({ detail: { code: `HTTP_${res.status}`, message } }, { status: res.ok ? 502 : res.status });
}
