// SSE proxy for job events: the browser connects here; we forward the backend stream with the token.
import { BACKEND_URL, getToken } from "@/lib/backend";


export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const token = await getToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const { id } = await params;
  const lastId = request.headers.get("last-event-id");
  const upstream = await fetch(`${BACKEND_URL}/api/v1/jobs/${encodeURIComponent(id)}/events`, {
    headers: { authorization: `Bearer ${token}`, accept: "text/event-stream", ...(lastId ? { "last-event-id": lastId } : {}) },
    signal: request.signal,
    cache: "no-store",
  });
  if (!upstream.ok || !upstream.body) return new Response(await upstream.text(), { status: upstream.status });
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
