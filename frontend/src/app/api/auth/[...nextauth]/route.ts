// Auth.js route handlers (<base>/api/auth/*). Only meaningful when AUTH_MODE=keycloak; local mode answers 404 so
// nobody can start an OAuth flow against a half-configured provider.
//
// Next.js strips the configured basePath from request.url before a route handler runs, while Auth.js parses its
// action from the pathname against its own basePath (<base>/api/auth, see src/auth.ts — it must carry the site
// prefix so the public callback URL is https://host/ai-lab/api/auth/callback/keycloak). Put the prefix back.
import { NextRequest } from "next/server";
import { handlers } from "@/auth";
import { BASE_PATH } from "@/lib/base-path";
import { AUTH_MODE } from "@/lib/backend";

const notFound = () => new Response("Not found", { status: 404 });

function withSitePrefix(req: NextRequest): NextRequest {
  if (!BASE_PATH) return req;
  const url = new URL(req.url);
  if (url.pathname === BASE_PATH || url.pathname.startsWith(`${BASE_PATH}/`)) return req;
  url.pathname = `${BASE_PATH}${url.pathname}`;
  return new NextRequest(url, { method: req.method, headers: req.headers, body: req.body, duplex: "half" });
}

export const GET = AUTH_MODE === "keycloak" ? (req: NextRequest) => handlers.GET(withSitePrefix(req)) : notFound;
export const POST = AUTH_MODE === "keycloak" ? (req: NextRequest) => handlers.POST(withSitePrefix(req)) : notFound;
