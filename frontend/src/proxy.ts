// Next.js 16 proxy (the former middleware). Two jobs, both lightweight:
//   1. keep anonymous visitors on /login (pages) or answer a 401 JSON (/api/* route handlers);
//   2. in AUTH_MODE=keycloak be the ONLY place that refreshes the Keycloak tokens and persists them.
//
// Keycloak flow, end to end (src/auth.ts, src/lib/backend.ts and this file):
//   - The Auth.js session cookie (jwt strategy, possibly chunked `authjs.session-token.0/.1…`, `__Secure-` prefix
//     behind https) carries accessToken / refreshToken / idToken / expiresAt.
//   - The handler is wrapped in Auth.js' `auth()` middleware form. On every matched request Auth.js decodes the
//     cookie and runs the `jwt` callback (src/auth.ts), which refreshes the access token shortly before it expires.
//     The wrapper then appends the re-encrypted session cookie to OUR response (next-auth/lib/index.js
//     `handleAuth`: `finalResponse.headers.append("set-cookie", …)`), so refresh-token rotation is persisted.
//   - The current access token is handed to the rendering request in the `x-qr-access-token` request header
//     (`NextResponse.next({ request: { headers } })`). `getToken()` in src/lib/backend.ts reads that header first,
//     so the page / server action / route handler rendered in the SAME request already uses the refreshed token
//     and never refreshes on its own (a React Server Component cannot write cookies; doing it there caused refresh
//     storms and, with rotation, forced re-logins). A client-supplied copy of that header is always dropped.
//   - A session whose refresh failed (`error: "RefreshTokenError"`) counts as logged out: pages are sent to
//     /login?reason=expired, /api/* gets 401. /login is only bounced back to "/" for plain visits (no ?reason /
//     ?error), otherwise the stale cookie that is still in the browser would redirect in a loop.
//   - The route handlers that forward the token to the backend (/api/upload, /api/stream, /api/download,
//     /api/tools, /api/admin) pass through here as well, so they get a refreshed token too; /api/auth/* (Auth.js
//     itself) never does. The proxy only decides and sets headers, so streamed responses stay streamed.
// AUTH_MODE=local keeps its original behaviour: our own httpOnly `qr_token` cookie decides, and Auth.js is never
// imported (the `@/auth` import is lazy so a local-mode deployment never initialises NextAuth).
// Authorization itself is decided by the backend on every API call; this only avoids rendering the shell.
import type { NextAuthRequest } from "next-auth";
import { NextResponse, type NextFetchEvent, type NextRequest } from "next/server";

type AuthedHandler = (req: NextAuthRequest, event: NextFetchEvent) => NextResponse;

const TOKEN_COOKIE = "qr_token";
const ACCESS_TOKEN_HEADER = "x-qr-access-token";
const KEYCLOAK = process.env.AUTH_MODE === "keycloak";

type Decision = { authed: true; token?: string } | { authed: false; expired: boolean };

function hasAuthjsCookie(request: NextRequest): boolean {
  return request.cookies.getAll().some((c) => c.name.includes("authjs.session-token") && c.value);
}

function unauthorizedJson(expired: boolean): NextResponse {
  return NextResponse.json(
    {
      detail: {
        code: expired ? "SESSION_EXPIRED" : "UNAUTHORIZED",
        message: expired ? "登入已過期，請重新登入" : "請先登入",
      },
    },
    { status: 401, headers: { "cache-control": "no-store" } },
  );
}

function respond(request: NextRequest, decision: Decision): NextResponse {
  const { pathname, search, searchParams } = request.nextUrl;
  const headers = new Headers(request.headers);
  headers.delete(ACCESS_TOKEN_HEADER); // never trust a client-supplied value
  if (pathname.startsWith("/login")) {
    // A stale session (refresh failed, backend rejected the token) lands here with ?reason= / ?error=;
    // bouncing it back to "/" would loop, so only redirect plain visits.
    if (decision.authed && !searchParams.has("reason") && !searchParams.has("error")) {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return NextResponse.next({ request: { headers } });
  }
  if (!decision.authed) {
    if (pathname.startsWith("/api/")) return unauthorizedJson(decision.expired);
    const url = new URL("/login", request.url);
    if (decision.expired) url.searchParams.set("reason", "expired");
    if (pathname !== "/") url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }
  if (decision.token) headers.set(ACCESS_TOKEN_HEADER, decision.token);
  return NextResponse.next({ request: { headers } });
}

export async function proxy(request: NextRequest, event: NextFetchEvent): Promise<Response> {
  if (!KEYCLOAK) {
    const authed = Boolean(request.cookies.get(TOKEN_COOKIE)?.value);
    return respond(request, authed ? { authed: true } : { authed: false, expired: false });
  }
  const { auth } = await import("@/auth");
  const decide: AuthedHandler = (req) => {
    const session = req.auth;
    if (session?.accessToken && !session.error) return respond(req, { authed: true, token: session.accessToken });
    // Cookie present but unusable (refresh failed / no access token) → expired; no cookie at all → plain anonymous.
    return respond(req, { authed: false, expired: hasAuthjsCookie(req) });
  };
  return (await auth(decide)(request, event)) ?? NextResponse.next();
}

export const config = {
  matcher: [
    // every page (not Next internals, static files or /api/*) …
    "/((?!api/|_next/|favicon\\.ico|.*\\.[a-zA-Z0-9]+$).*)",
    // … plus the route handlers that forward the token to the backend (never /api/auth/*)
    "/api/upload/:path*",
    "/api/stream/:path*",
    "/api/download/:path*",
    "/api/tools/:path*",
    "/api/admin/:path*",
  ],
};
