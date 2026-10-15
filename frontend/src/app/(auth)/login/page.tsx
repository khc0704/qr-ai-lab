import { Suspense } from "react";
import { BrandMark } from "@/components/layout/brand-mark";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TooltipProvider } from "@/components/ui/tooltip";
import { common } from "@/i18n/zh-TW";
import { AUTH_MODE } from "@/lib/backend";
import { KeycloakButton } from "./keycloak-button";
import { LoginForm } from "./login-form";

const KEYCLOAK = AUTH_MODE === "keycloak";
// During the switch-over a superadmin may still need the seeded local accounts next to Keycloak.
const LOCAL_FALLBACK = process.env.AUTH_LOCAL_FALLBACK === "1";

async function LoginFormWithNext({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; reason?: string; error?: string }>;
}) {
  const sp = await searchParams;
  const next = sp.next ?? "/";
  const expired = sp.reason === "expired";
  // Everything that depends on AUTH_MODE renders here (dynamic, request time) so the prerendered shell never
  // bakes the build machine's mode in.
  if (!KEYCLOAK)
    return (
      <>
        <p className="text-center text-sm text-muted-foreground">開發 / 過渡期：使用後端建立的本地帳號登入。</p>
        <LoginForm next={next} expired={expired} />
      </>
    );
  return (
    <>
      <p className="text-center text-sm text-muted-foreground">使用公司帳號（Keycloak 單一登入）。</p>
      <KeycloakButton next={next} expired={expired} error={sp.error} />
      {LOCAL_FALLBACK ? (
        <details className="rounded-lg border border-border p-3 text-sm">
          <summary className="cursor-pointer text-muted-foreground">本地帳號（僅限過渡期）</summary>
          <div className="pt-3">
            <LoginForm next={next} expired={false} />
          </div>
        </details>
      ) : null}
    </>
  );
}

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <TooltipProvider>
      <div className="relative flex min-h-svh flex-col items-center justify-center p-6">
        <div className="pointer-events-none absolute inset-0 bg-grid [mask-image:radial-gradient(ellipse_at_center,black,transparent_70%)]" />
        <div className="pointer-events-none absolute top-1/2 left-1/2 size-[480px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary/10 blur-3xl" />
        <div className="absolute top-4 right-4">
          <ThemeToggle />
        </div>
        <Card className="relative w-full max-w-sm">
          <CardHeader className="items-center text-center">
            <BrandMark className="size-12 [&>svg]:size-7" />
            <CardTitle className="mt-2 text-xl tracking-tight">{common.appName}</CardTitle>
            <CardDescription>公司內部 AI 模型實驗室。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {/* mode-agnostic shell: the prerendered HTML must not depend on the build machine's AUTH_MODE */}
            <Suspense fallback={<div className="h-40 animate-pulse rounded-lg bg-muted" aria-hidden />}>
              <LoginFormWithNext searchParams={searchParams} />
            </Suspense>
            <p className="text-center text-xs text-muted-foreground">
              登入即代表同意資料不留存政策：上傳的資料只用於該次任務。
            </p>
          </CardContent>
        </Card>
      </div>
    </TooltipProvider>
  );
}
