// Next.js 16 proxy (the former middleware): keep anonymous visitors on /login. Authorization itself is
// decided by the backend on every API call; this only avoids rendering the shell for logged-out users.
import { NextResponse, type NextRequest } from "next/server";

const TOKEN_COOKIE = "qr_token";

export function proxy(request: NextRequest) {
  const token = request.cookies.get(TOKEN_COOKIE)?.value;
  const { pathname } = request.nextUrl;
  if (pathname.startsWith("/login")) {
    return token ? NextResponse.redirect(new URL("/", request.url)) : NextResponse.next();
  }
  if (!token) {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api/|_next/|favicon\\.ico|.*\\.[a-zA-Z0-9]+$).*)"],
};
