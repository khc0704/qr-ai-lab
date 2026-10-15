// Next.js 16 proxy (the former middleware): keep anonymous visitors on /login. Authorization itself is
// decided by the backend on every API call; this only avoids rendering the shell for logged-out users.
// AUTH_MODE=local → our own httpOnly token cookie; AUTH_MODE=keycloak → the Auth.js session cookie
// (possibly chunked: authjs.session-token.0, .1 … / __Secure- prefix behind https).
import { NextResponse, type NextRequest } from "next/server";

const TOKEN_COOKIE = "qr_token";
const KEYCLOAK = process.env.AUTH_MODE === "keycloak";

function hasSession(request: NextRequest): boolean {
  if (!KEYCLOAK) return Boolean(request.cookies.get(TOKEN_COOKIE)?.value);
  return request.cookies.getAll().some((c) => c.name.includes("authjs.session-token") && c.value);
}

export function proxy(request: NextRequest) {
  const authed = hasSession(request);
  const { pathname, searchParams } = request.nextUrl;
  if (pathname.startsWith("/login")) {
    // A stale session (refresh failed, backend rejected the token) lands here with ?reason= / ?error=;
    // bouncing it back to "/" would loop, so only redirect plain visits.
    if (authed && !searchParams.has("reason") && !searchParams.has("error")) {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return NextResponse.next();
  }
  if (!authed) {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api/|_next/|favicon\\.ico|.*\\.[a-zA-Z0-9]+$).*)"],
};
