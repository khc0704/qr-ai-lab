import { Info } from "lucide-react";
import { Suspense } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { listPreprocessOps } from "@/lib/api";
import { ToolJobs } from "../tool-jobs";
import { PreprocessTool } from "./preprocess-tool";

export const metadata = { title: "資料前處理" };

async function Tool() {
  const ops = await listPreprocessOps();
  return <PreprocessTool ops={ops} />;
}

export default function PreprocessToolPage() {
  return (
    <>
      <PageHeader
        title="資料前處理"
        description="不需要專案：上傳檔案、選資料類型、挑步驟、抽樣預覽（即時），再把整個檔案交給任務處理；完成後在任務頁下載打包結果（處理後資料 + pipeline.json + summary.json）。"
      />
      <Alert>
        <Info />
        <AlertTitle>本服務不保存資料</AlertTitle>
        <AlertDescription>
          上傳檔只放在暫存資料夾；建立任務時移進任務的輸入區，任務結束即刪。結果 zip
          下載一次就刪除，沒下載的也會在管理員設定的期限（預設 24 小時）後刪除。 pipeline.json
          記錄了步驟與擬合出的數值，之後建立訓練任務可用相同步驟重現。
        </AlertDescription>
      </Alert>
      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <Tool />
      </Suspense>
      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <ToolJobs kind="preprocess" />
      </Suspense>
    </>
  );
}
