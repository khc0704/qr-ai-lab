import { Info } from "lucide-react";
import { Suspense } from "react";
import { PageSkeleton } from "@/components/features/skeletons";
import { PageHeader } from "@/components/layout/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { getModelZoo, getNodeStatus } from "@/lib/api";
import { can, getCurrentUser } from "@/lib/session";
import { ZooTable } from "./zoo-table";

async function ModelZoo({ searchParams }: { searchParams: Promise<{ verify?: string }> }) {
  const { verify } = await searchParams;
  const [entries, node, me] = await Promise.all([getModelZoo(verify === "1"), getNodeStatus(), getCurrentUser()]);
  const canManage = can(me, "model_zoo.manage");
  const present = entries.filter((e) => e.status === "present").length;
  return (
    <>
      <PageHeader
        title="模型庫"
        description="目錄裡每個模型家族需要的預訓練權重。伺服器不連外網，權重由管理員從瀏覽器上傳、從伺服器掛載的資料夾匯入，或從內網鏡像下載；任務永遠只從這裡讀取。"
        eyebrow={
          <span className="font-mono normal-case">
            {present} / {entries.length} 已就緒 · trainer {node.runner?.kind ?? "?"} runner 離線讀取
          </span>
        }
      />
      <Alert>
        <Info />
        <AlertTitle>離線政策</AlertTitle>
        <AlertDescription>
          trainer 以 HF_HUB_OFFLINE / YOLO_OFFLINE 執行，不會自行下載任何權重。所有權重的來源都是 Hugging Face
          Hub：snapshot 類型（DINOv2 / DINOv3、BERT、Qwen3 Embedding）請提供整個資料夾的 zip；單檔類型（YOLO .pt、TabPFN
          .ckpt）直接提供檔案。有網路的機器可用 scripts/fetch_model_zoo.py 一次抓齊（DINOv3 是 gated 模型，要先在
          Hugging Face 接受授權並設定 HF_TOKEN）。目錄有登記 sha256 的會在匯入時比對。
        </AlertDescription>
      </Alert>
      <ZooTable entries={entries} verified={verify === "1"} canManage={canManage} />
    </>
  );
}

export default function ModelZooPage({ searchParams }: PageProps<"/admin/model-zoo">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ModelZoo searchParams={searchParams} />
    </Suspense>
  );
}

export const metadata = { title: "模型庫" };
