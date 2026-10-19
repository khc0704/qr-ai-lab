import ReactMarkdown, { type Components } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

// react-markdown hands every override the hast `node`; it must not reach the DOM element.
function dom<T extends { node?: unknown }>(props: T): Omit<T, "node"> {
  const { node, ...rest } = props;
  void node;
  return rest;
}

/** GitHub-flavoured Markdown mapped onto the design tokens. Raw HTML never renders (rehype-sanitize, default schema). */
const components: Components = {
  h1: (p) => <h1 className="mt-5 mb-2 text-xl font-semibold tracking-tight first:mt-0" {...dom(p)} />,
  h2: (p) => <h2 className="mt-5 mb-2 text-lg font-semibold tracking-tight first:mt-0" {...dom(p)} />,
  h3: (p) => <h3 className="mt-4 mb-1.5 text-base font-semibold tracking-tight first:mt-0" {...dom(p)} />,
  h4: (p) => <h4 className="mt-3 mb-1 text-sm font-semibold first:mt-0" {...dom(p)} />,
  h5: (p) => <h5 className="mt-3 mb-1 text-sm font-semibold first:mt-0" {...dom(p)} />,
  h6: (p) => <h6 className="mt-3 mb-1 text-sm font-semibold text-muted-foreground first:mt-0" {...dom(p)} />,
  p: (p) => <p className="my-2 leading-relaxed first:mt-0 last:mb-0" {...dom(p)} />,
  a: (p) => (
    <a
      className="break-words text-brand-ink underline-offset-4 hover:underline"
      rel="noopener noreferrer"
      {...dom(p)}
    />
  ),
  ul: (p) => <ul className="my-2 list-disc space-y-1 pl-5" {...dom(p)} />,
  ol: (p) => <ol className="my-2 list-decimal space-y-1 pl-5" {...dom(p)} />,
  li: (p) => <li className="leading-relaxed [&>p]:my-0" {...dom(p)} />,
  blockquote: (p) => <blockquote className="my-2 border-l-2 border-border pl-3 text-muted-foreground" {...dom(p)} />,
  hr: (p) => <hr className="my-4 border-border" {...dom(p)} />,
  pre: (p) => (
    <pre
      className="my-3 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed [&>code]:rounded-none [&>code]:bg-transparent [&>code]:p-0 [&>code]:text-xs"
      {...dom(p)}
    />
  ),
  code: (p) => <code className="rounded-sm bg-muted px-1 py-0.5 font-mono text-[0.85em]" {...dom(p)} />,
  table: (p) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm" {...dom(p)} />
    </div>
  ),
  thead: (p) => <thead className="bg-muted" {...dom(p)} />,
  th: (p) => <th className="border border-border px-2 py-1 text-left font-medium" {...dom(p)} />,
  td: (p) => <td className="border border-border px-2 py-1 align-top" {...dom(p)} />,
  // User content points at arbitrary (intranet) URLs and the server is offline, so next/image cannot be used.
  // eslint-disable-next-line @next/next/no-img-element
  img: (p) => <img {...dom(p)} alt={p.alt ?? ""} className="my-2 max-w-full rounded-md border border-border" />,
};

/**
 * Renders a Markdown string (GFM: tables, task lists, strikethrough, autolinks) with semantic-token styling.
 * Usable from Server and Client Components alike; pair with `MarkdownEditor` for input.
 */
export function Markdown({ source, className }: { source: string; className?: string }) {
  return (
    <div data-slot="markdown" className={cn("text-sm break-words text-foreground", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]} components={components}>
        {source}
      </ReactMarkdown>
    </div>
  );
}
