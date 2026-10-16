// SSE proxy for job events: the browser connects here; we forward the backend stream with the token.
// The cursor to resume from comes either from the browser's automatic reconnect (`Last-Event-ID` header) or,
// on the first connection, from `?last_event_id=` (the id GET /jobs/{id}/logs reported for the snapshot the
// page already rendered); both are forwarded upstream as `Last-Event-ID` so the backend skips the replay.
import { BACKEND_URL, getToken } from "@/lib/backend";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const token = await getToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const { id } = await params;
  const url = new URL(request.url);
  const lastId = request.headers.get("last-event-id") ?? url.searchParams.get("last_event_id");
  const upstream = await fetch(`${BACKEND_URL}/api/v1/jobs/${encodeURIComponent(id)}/events`, {
    headers: {
      authorization: `Bearer ${token}`,
      accept: "text/event-stream",
      ...(lastId ? { "last-event-id": lastId } : {}),
    },
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
