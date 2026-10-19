"use client";

import { Bold, Code, Link as LinkIcon, List, type LucideIcon } from "lucide-react";
import { useRef, useState, type ComponentProps, type Ref } from "react";
import { Markdown } from "@/components/features/markdown";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { markdownCopy } from "@/i18n/zh-TW";
import { applyMarkdownTool, type MarkdownTool } from "@/lib/markdown-tools";
import { cn } from "@/lib/utils";

const TOOLS: { tool: MarkdownTool; icon: LucideIcon; label: string }[] = [
  { tool: "bold", icon: Bold, label: markdownCopy.bold },
  { tool: "list", icon: List, label: markdownCopy.list },
  { tool: "code", icon: Code, label: markdownCopy.code },
  { tool: "link", icon: LinkIcon, label: markdownCopy.link },
];

type Mode = "write" | "preview";

export interface MarkdownEditorProps extends Omit<ComponentProps<"textarea">, "value" | "onChange" | "rows"> {
  value: string;
  onChange: (value: string) => void;
  /** Minimum visible rows; the field grows with its content. */
  minRows?: number;
  ref?: Ref<HTMLTextAreaElement>;
}

/**
 * Markdown textarea with a formatting toolbar (粗體 / 清單 / 程式碼 / 連結) and an 編輯 / 預覽 switch.
 * Controlled (`value` / `onChange(string)`), so it drops into react-hook-form through `FormField` + `FormControl`,
 * which forward `id`, `aria-describedby` and `aria-invalid` to the textarea. Any other textarea prop passes through.
 */
export function MarkdownEditor({
  value,
  onChange,
  placeholder,
  minRows = 6,
  id,
  className,
  disabled,
  ref,
  ...rest
}: MarkdownEditorProps) {
  const [mode, setMode] = useState<Mode>("write");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const invalid = rest["aria-invalid"] === true || rest["aria-invalid"] === "true";
  const minHeight = `${minRows * 1.25 + 1}rem`; // text-sm line height × rows + vertical padding

  const attach = (el: HTMLTextAreaElement | null) => {
    textareaRef.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) ref.current = el;
  };

  const run = (tool: MarkdownTool) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const next = applyMarkdownTool(tool, value, ta.selectionStart, ta.selectionEnd);
    onChange(next.text);
    // The controlled value lands on the next render; restore focus and the selection after it.
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(next.start, next.end);
    });
  };

  return (
    <div
      data-slot="markdown-editor"
      data-invalid={invalid || undefined}
      className={cn(
        "rounded-md border border-input bg-background shadow-xs transition-[color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50 data-[invalid=true]:border-destructive data-[invalid=true]:ring-destructive/20",
        disabled && "opacity-50",
        className,
      )}
    >
      <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)} className="gap-0">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-2 py-1">
          <TabsList variant="line">
            <TabsTrigger value="write" className="px-2 text-xs">
              {markdownCopy.write}
            </TabsTrigger>
            <TabsTrigger value="preview" className="px-2 text-xs">
              {markdownCopy.preview}
            </TabsTrigger>
          </TabsList>
          <div role="toolbar" aria-label={markdownCopy.toolbar} className="flex items-center gap-0.5">
            {TOOLS.map(({ tool, icon: Icon, label }) => (
              <Tooltip key={tool}>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground"
                    aria-label={label}
                    disabled={disabled || mode !== "write"}
                    onClick={() => run(tool)}
                  >
                    <Icon />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{label}</TooltipContent>
              </Tooltip>
            ))}
          </div>
        </div>
        <TabsContent value="write">
          <Textarea
            ref={attach}
            id={id}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            rows={minRows}
            disabled={disabled}
            style={{ minHeight }}
            className="min-h-0 rounded-none border-0 bg-transparent! shadow-none focus-visible:border-transparent focus-visible:ring-0"
            {...rest}
          />
        </TabsContent>
        <TabsContent value="preview">
          <div className="px-3 py-2" style={{ minHeight }}>
            {value.trim() ? (
              <Markdown source={value} />
            ) : (
              <p className="text-sm text-subtle-foreground">{markdownCopy.emptyPreview}</p>
            )}
          </div>
        </TabsContent>
      </Tabs>
      <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-1.5 text-xs text-muted-foreground">
        <span>{markdownCopy.hint}</span>
        <span className="font-mono tabular-nums">{markdownCopy.chars(value.length)}</span>
      </div>
    </div>
  );
}
