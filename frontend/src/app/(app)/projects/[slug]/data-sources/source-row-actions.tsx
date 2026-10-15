"use client";

import { RefreshCw, Trash2 } from "lucide-react";
import { useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { checkDataSourceAction, deleteDataSourceAction } from "@/lib/actions";

export function SourceRowActions({ slug, id, name }: { slug: string; id: number; name: string }) {
  const [pending, startTransition] = useTransition();
  return (
    <div className="flex justify-end gap-1">
      <Button
        variant="ghost"
        size="sm"
        disabled={pending}
        onClick={() =>
          startTransition(async () => {
            const r = await checkDataSourceAction(slug, id);
            if (!r.ok) toast.error(r.error);
            else if (r.data) toast.success(`${name} 連線正常`);
            else toast.warning(`${name} 連線失敗，請看最近檢查訊息`);
          })
        }
      >
        <RefreshCw className={pending ? "animate-spin" : undefined} />
        檢查連線
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="刪除資料來源"
        disabled={pending}
        onClick={() => {
          if (!confirm(`刪除資料來源「${name}」？只移除連線資訊，不影響你的資料。`)) return;
          startTransition(async () => {
            const r = await deleteDataSourceAction(slug, id);
            if (!r.ok) toast.error(r.error);
            else toast.success("已刪除");
          });
        }}
      >
        <Trash2 />
      </Button>
    </div>
  );
}
