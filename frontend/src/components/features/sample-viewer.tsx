"use client";

// Side drawer that shows the sample behind a result row or an embedding point, read from the file the
// browser still holds (see lib/local-data.ts). An inline row (pasted JSON) is shown as-is; an uploaded file is
// resolved locally (zip entry → image, CSV → row + curve for wide numeric rows). When the file is not in this
// tab any more (reload, another browser) the user can re-attach it, verified against the job's fingerprint.
import { Eye, FileUp, ImageOff, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ExpandableValue } from "@/components/features/expandable-value";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  attachLocalFile,
  matchesFingerprint,
  readSample,
  useLocalFile,
  type Fingerprint,
  type Sample,
  type SampleRef,
} from "@/lib/local-data";
import { formatBytes } from "@/lib/format";

export interface SampleTarget {
  ref: SampleRef;
  /** The row itself when the input was pasted inline (no file to read). */
  inlineRow?: Record<string, unknown>;
  /** URL of a transparent heat overlay the model wrote for this sample (attention / deviation map). */
  overlayUrl?: string;
  overlayLabel?: string;
}

export function SampleViewer({
  open,
  onOpenChange,
  dataKey,
  target,
  fingerprint,
  accept,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Key of the local file (job:<id>); undefined when the input was inline. */
  dataKey?: string;
  target: SampleTarget | null;
  /** What the job recorded about its upload, used to verify a re-attached file. */
  fingerprint?: Fingerprint;
  accept?: string;
}) {
  const local = useLocalFile(dataKey);
  const title = target?.ref.id ?? "";
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-xl">
        <SheetHeader className="border-b border-border px-6 py-3">
          <SheetTitle className="truncate font-mono text-base">{title || "樣本"}</SheetTitle>
          <SheetDescription>
            {target?.inlineRow
              ? "直接輸入的列，顯示送出推論時的內容。"
              : "從你這個瀏覽器上傳的原始檔案讀出來的樣本；伺服器沒有保存資料。"}
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
          {!target ? null : target.inlineRow ? (
            <KeyValues columns={Object.keys(target.inlineRow)} values={Object.values(target.inlineRow)} />
          ) : !dataKey ? (
            <p className="text-sm text-muted-foreground">這個任務的輸入來自資料來源，瀏覽器沒有原始檔案可以顯示。</p>
          ) : local ? (
            <SampleBody fileKey={`${local.name}:${local.attachedAt}`} target={target} local={local} />
          ) : (
            <Reattach dataKey={dataKey} fingerprint={fingerprint} accept={accept} />
          )}
        </div>
        {local ? (
          <div className="flex items-center justify-between gap-2 border-t border-border px-6 py-2 font-mono text-[11px] text-muted-foreground">
            <span className="truncate">{local.name}</span>
            <span className="shrink-0 tabular-nums">{formatBytes(local.size)}</span>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function SampleBody({
  fileKey,
  target,
  local,
}: {
  fileKey: string;
  target: SampleTarget;
  local: NonNullable<ReturnType<typeof useLocalFile>>;
}) {
  const key = `${fileKey}|${target.ref.id}|${target.ref.index ?? ""}|${target.ref.idColumn ?? ""}`;
  const [loaded, setLoaded] = useState<{ key: string; sample: Sample } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void readSample(local, target.ref).then((sample) => {
      if (!cancelled) setLoaded({ key, sample });
    });
    return () => {
      cancelled = true;
    };
  }, [key, local, target.ref]);
  const sample = loaded?.key === key ? loaded.sample : null;
  if (!sample)
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" /> 讀取中…
      </p>
    );
  if (sample.kind === "image")
    return (
      <ImageView
        key={`${key}:${sample.name}`}
        blob={sample.blob}
        name={sample.name}
        overlayUrl={target.overlayUrl}
        overlayLabel={target.overlayLabel}
      />
    );
  if (sample.kind === "row") return <RowView columns={sample.columns} values={sample.values} index={sample.index} />;
  if (sample.kind === "text")
    return (
      <pre className="rounded-md border border-border bg-muted p-3 font-mono text-xs whitespace-pre-wrap">
        {sample.text}
      </pre>
    );
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <ImageOff className="size-4" /> {sample.reason}
    </p>
  );
}

