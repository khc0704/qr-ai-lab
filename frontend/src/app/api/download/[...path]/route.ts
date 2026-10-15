// Streams backend downloads (artifacts, logs, inference output) through the server with the token.
import { BACKEND_URL, getToken } from "@/lib/backend";

const ALLOWED = [/^artifacts\/\d+\/download$/, /^jobs\/\d+\/logs\/download$/, /^jobs\/\d+\/download$/];

export async function GET(_request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const token = await getToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const { path } = await params;
  const rel = path.join("/");
  if (!ALLOWED.some((re) => re.test(rel))) return new Response("not found", { status: 404 });
  const upstream = await fetch(`${BACKEND_URL}/api/v1/${rel}`, {
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
