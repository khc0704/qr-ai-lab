// Streams the processed zip of the preprocessing tool; the backend deletes the temp folder once sent.
import { BACKEND_URL, getToken } from "@/lib/backend";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const token = await getToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const { id } = await params;
  if (!/^[a-f0-9]{8,40}$/.test(id)) return new Response("not found", { status: 404 });
  const upstream = await fetch(`${BACKEND_URL}/api/v1/tools/uploads/${id}/download`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!upstream.ok || !upstream.body) return new Response(await upstream.text(), { status: upstream.status });
  const headers = new Headers();
  for (const h of ["content-type", "content-disposition", "content-length"]) {
    const v = upstream.headers.get(h);
    if (v) headers.set(h, v);
  }
  return new Response(upstream.body, { status: 200, headers });
}
