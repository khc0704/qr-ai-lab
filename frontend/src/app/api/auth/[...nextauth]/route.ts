// Auth.js route handlers (/api/auth/*). Only meaningful when AUTH_MODE=keycloak; local mode answers 404 so
// nobody can start an OAuth flow against a half-configured provider.
import { handlers } from "@/auth";
import { AUTH_MODE } from "@/lib/backend";

const notFound = () => new Response("Not found", { status: 404 });

export const GET = AUTH_MODE === "keycloak" ? handlers.GET : notFound;
export const POST = AUTH_MODE === "keycloak" ? handlers.POST : notFound;
