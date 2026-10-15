"use client";

import { Building2, LoaderCircle } from "lucide-react";
import { signIn } from "next-auth/react";
import { useTransition } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

const errorText: Record<string, string> = {
  Configuration: "Keycloak 設定不完整（AUTH_KEYCLOAK_* / AUTH_SECRET），請聯絡系統管理員。",
  AccessDenied: "此帳號沒有登入權限。",
  OAuthCallbackError: "Keycloak 回呼失敗，請重試。",
  OAuthAccountNotLinked: "帳號已存在但未連結，請聯絡系統管理員。",
};

export function KeycloakButton({ next, expired, error }: { next: string; expired: boolean; error?: string }) {
  const [pending, startTransition] = useTransition();
  return (
    <div className="grid gap-3">
      {expired ? (
        <Alert>
          <AlertDescription>登入已過期，請重新登入。</AlertDescription>
        </Alert>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {errorText[error] ?? `登入失敗（${error}）`}
        </p>
      ) : null}
      <Button
        type="button"
        size="lg"
        className="w-full"
        disabled={pending}
        // Client-side sign-in (csrf → POST /api/auth/signin/keycloak → redirect): the PKCE / state cookies are set
        // on the same origin the callback comes back to, which a server action cannot guarantee behind a proxy.
        onClick={() =>
          startTransition(async () => {
            await signIn("keycloak", { redirectTo: next.startsWith("/") && !next.startsWith("//") ? next : "/" });
          })
        }
      >
        {pending ? <LoaderCircle className="animate-spin" /> : <Building2 />}
        使用公司帳號登入（Keycloak）
      </Button>
      <p className="text-center text-xs text-muted-foreground">會轉到公司單一登入頁，登入後自動回到這裡。</p>
    </div>
  );
}
