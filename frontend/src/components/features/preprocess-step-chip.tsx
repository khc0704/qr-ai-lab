"use client";

// One step of a preprocessing chain as a chip: position, label, compact params, warnings, a popover to edit the
// params, move up / down and remove. Shared by the tabular and the image workbench.
import { ArrowDown, ArrowUp, Settings2, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { describeParams } from "@/lib/preprocess-steps";
import { cn } from "@/lib/utils";
import type { PreprocessOp, PreprocessParam, PreprocessStep } from "@/types/domain";

export function StepChip({
  index,
  step,
  op,
  warnings,
  onMove,
  onRemove,
  onParams,
  first,
  last,
}: {
  index: number;
  step: PreprocessStep;
  op?: PreprocessOp;
  warnings: string[];
  onMove: (delta: number) => void;
  onRemove: () => void;
  onParams: (params: Record<string, unknown>) => void;
  first: boolean;
  last: boolean;
}) {
  const label = op?.label ?? step.op;
  const summary = describeParams(step.params);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border bg-card py-0.5 pr-0.5 pl-2 text-xs",
        warnings.length ? "border-warning/40" : "border-border",
      )}
    >
      <span className="font-mono text-[11px] text-brand-ink">{index + 1}</span>
      <span className="font-medium">{label}</span>
      {summary ? (
        <span className="max-w-56 truncate font-mono text-[11px] text-muted-foreground">{summary}</span>
      ) : null}
      {warnings.length ? (
        <TriangleAlert className="size-3.5 text-warning" aria-label={`${warnings.length} 個警告`} />
      ) : null}
      {op?.params.length ? (
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={`編輯步驟 ${index + 1} 的參數`}>
              <Settings2 />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80 space-y-3">
            <div className="text-sm font-medium">{label}</div>
            {op.description ? <p className="text-xs text-muted-foreground">{op.description}</p> : null}
            {op.params.map((p) => (
              <ParamField
                key={p.name}
                param={p}
                value={step.params?.[p.name]}
                onChange={(v) => onParams({ [p.name]: v })}
              />
            ))}
            {warnings.length ? (
              <ul className="list-disc pl-4 text-xs text-warning">
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            ) : null}
          </PopoverContent>
        </Popover>
      ) : null}
      <Button variant="ghost" size="icon-sm" aria-label="上移" disabled={first} onClick={() => onMove(-1)}>
        <ArrowUp />
      </Button>
      <Button variant="ghost" size="icon-sm" aria-label="下移" disabled={last} onClick={() => onMove(1)}>
        <ArrowDown />
      </Button>
      <Button variant="ghost" size="icon-sm" aria-label="移除步驟" onClick={onRemove}>
        <X />
      </Button>
    </span>
  );
}

export function ParamField({
  param: p,
  value,
  onChange,
}: {
  param: PreprocessParam;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const id = `wb-${p.name}`;
  const v = value ?? p.default ?? "";
  if (p.type === "bool")
    return (
      <label className="flex items-center gap-2 text-sm">
        <Switch checked={Boolean(v)} onCheckedChange={(c) => onChange(c)} />
        {p.label}
      </label>
    );
  if (p.type === "choice")
    return (
      <div className="grid gap-1.5">
        <Label htmlFor={id}>{p.label}</Label>
        <Select value={String(v)} onValueChange={(x) => onChange((p.choices ?? []).find((c) => String(c) === x) ?? x)}>
          <SelectTrigger id={id} size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(p.choices ?? []).map((c) => (
              <SelectItem key={String(c)} value={String(c)}>
                {String(c)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {p.help ? <p className="text-[11px] text-muted-foreground">{p.help}</p> : null}
      </div>
    );
  const isList = p.type === "columns" || p.type === "list";
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{p.label}</Label>
      <Input
        id={id}
        className="h-8 font-mono text-xs"
        type={p.type === "int" || p.type === "float" ? "number" : "text"}
        step={p.type === "float" ? "any" : undefined}
        min={p.min}
        max={p.max}
        placeholder={isList ? "a,b,c（留空 = 自動）" : undefined}
        value={Array.isArray(v) ? v.join(",") : String(v)}
        onChange={(e) => {
          const raw = e.target.value;
          if (p.type === "int") onChange(raw === "" ? "" : Number.parseInt(raw, 10));
          else if (p.type === "float") onChange(raw === "" ? "" : Number(raw));
          else if (isList)
            onChange(
              raw
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean),
            );
          else onChange(raw);
        }}
      />
      {p.help ? <p className="text-[11px] text-muted-foreground">{p.help}</p> : null}
    </div>
  );
}