function ImageView({
  blob,
  name,
  overlayUrl,
  overlayLabel,
}: {
  blob: Blob;
  name: string;
  overlayUrl?: string;
  overlayLabel?: string;
}) {
  // Mounted with key={name}, so one object URL per image; revoked when the view unmounts.
  const [url] = useState(() => URL.createObjectURL(blob));
  useEffect(() => () => URL.revokeObjectURL(url), [url]);
  const [showOverlay, setShowOverlay] = useState(true);
  const [opacity, setOpacity] = useState(70);
  const [overlayFailed, setOverlayFailed] = useState(false);
  const overlay = overlayUrl && !overlayFailed;
  return (
    <figure className="space-y-2">
      <div className="relative w-full overflow-hidden rounded-md border border-border bg-muted">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt={name} className="block max-h-[70vh] w-full object-contain" />
        {overlay && showOverlay ? (
          // the overlay is rendered at the image's own size, so stretching it over the same box lines up
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={overlayUrl}
            alt=""
            aria-hidden
            onError={() => setOverlayFailed(true)}
            style={{ opacity: opacity / 100 }}
            className="pointer-events-none absolute inset-0 h-full w-full object-contain"
            data-testid="sample-overlay"
          />
        ) : null}
      </div>
      {overlay ? (
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <Label htmlFor="overlay-toggle" className="flex items-center gap-2 text-xs">
            <Switch id="overlay-toggle" checked={showOverlay} onCheckedChange={setShowOverlay} />
            <Eye className="size-3.5" />
            {overlayLabel ?? "模型關注的區塊"}
          </Label>
          <label className="flex items-center gap-2 text-muted-foreground">
            透明度
            <input
              type="range"
              min={10}
              max={100}
              value={opacity}
              onChange={(e) => setOpacity(Number(e.target.value))}
              className="w-28 accent-primary"
              aria-label="關注區塊的透明度"
              disabled={!showOverlay}
            />
          </label>
          <span className="text-muted-foreground">紅 = 影響判斷最多的位置；只顯示模型實際看到的中央區域。</span>
        </div>
      ) : null}
      <figcaption className="truncate font-mono text-[11px] text-muted-foreground">{name}</figcaption>
    </figure>
  );
}

const MIN_CURVE_POINTS = 8;

function RowView({ columns, values, index }: { columns: string[]; values: string[]; index: number }) {
  // A wide numeric row (spectrum / sequence) is also drawn as a curve.
  const numeric = values.map((v) => Number(v)).filter((v, i) => v !== 0 || values[i].trim() !== "");
  const curve =
    columns.length >= MIN_CURVE_POINTS && values.every((v) => v.trim() === "" || Number.isFinite(Number(v)));
  return (
    <div className="space-y-4">
      <p className="font-mono text-[11px] text-muted-foreground tabular-nums">第 {index + 1} 列</p>
      {curve ? <Curve values={numeric} /> : null}
      <KeyValues columns={columns} values={values} />
    </div>
  );
}

function Curve({ values }: { values: number[] }) {
  const W = 480;
  const H = 160;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const sx = (i: number) => (values.length <= 1 ? 0 : (i / (values.length - 1)) * W);
  const sy = (v: number) => (hi === lo ? H / 2 : H - ((v - lo) / (hi - lo)) * (H - 8) - 4);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-40 w-full rounded-md border border-border bg-background"
      role="img"
      aria-label="曲線"
    >
      <polyline
        fill="none"
        strokeWidth={1.2}
        className="stroke-primary"
        points={values.map((v, i) => `${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join(" ")}
      />
    </svg>
  );
}

function KeyValues({ columns, values }: { columns: string[]; values: unknown[] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-x-3 gap-y-1 font-mono text-xs tabular-nums">
      {columns.map((c, i) => (
        <div key={`${c}-${i}`} className="contents">
          <dt className="truncate text-muted-foreground" title={c}>
            {c}
          </dt>
          <dd className="min-w-0">
            <ExpandableValue
              className="justify-start"
              text={values[i] === null || values[i] === undefined || values[i] === "" ? "—" : String(values[i])}
            />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Reattach({ dataKey, fingerprint, accept }: { dataKey: string; fingerprint?: Fingerprint; accept?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await matchesFingerprint(file, fingerprint ?? {});
      if (!r.ok) {
        toast.error(`不是同一個檔案：${r.reason}`);
        return;
      }
      attachLocalFile(dataKey, file);
      toast.success(`已重新附加 ${file.name}`);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <div className="space-y-3 rounded-lg border border-dashed border-border p-4 text-sm">
      <p className="font-medium">原始檔案不在這個瀏覽器裡</p>
      <p className="text-muted-foreground">
        伺服器不保存資料，樣本只能從上傳時的那個檔案讀出。重新選擇同一個檔案即可，會用大小
        {fingerprint?.sha256 ? "與 sha256" : ""}比對確認是同一份；檔案一樣留在你的電腦。
      </p>
      {fingerprint?.name ? (
        <p className="font-mono text-[11px] text-muted-foreground">
          {fingerprint.name}
          {fingerprint.size ? ` · ${formatBytes(fingerprint.size)}` : ""}
        </p>
      ) : null}
      <input
        ref={input}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => void pick(e.target.files?.[0])}
        data-testid="reattach-input"
      />
      <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => input.current?.click()}>
        {busy ? <LoaderCircle className="animate-spin" /> : <FileUp />}
        重新附加原始檔
      </Button>
    </div>
  );
}
