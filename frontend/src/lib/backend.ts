// Server-only HTTP helper for the FastAPI backend. Every call forwards the user's access token as a Bearer token.
//
// Where the token comes from (the other half of this flow is src/proxy.ts):
//   AUTH_MODE=local    loginAction stores the backend-issued JWT in our own httpOnly cookie `qr_token`;
//                      getToken() simply reads it.
//   AUTH_MODE=keycloak the Auth.js session cookie (jwt strategy) carries accessToken / refreshToken / idToken.
//                      Only src/proxy.ts refreshes those tokens, because it is the one place that can write the
//                      rotated cookie back to the browser; it hands the current access token to the rendering
//                      request in the `x-qr-access-token` request header. getToken() reads that header first and,
//                      for requests the proxy did not see, falls back to decoding the session cookie WITHOUT the
//                      Auth.js callbacks (no refresh, no cookie write). Never call auth() from here: a React Server
//                      Component cannot persist a refreshed cookie, so a refresh triggered during render is lost and
//                      with refresh-token rotation it invalidates the session (refresh storm → forced re-login).
import "server-only";

import { cookies, headers } from "next/headers";
import type { JWT } from "next-auth/jwt";
import { cache } from "react";

export const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const TOKEN_COOKIE = "qr_token";
/** Request header the proxy uses to hand the (possibly just refreshed) access token to the render. */
export const ACCESS_TOKEN_HEADER = "x-qr-access-token";
/** "local" (dev: username/password accounts, token in our own cookie) or "keycloak" (prod: Auth.js session). */
export const AUTH_MODE: "local" | "keycloak" = process.env.AUTH_MODE === "keycloak" ? "keycloak" : "local";
/** Public origin of this frontend (nginx), used for Keycloak post-logout redirects. */
export const PUBLIC_URL = (process.env.AUTH_URL ?? process.env.PUBLIC_URL ?? "http://localhost:3000").replace(
  /\/$/,
  "",
);
const AUTH_SECRET = process.env.AUTH_SECRET ?? "dev-local-mode-unused";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Decode the Auth.js session cookie of the current request without running any callback (so no refresh and no
 * cookie write). Handles the `__Secure-` prefix behind https and chunked cookies (`authjs.session-token.0`, `.1` …)
 * through @auth/core's SessionStore. Cached per request; null outside keycloak mode or when not signed in.
 */
export const readSessionJwt = cache(async (): Promise<JWT | null> => {
  if (AUTH_MODE !== "keycloak") return null;
  const { getToken: decodeSessionCookie } = await import("next-auth/jwt");
  const req = { headers: new Headers(await headers()) };
  // Auth.js picks the cookie name from the request protocol; try the https name first, then the plain one.
  for (const secureCookie of [true, false]) {
    const jwt = await decodeSessionCookie({ req, secret: AUTH_SECRET, secureCookie });
    if (jwt) return jwt;
  }
  return null;
});

/** The current access token, or undefined when logged out / expired. Never triggers a refresh (see header). */
export const getToken = cache(async (): Promise<string | undefined> => {
  if (AUTH_MODE === "keycloak") {
    const fromProxy = (await headers()).get(ACCESS_TOKEN_HEADER);
    if (fromProxy) return fromProxy;
    const jwt = await readSessionJwt();
    if (!jwt || jwt.error || !jwt.accessToken) return undefined;
    if (jwt.expiresAt && Date.now() / 1000 >= jwt.expiresAt) return undefined; // stale: let the proxy refresh it
    return jwt.accessToken;
  }
  return (await cookies()).get(TOKEN_COOKIE)?.value;
});

interface Options extends Omit<RequestInit, "body"> {
  /** Pass null to call without a token (login); undefined reads the cookie. */
  token?: string | null;
  body?: unknown;
  /** Return undefined instead of throwing on these statuses (e.g. 404 → "not found" pages). */
  swallow?: number[];
}

export async function apiFetch<T>(path: string, opts: Options = {}): Promise<T> {
  const { token: tokenOpt, body, swallow, headers, ...init } = opts;
  const token = tokenOpt === undefined ? await getToken() : tokenOpt;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const res = await fetch(`${BACKEND_URL}/api/v1${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...(body !== undefined && !isForm ? { "content-type": "application/json" } : {}),
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(headers as Record<string, string> | undefined),
    },
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });
  if (!res.ok) {
    if (swallow?.includes(res.status)) return undefined as T;
    throw await toApiError(res);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function toApiError(res: Response): Promise<ApiError> {
  let code = `HTTP_${res.status}`;
  let message = res.statusText || `HTTP ${res.status}`;
  try {
    const j = (await res.json()) as { detail?: unknown };
    const d = j.detail;
    if (d && typeof d === "object" && !Array.isArray(d) && "code" in d) {
      code = String((d as { code: string }).code);
      message = String((d as { message?: string }).message ?? message);
    } else if (typeof d === "string") {
      message = d;
    } else if (Array.isArray(d)) {
      message = d
        .map((e) => `${(e as { loc?: unknown[] }).loc?.slice(-1)[0] ?? ""}: ${(e as { msg?: string }).msg ?? ""}`)
        .join("; ");
      code = "VALIDATION_ERROR";
    }
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, code, message);
}

/** Human-readable message for toasts. */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message || e.code;
  if (e instanceof Error) return e.message;
  return String(e);
}
