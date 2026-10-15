// Auth.js (next-auth v5) with the company Keycloak as the only provider. Used when AUTH_MODE=keycloak:
// the browser signs in at Keycloak, the server keeps access/refresh/id tokens in the encrypted session
// cookie (jwt strategy) and forwards the access token to FastAPI, which validates it against the realm JWKS.
// AUTH_MODE=local (dev) never touches this file at request time.
import NextAuth, { type NextAuthConfig } from "next-auth";
import type { JWT } from "next-auth/jwt";
import Keycloak from "next-auth/providers/keycloak";

const issuer = process.env.AUTH_KEYCLOAK_ISSUER ?? "";
const clientId = process.env.AUTH_KEYCLOAK_ID ?? "";
const clientSecret = process.env.AUTH_KEYCLOAK_SECRET ?? "";
// Refresh a little before the access token expires so a request never carries an expired token.
const REFRESH_MARGIN_S = 30;

async function refreshAccessToken(token: JWT): Promise<JWT> {
  if (!token.refreshToken) return { ...token, error: "RefreshTokenError" };
  try {
    const res = await fetch(`${issuer}/protocol/openid-connect/token`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: clientId,
        client_secret: clientSecret,
        refresh_token: token.refreshToken,
      }),
      cache: "no-store",
    });
    const data = (await res.json()) as {
      access_token?: string;
      refresh_token?: string;
      id_token?: string;
      expires_in?: number;
      error?: string;
    };
    if (!res.ok || !data.access_token) return { ...token, error: "RefreshTokenError" };
    return {
      ...token,
      accessToken: data.access_token,
      refreshToken: data.refresh_token ?? token.refreshToken,
      idToken: data.id_token ?? token.idToken,
      expiresAt: Math.floor(Date.now() / 1000) + (data.expires_in ?? 300),
      error: undefined,
    };
  } catch {
    return { ...token, error: "RefreshTokenError" };
  }
}

export const authConfig: NextAuthConfig = {
  providers: [Keycloak({ clientId, clientSecret, issuer })],
  session: { strategy: "jwt", maxAge: Number(process.env.AUTH_SESSION_MAX_AGE ?? 12 * 60 * 60) },
  pages: { signIn: "/login", error: "/login" },
  trustHost: true, // behind nginx; AUTH_URL is the public origin
  secret: process.env.AUTH_SECRET ?? "dev-local-mode-unused",
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account) {
        // first sign-in: keep the provider tokens (never exposed to the browser except through our own session)
        return {
          ...token,
          username:
            (profile as { preferred_username?: string } | undefined)?.preferred_username ?? token.name ?? undefined,
          accessToken: account.access_token,
          refreshToken: account.refresh_token,
          idToken: account.id_token,
          expiresAt: account.expires_at,
          error: undefined,
        };
      }
      if (token.expiresAt && Date.now() / 1000 < token.expiresAt - REFRESH_MARGIN_S) return token;
      return refreshAccessToken(token);
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken;
      session.idToken = token.idToken;
      session.error = token.error;
      session.username = token.username;
      return session;
    },
  },
};

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);
