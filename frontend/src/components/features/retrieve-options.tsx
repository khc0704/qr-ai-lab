"use client";

// Options for the `retrieve` inference mode (find the most similar / least similar references): the direction
// and how many neighbours per query. Shared by the one-off inference panel and the job wizard; sent as
// config.order / config.k and read by the trainer (vision.dino_*, text.qwen_embedding).
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { retrieveOrderLabel } from "@/i18n/zh-TW";
import type { RetrieveOrder } from "@/types/domain";

export const RETRIEVE_ORDERS: RetrieveOrder[] = ["both", "similar", "dissimilar"];
export const RETRIEVE_K_DEFAULT = 5;
const K_MIN = 1;
const K_MAX = 50;

export interface RetrieveConfig {
  order: RetrieveOrder;
  k: number;
}

export const DEFAULT_RETRIEVE: RetrieveConfig = { order: "both", k: RETRIEVE_K_DEFAULT };

export function isRetrieveOrder(v: unknown): v is RetrieveOrder {
  return typeof v === "string" && (RETRIEVE_ORDERS as string[]).includes(v);
}

/** Clamp a user-typed k to the range the trainer accepts. */
export function clampK(v: number): number {
  if (!Number.isFinite(v)) return RETRIEVE_K_DEFAULT;
  return Math.min(K_MAX, Math.max(K_MIN, Math.round(v)));
}

export function RetrieveOptions({
  value,
  onChange,
  idPrefix = "retrieve",
  className,
}: {
  value: RetrieveConfig;
  onChange: (next: RetrieveConfig) => void;
  idPrefix?: string;
  className?: string;
}) {
  return (
    <div className={className} data-testid="retrieve-options">
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_8rem]">
        <div className="grid gap-2">
          <Label htmlFor={`${idPrefix}-order`}>要找的方向</Label>
          <Select value={value.order} onValueChange={(v) => onChange({ ...value, order: v as RetrieveOrder })}>
            <SelectTrigger id={`${idPrefix}-order`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RETRIEVE_ORDERS.map((o) => (
                <SelectItem key={o} value={o}>
                  {retrieveOrderLabel[o]}
                  <span className="ml-2 font-mono text-[11px] text-muted-foreground">{o}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor={`${idPrefix}-k`}>每筆回傳幾個</Label>
          <Input
            id={`${idPrefix}-k`}
            type="number"
            inputMode="numeric"
            min={K_MIN}
            max={K_MAX}
            value={value.k}
            onChange={(e) => onChange({ ...value, k: clampK(Number(e.target.value)) })}
            className="font-mono tabular-nums"
          />
        </div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        最相似用來找同類樣本或重複品；最不相似用來找離群、與參考集差最多的樣本。影像模型的結果列可以開啟樣本，疊上模型關注的區塊。
      </p>
    </div>
  );
}
