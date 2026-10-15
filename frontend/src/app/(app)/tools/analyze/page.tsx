import { Info } from "lucide-react";
import { Suspense } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { ToolJobs } from "../tool-jobs";
import { AnalyzeTool } from "./analyze-tool";

export const metadata = { title: "資料分析" };

export default function AnalyzeToolPage() {
  return (
    <>
      <PageHeader
        title="資料分析"
        description="不需要專案：上傳資料、選分析類型，由任務算出報告。表格：欄位相關性、共線性（VIF）、對目標的解釋力與建議；影像品質：各機台 / 條件的 IQA 指標、最會飄的指標、embedding 相似度與離群影像。"
      />
      <Alert>
        <Info />
        <AlertTitle>只保留報告，不保留資料</AlertTitle>
        <AlertDescription>
          上傳檔在任務結束時刪除；留下的只有報告（任務頁可看、也登記為 report 產物）。影像分析請把不同機台 / 條件放在 zip
          的不同子資料夾，資料夾名稱就是群組。
        </AlertDescription>
      </Alert>
      <AnalyzeTool />
      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <ToolJobs kind="analysis" />
      </Suspense>
    </>
  );
}
