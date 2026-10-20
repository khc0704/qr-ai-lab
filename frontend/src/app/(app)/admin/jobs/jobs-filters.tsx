"use client";

// Filters of the 任務管理 page, kept in the URL so a filtered view can be shared and paginated.
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { pageHref } from "@/components/features/pagination";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { jobKindLabel } from "@/i18n/zh-TW";

export interface JobsFilterValues {
  status: string;
  kind: string;
  project: string;
  q: string;
  ephemeral: string;
}

const ALL = "all";
const STATUS_OPTIONS = [
  [ALL, "全部狀態"],
  ["active", "執行中 / 排隊中"],
  ["finished", "已結束"],
  ["succeeded", "成功"],
  ["failed", "失敗"],
  ["cancelled", "已取消"],
] as const;
const EPHEMERAL_OPTIONS = [
  [ALL, "含一次性推論"],
  ["none", "不含一次性推論"],
  ["only", "只看一次性推論"],
] as const;

export function JobsFilters({ values }: { values: JobsFilterValues }) {
  const router = useRouter();
  const [draft, setDraft] = useState(values);
  const apply = (next: JobsFilterValues) => {
    setDraft(next);
    const params = Object.fromEntries(Object.entries(next).map(([k, v]) => [k, v && v !== ALL ? v : undefined]));
    router.push(pageHref("/admin/jobs", params, 1));
  };
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        apply(draft);
      }}
      data-testid="jobs-filters"
    >
      <Select value={draft.status || ALL} onValueChange={(v) => apply({ ...draft, status: v })}>
        <SelectTrigger size="sm" className="w-40" aria-label="狀態">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {STATUS_OPTIONS.map(([v, label]) => (
            <SelectItem key={v} value={v}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={draft.kind || ALL} onValueChange={(v) => apply({ ...draft, kind: v })}>
        <SelectTrigger size="sm" className="w-32" aria-label="種類">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>全部種類</SelectItem>
          {(Object.keys(jobKindLabel) as (keyof typeof jobKindLabel)[]).map((k) => (
            <SelectItem key={k} value={k}>
              {jobKindLabel[k]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={draft.ephemeral || ALL} onValueChange={(v) => apply({ ...draft, ephemeral: v })}>
        <SelectTrigger size="sm" className="w-40" aria-label="一次性推論">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {EPHEMERAL_OPTIONS.map(([v, label]) => (
            <SelectItem key={v} value={v}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        value={draft.project}
        onChange={(e) => setDraft({ ...draft, project: e.target.value })}
        placeholder="專案 slug"
        aria-label="專案 slug"
        className="h-8 w-40 font-mono text-xs"
      />
      <Input
        value={draft.q}
        onChange={(e) => setDraft({ ...draft, q: e.target.value })}
        placeholder="任務名稱或 #id"
        aria-label="任務名稱或 id"
        className="h-8 w-48 text-xs"
      />
      <Button type="submit" variant="outline" size="sm">
        <Search />
        篩選
      </Button>
      {Object.values(values).some(Boolean) ? (
        <Button type="button" variant="ghost" size="sm" onClick={() => router.push("/admin/jobs")}>
          清除
        </Button>
      ) : null}
    </form>
  );
}
