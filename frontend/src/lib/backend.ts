// Server-only HTTP helper for the FastAPI backend. The access token lives in an httpOnly cookie that
// the login server action sets; every call here forwards it as a Bearer token.
import "server-only";

import { cookies } from "next/headers";

export const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const TOKEN_COOKIE = "qr_token";
/** "local" (dev: username/password accounts, token in our own cookie) or "keycloak" (prod: Auth.js session). */
export const AUTH_MODE: "local" | "keycloak" = process.env.AUTH_MODE === "keycloak" ? "keycloak" : "local";
/** Public origin of this frontend (nginx), used for Keycloak post-logout redirects. */
export const PUBLIC_URL = (process.env.AUTH_URL ?? process.env.PUBLIC_URL ?? "http://localhost:3000").replace(
  /\/$/,
  "",
);

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

export async function getToken(): Promise<string | undefined> {
  if (AUTH_MODE === "keycloak") {
    const { auth } = await import("@/auth");
    const session = await auth();
    if (!session || session.error || !session.accessToken) return undefined;
    return session.accessToken;
  }
  return (await cookies()).get(TOKEN_COOKIE)?.value;
}

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
