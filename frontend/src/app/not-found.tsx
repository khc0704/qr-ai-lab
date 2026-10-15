import { SearchX } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6 text-center">
      <div className="flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
        <SearchX className="size-6" />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">找不到頁面</h1>
      <p className="max-w-sm text-sm text-muted-foreground">這個網址不存在，或你沒有權限檢視。</p>
      <Button asChild>
        <Link href="/">回首頁</Link>
      </Button>
    </div>
  );
}
