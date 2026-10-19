// User autocomplete proxy: browser → this route → backend GET /users/lookup?q= (adds the Bearer token the
// browser never sees). Any logged-in user may call it; the backend answers identity fields only (id, username,
// display_name, email), never roles. `src/proxy.ts` lists /api/users so a refreshed Keycloak token reaches us.
import { NextResponse } from "next/server";
import { BACKEND_URL, getToken } from "@/lib/backend";

const MAX_QUERY_LENGTH = 100;

export async function GET(request: Request) {
  const token = await getToken();
  if (!token) {
    return NextResponse.json(
      { detail: { code: "UNAUTHORIZED", message: "請先登入" } },
      { status: 401, headers: { "cache-control": "no-store" } },
    );
  }
  const q = (new URL(request.url).searchParams.get("q") ?? "").slice(0, MAX_QUERY_LENGTH);
  const upstream = await fetch(`${BACKEND_URL}/api/v1/users/lookup?q=${encodeURIComponent(q)}`, {
    headers: { authorization: `Bearer ${token}`, accept: "application/json" },
    cache: "no-store",
    signal: request.signal,
  });
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
    },
  });
}
