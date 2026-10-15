import { Suspense } from "react";
import { BrandMark } from "@/components/layout/brand-mark";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TooltipProvider } from "@/components/ui/tooltip";
import { common } from "@/i18n/zh-TW";
import { LoginForm } from "./login-form";

async function LoginFormWithNext({ searchParams }: { searchParams: Promise<{ next?: string; reason?: string }> }) {
  const sp = await searchParams;
  return <LoginForm next={sp.next ?? "/"} expired={sp.reason === "expired"} />;
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
            <CardDescription>公司內部 AI 模型實驗室。過渡期使用本地帳號登入；之後改為 Keycloak。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <Suspense fallback={<LoginForm next="/" expired={false} />}>
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
