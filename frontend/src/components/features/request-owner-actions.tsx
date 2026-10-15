"use client";

import { Undo2 } from "lucide-react";
import { useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { withdrawRequestAction } from "@/lib/actions";

export function WithdrawRequestButton({ id }: { id: number }) {
  const [pending, startTransition] = useTransition();
  return (
    <Button
      variant="outline"
      disabled={pending}
      onClick={() => {
        if (!confirm("撤回這個申請？之後可以重新提出。")) return;
        startTransition(async () => {
          const r = await withdrawRequestAction(id);
          if (!r.ok) toast.error(r.error);
          else toast.success("已撤回");
        });
      }}
    >
      <Undo2 />
      撤回
    </Button>
  );
}
