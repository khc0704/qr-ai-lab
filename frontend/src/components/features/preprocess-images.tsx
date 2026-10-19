"use client";

// Image branch of the preprocessing editor: a live before / after gallery of the preview sample whose thumbnail
// size is a slider, a lightbox that shows one image at full preview size, and a drag-to-crop rectangle on the
// original that writes the `image.crop` ratios. Step chips and the generic add menu are shared with the tabular
// workbench (preprocess-step-chip.tsx).
import { Crop, Eye, LoaderCircle, TriangleAlert, ZoomIn } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { StepChip } from "@/components/features/preprocess-step-chip";
import type { PreviewFn } from "@/components/features/preprocess-workbench";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  addStep,
  cropFromSteps,
  moveStep,
  normalizeCropRect,
  removeStep,
  updateStepParams,
  upsertStep,
  type CropRect,
} from "@/lib/preprocess-steps";
import { cn } from "@/lib/utils";
import type { PreprocessOp, PreprocessStep, PreviewPayload, PreviewSide } from "@/types/domain";

/** How many images one preview asks for (the backend caps it by thumbnail size). */
const GALLERY_COUNT = 16;
const LIGHTBOX_THUMB = 1024;
const SIZE_MIN = 96;
const SIZE_MAX = 480;
const SIZE_DEFAULT = 176;

type PreviewImage = NonNullable<PreviewSide["images"]>[number];

/** The thumbnail resolution worth requesting for a given on-screen size (never upscale a blurry thumbnail). */
export function thumbResolution(size: number): number {
  return size <= 128 ? 128 : size <= 256 ? 256 : 512;
}

