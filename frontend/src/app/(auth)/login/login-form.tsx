"use client";

import { KeyRound, LoaderCircle } from "lucide-react";
import { useActionState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { loginAction, type LoginState } from "@/lib/actions";

export function LoginForm({ next, expired }: { next: string; expired: boolean }) {
  const [state, action, pending] = useActionState<LoginState, FormData>(loginAction, {});
  return (
    <form action={action} className="grid gap-3">
      <input type="hidden" name="next" value={next} />
      {expired ? (
        <Alert>
          <AlertDescription>登入已過期，請重新登入。</AlertDescription>
        </Alert>
      ) : null}
      <div className="grid gap-2">
        <Label htmlFor="username">帳號</Label>
        <Input id="username" name="username" autoComplete="username" required autoFocus placeholder="admin" />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="password">密碼</Label>
        <Input id="password" name="password" type="password" autoComplete="current-password" required />
      </div>
      {state.error ? (
        <p role="alert" className="text-sm text-destructive">
          {state.error}
        </p>
      ) : null}
      <Button type="submit" size="lg" className="w-full" disabled={pending}>
        {pending ? <LoaderCircle className="animate-spin" /> : <KeyRound />}
        登入
      </Button>
    </form>
  );
}
