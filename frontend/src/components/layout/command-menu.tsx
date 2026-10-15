"use client";

import { ClipboardList, FolderKanban, Gauge, House, ListOrdered, MessagesSquare, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Kbd } from "@/components/ui/kbd";
import { common, nav } from "@/i18n/zh-TW";

export interface CommandEntry {
  label: string;
  href: string;
  hint?: string;
}

export function CommandMenu({ projects, isAdmin }: { projects: CommandEntry[]; isAdmin: boolean }) {
  const [open, setOpen] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="hidden w-56 justify-between text-muted-foreground md:flex"
        onClick={() => setOpen(true)}
      >
        <span className="inline-flex items-center gap-2">
          <Search className="size-4" />
          {common.search}
        </span>
        <Kbd>⌘K</Kbd>
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden"
        aria-label={common.search}
        onClick={() => setOpen(true)}
      >
        <Search />
      </Button>
      <CommandDialog open={open} onOpenChange={setOpen} title="搜尋" description={common.searchPlaceholder}>
        <CommandInput placeholder={common.searchPlaceholder} />
        <CommandList>
          <CommandEmpty>{common.noData}</CommandEmpty>
          <CommandGroup heading="前往">
            <CommandItem onSelect={() => go("/")}>
              <House />
              {nav.home}
            </CommandItem>
            <CommandItem onSelect={() => go("/discussions")}>
              <MessagesSquare />
              {nav.discussions}
            </CommandItem>
            <CommandItem onSelect={() => go("/project-requests")}>
              <ClipboardList />
              {nav.projectRequests}
            </CommandItem>
            <CommandItem onSelect={() => go("/projects")}>
              <FolderKanban />
              {nav.projects}
            </CommandItem>
            {isAdmin ? (
              <>
                <CommandItem onSelect={() => go("/admin")}>
                  <Gauge />
                  {nav.adminDashboard}
                </CommandItem>
                <CommandItem onSelect={() => go("/admin/queue")}>
                  <ListOrdered />
                  {nav.adminQueue}
                </CommandItem>
              </>
            ) : null}
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading="專案">
            {projects.map((p) => (
              <CommandItem key={p.href} value={`${p.label} ${p.hint ?? ""}`} onSelect={() => go(p.href)}>
                <FolderKanban />
                <span>{p.label}</span>
                {p.hint ? <span className="ml-auto font-mono text-xs text-muted-foreground">{p.hint}</span> : null}
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </>
  );
}
