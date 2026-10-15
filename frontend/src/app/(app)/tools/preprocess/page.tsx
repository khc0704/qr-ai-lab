import { Info } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { listPreprocessOps } from "@/lib/api";
import { PreprocessTool } from "./preprocess-tool";

export const metadata = { title: "資料前處理" };

export default async function PreprocessToolPage() {
  const ops = await listPreprocessOps();
  return (
    <>
      <PageHeader
        title="資料前處理"
        description="不需要專案：上傳檔案、選資料類型、挑步驟、抽樣預覽，然後對整個檔案執行並下載打包結果（處理後資料 + pipeline.json + summary.json）。"
      />
      <Alert>
        <Info />
        <AlertTitle>本服務不保存資料</AlertTitle>
        <AlertDescription>
          檔案只放在伺服器的暫存資料夾，沒有資料庫紀錄；下載結果、按「刪除」或超過上傳有效期（預設 60 分鐘）就會刪除。
          pipeline.json 記錄了步驟與擬合出的數值（補值、標準化、對位參考…），之後建立訓練任務時可用相同步驟重現。
        </AlertDescription>
      </Alert>
      <PreprocessTool ops={ops} />
    </>
  );
}