export function ImageWorkbench({
  ops,
  steps,
  onChange,
  spec,
  uploadId,
  onPreview,
  onPreviewLoaded,
  disabledReason,
}: {
  ops: PreprocessOp[];
  steps: PreprocessStep[];
  onChange: (steps: PreprocessStep[]) => void;
  spec: Record<string, unknown>;
  uploadId?: number | string;
  onPreview: PreviewFn;
  onPreviewLoaded?: (payload: PreviewPayload) => void;
  /** Geometric ops (crop, flip, rotate, resize) are refused for box / mask labels. */
  disabledReason?: string;
}) {
  const byId = useMemo(() => Object.fromEntries(ops.map((o) => [o.id, o])), [ops]);
  const cropOp = byId["image.crop"];
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [size, setSize] = useState(SIZE_DEFAULT);
  const [adding, setAdding] = useState("");
  const [lightbox, setLightbox] = useState<string | null>(null);
  const seq = useRef(0);
  const specKey = JSON.stringify(spec);
  const stepsKey = JSON.stringify(steps);
  const resolution = thumbResolution(size);
  // Parents pass inline objects / callbacks; keep the latest ones in a ref (written in an effect, never during
  // render) so the debounced preview only re-arms when the serialised inputs change.
  const latest = useRef({ steps, spec, onPreview, onPreviewLoaded });
  useEffect(() => {
    latest.current = { steps, spec, onPreview, onPreviewLoaded };
  });
  const runPreview = useCallback(() => {
    if (!uploadId) return;
    const { steps: st, spec: sp, onPreview: fn, onPreviewLoaded: loaded } = latest.current;
    const my = ++seq.current;
    setLoading(true);
    void fn(st, sp, GALLERY_COUNT, { thumb: thumbResolution(size) }).then((r) => {
      if (my !== seq.current) return;
      setLoading(false);
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      setPreview(r.data);
      loaded?.(r.data);
    });
  }, [uploadId, size]);
  // Debounced live preview whenever the steps / spec / upload / thumbnail resolution change.
  useEffect(() => {
    if (!uploadId) return;
    const t = setTimeout(runPreview, 400);
    return () => clearTimeout(t);
  }, [uploadId, stepsKey, specKey, resolution, runPreview]);

  const before = preview?.before.images ?? [];
  const after = preview?.after.images ?? [];
  const afterById = new Map(after.map((im) => [im.id, im]));
  const warnings = preview?.warnings ?? [];
  const addGeneric = (id: string) => {
    const op = byId[id];
    if (!op) return;
    onChange(addStep(steps, op));
    setAdding("");
  };
  const applyCrop = (rect: CropRect) => {
    if (!cropOp) return;
    onChange(upsertStep(steps, cropOp, { ...rect }));
    toast.success("已套用裁切，預覽會重新計算");
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <Select value={adding} onValueChange={addGeneric}>
          <SelectTrigger className="w-64" size="sm" aria-label="新增前處理步驟">
            <SelectValue placeholder="＋ 新增步驟…" />
          </SelectTrigger>
          <SelectContent>
            {ops.map((o) => (
              <SelectItem key={o.id} value={o.id} disabled={o.geometric && Boolean(disabledReason)}>
                {o.label}
                <span className="ml-2 font-mono text-[11px] text-muted-foreground">{o.id}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button type="button" variant="outline" size="sm" onClick={runPreview} disabled={!uploadId || loading}>
          {loading ? <LoaderCircle className="animate-spin" /> : <Eye />}
          抽樣預覽
        </Button>
        {disabledReason ? <span className="text-xs text-warning">{disabledReason}</span> : null}
        <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          縮圖大小
          <input
            type="range"
            min={SIZE_MIN}
            max={SIZE_MAX}
            step={16}
            value={size}
            onChange={(e) => setSize(Number(e.target.value))}
            className="w-36 accent-primary"
            aria-label="縮圖大小"
          />
          <span className="w-12 font-mono tabular-nums">{size}px</span>
        </label>
      </div>

      {/* step chain */}
      <div className="flex flex-wrap items-center gap-1.5" data-testid="step-chips">
        <span className="text-label">步驟</span>
        {steps.length === 0 ? (
          <span className="text-xs text-muted-foreground">
            還沒有步驟：用上面的選單加入，或點一張圖放大後拖曳框選要保留的區域。
          </span>
        ) : null}
        {steps.map((s, i) => (
          <StepChip
            key={`${s.op}-${i}`}
            index={i}
            step={s}
            op={byId[s.op]}
            warnings={preview?.step_details?.[i]?.warnings ?? []}
            onMove={(d) => onChange(moveStep(steps, i, i + d))}
            onRemove={() => onChange(removeStep(steps, i))}
            onParams={(p) => onChange(updateStepParams(steps, i, p))}
            first={i === 0}
            last={i === steps.length - 1}
          />
        ))}
      </div>

      {preview ? (
        <p className="font-mono text-xs text-muted-foreground tabular-nums">
          抽樣 <b className="text-foreground">{before.length}</b> 張（依資料夾平均取樣）；點圖放大，整個檔案由任務處理
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">{uploadId ? "計算預覽中…" : "上傳檔案後會自動抽樣預覽。"}</p>
      )}
      {warnings.length ? (
        <Alert className="border-warning/30 bg-warning/10">
          <TriangleAlert className="text-warning" />
          <AlertTitle>預覽發現的問題</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-0.5 pl-4">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      {/* gallery */}
      <div className="relative min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-card p-3">
        {loading ? (
          <div
            className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 text-sm text-muted-foreground backdrop-blur-[1px]"
            role="status"
          >
            預覽計算中…
          </div>
        ) : null}
        {before.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">沒有影像可以顯示</p>
        ) : (
          <ul className="flex flex-wrap gap-3" data-testid="image-gallery">
            {before.map((im) => (
              <li key={im.id}>
                <ImageCard before={im} after={afterById.get(im.id)} size={size} onOpen={() => setLightbox(im.id)} />
              </li>
            ))}
          </ul>
        )}
      </div>

      <Lightbox
        id={lightbox}
        onClose={() => setLightbox(null)}
        uploadId={uploadId}
        stepsKey={stepsKey}
        specKey={specKey}
        latest={latest}
        crop={cropFromSteps(steps)}
        canCrop={Boolean(cropOp) && !disabledReason}
        cropDisabledReason={disabledReason}
        onApplyCrop={applyCrop}
      />
    </div>
  );
}

function ImageCard({
  before,
  after,
  size,
  onOpen,
}: {
  before: PreviewImage;
  after?: PreviewImage;
  size: number;
  onOpen: () => void;
}) {
  const box = { width: size, height: size };
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group rounded-lg border border-border bg-background p-2 text-left transition-colors outline-none hover:border-primary/50 focus-visible:ring-[3px] focus-visible:ring-ring/50"
      aria-label={`放大 ${before.id}`}
    >
      <div className="flex gap-2">
        <figure className="text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:image/png;base64,${before.png_base64}`}
            alt=""
            style={box}
            className="rounded-md border border-border bg-muted object-contain"
          />
          <figcaption className="mt-1 text-[10px] text-muted-foreground">原始</figcaption>
        </figure>
        <figure className="text-center">
          {after ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`data:image/png;base64,${after.png_base64}`}
              alt=""
              style={box}
              className="rounded-md border border-primary/40 bg-muted object-contain"
            />
          ) : (
            <div style={box} className="rounded-md border border-dashed border-border" />
          )}
          <figcaption className="mt-1 text-[10px] text-muted-foreground">處理後</figcaption>
        </figure>
      </div>
      <div
        className="mt-1 flex items-center justify-between gap-2 font-mono text-[10px] text-muted-foreground tabular-nums"
        style={{ maxWidth: size * 2 + 8 }}
      >
        <span className="truncate" title={before.id}>
          {before.id}
        </span>
        <span className="shrink-0">
          {before.width}×{before.height}
          {after && (after.width !== before.width || after.height !== before.height)
            ? ` → ${after.width}×${after.height}`
            : ""}
        </span>
        <ZoomIn className="size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
    </button>
  );
}

type Drag = { x0: number; y0: number; x1: number; y1: number };

function Lightbox({
  id,
  onClose,
  uploadId,
  stepsKey,
  specKey,
  latest,
  crop,
  canCrop,
  cropDisabledReason,
  onApplyCrop,
}: {
  id: string | null;
  onClose: () => void;
  uploadId?: number | string;
  stepsKey: string;
  specKey: string;
  latest: React.RefObject<{ steps: PreprocessStep[]; spec: Record<string, unknown>; onPreview: PreviewFn }>;
  /** The crop the step chain already applies, drawn as a dashed outline on the original. */
  crop: CropRect | null;
  canCrop: boolean;
  cropDisabledReason?: string;
  onApplyCrop: (rect: CropRect) => void;
}) {
  // The loaded payload remembers which (image, chain, spec) it answers, so "loading" is derived instead of being
  // set from inside the effect, and a payload from a previous key is never shown for the current one.
  const key = id === null ? null : `${id}\u0000${stepsKey}\u0000${specKey}`;
  const [big, setBig] = useState<{ key: string; data: PreviewPayload } | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [rect, setRect] = useState<CropRect | null>(null);
  // One image at full preview size, re-fetched whenever the chain changes while the dialog is open.
  useEffect(() => {
    if (!key || !id || !uploadId) return;
    // Parse the serialised chain instead of reading the parent's ref: a child's effect runs before the parent's
    // ref-updating effect, so right after 套用裁切 the ref would still hold the previous chain.
    const steps = JSON.parse(stepsKey) as PreprocessStep[];
    const spec = JSON.parse(specKey) as Record<string, unknown>;
    const { onPreview } = latest.current;
    let cancelled = false;
    void onPreview(steps, spec, 1, { thumb: LIGHTBOX_THUMB, imageIds: [id] }).then((r) => {
      if (cancelled) return;
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      setBig({ key, data: r.data });
    });
    return () => {
      cancelled = true;
    };
  }, [key, id, uploadId, stepsKey, specKey, latest]);
  const open = id !== null;
  const current = big && big.key === key ? big.data : null;
  const loading = open && !current;
  const beforeIm = current?.before.images?.[0];
  const afterIm = current?.after.images?.[0];

  const point = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(r.width, Math.max(0, e.clientX - r.left)),
      y: Math.min(r.height, Math.max(0, e.clientY - r.top)),
      w: r.width,
      h: r.height,
    };
  };
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!canCrop) return;
    const p = point(e);
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag) return;
    const p = point(e);
    setDrag({ ...drag, x1: p.x, y1: p.y });
  };
  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag) return;
    const p = point(e);
    setRect(normalizeCropRect(drag.x0, drag.y0, drag.x1, drag.y1, p.w, p.h));
    setDrag(null);
  };
  const live: CropRect | null = drag
    ? {
        left: Math.min(drag.x0, drag.x1),
        top: Math.min(drag.y0, drag.y1),
        right: Math.max(drag.x0, drag.x1),
        bottom: Math.max(drag.y0, drag.y1),
      }
    : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setRect(null);
          setDrag(null);
          onClose();
        }
      }}
    >
      <DialogContent className="flex max-h-[92vh] flex-col gap-3 overflow-hidden sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle className="truncate font-mono text-base">{id}</DialogTitle>
          <DialogDescription>
            {canCrop
              ? "在左邊的原圖上拖曳框選要保留的區域，再按「套用裁切」；右邊是目前步驟處理後的結果。"
              : (cropDisabledReason ?? "右邊是目前步驟處理後的結果。")}
          </DialogDescription>
        </DialogHeader>
        <div className="grid min-h-0 flex-1 gap-4 overflow-auto lg:grid-cols-2">
          <figure className="min-w-0 space-y-1">
            <figcaption className="flex items-center justify-between text-label">
              <span>原始</span>
              {beforeIm ? (
                <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                  {beforeIm.width}×{beforeIm.height}
                </span>
              ) : null}
            </figcaption>
            {beforeIm ? (
              <div className="relative w-full" style={fitStyle(beforeIm)}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`data:image/png;base64,${beforeIm.png_base64}`}
                  alt=""
                  draggable={false}
                  className="absolute inset-0 h-full w-full rounded-md border border-border bg-muted"
                />
                <div
                  className={cn("absolute inset-0 select-none", canCrop ? "cursor-crosshair touch-none" : "")}
                  data-testid="crop-surface"
                  onPointerDown={onPointerDown}
                  onPointerMove={onPointerMove}
                  onPointerUp={onPointerUp}
                  onPointerCancel={() => setDrag(null)}
                >
                  {crop && !rect && !live ? <RectOverlay rect={crop} ratio dashed /> : null}
                  {live ? <RectOverlay rect={live} /> : rect ? <RectOverlay rect={rect} ratio /> : null}
                </div>
              </div>
            ) : (
              <Placeholder loading={loading} />
            )}
          </figure>
          <figure className="min-w-0 space-y-1">
            <figcaption className="flex items-center justify-between text-label">
              <span>處理後</span>
              {afterIm ? (
                <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                  {afterIm.width}×{afterIm.height}
                </span>
              ) : null}
            </figcaption>
            {afterIm ? (
              <div className="relative w-full" style={fitStyle(afterIm)}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`data:image/png;base64,${afterIm.png_base64}`}
                  alt=""
                  className="absolute inset-0 h-full w-full rounded-md border border-primary/40 bg-muted"
                />
              </div>
            ) : (
              <Placeholder loading={loading} />
            )}
          </figure>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          {rect ? (
            <span className="font-mono text-xs text-muted-foreground tabular-nums">
              left {rect.left} · top {rect.top} · right {rect.right} · bottom {rect.bottom}
            </span>
          ) : crop ? (
            <span className="font-mono text-xs text-muted-foreground tabular-nums">
              目前裁切：{crop.left} / {crop.top} / {crop.right} / {crop.bottom}（虛線）
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">{canCrop ? "尚未框選" : ""}</span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {loading ? <LoaderCircle className="size-4 animate-spin text-muted-foreground" /> : null}
            <Button type="button" variant="outline" size="sm" disabled={!rect} onClick={() => setRect(null)}>
              清除框選
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!rect || !canCrop}
              onClick={() => {
                if (rect) onApplyCrop(rect);
                setRect(null);
              }}
              data-testid="apply-crop"
            >
              <Crop />
              套用裁切
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Size a preview image to the column width, up or down, never taller than 68vh, keeping its aspect ratio exactly:
 * the crop surface sits on top of it and must coincide with the pixels (no letterboxing).
 */
function fitStyle(im: PreviewImage): React.CSSProperties {
  const ratio = im.width / Math.max(1, im.height);
  return { aspectRatio: `${im.width} / ${im.height}`, maxWidth: `calc(68vh * ${ratio})` };
}

function Placeholder({ loading }: { loading: boolean }) {
  return (
    <div className="flex h-72 w-full max-w-96 items-center justify-center rounded-md border border-border bg-muted text-sm text-muted-foreground">
      {loading ? "載入中…" : "沒有影像"}
    </div>
  );
}

/** A rectangle over the image: `ratio` rects are 0–1 fractions, otherwise pixels of the surface. */
function RectOverlay({ rect, ratio, dashed }: { rect: CropRect; ratio?: boolean; dashed?: boolean }) {
  const u = (v: number) => (ratio ? `${v * 100}%` : `${v}px`);
  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute border-2 border-primary bg-primary/10",
        dashed && "border-dashed bg-transparent",
      )}
      style={{
        left: u(rect.left),
        top: u(rect.top),
        width: u(rect.right - rect.left),
        height: u(rect.bottom - rect.top),
      }}
    />
  );
}
