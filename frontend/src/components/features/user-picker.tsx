"use client";

// Combobox that picks a user from our own `users` table (Keycloak only supplies identity, so every picker in
// the app searches the same directory): browser → /api/users/lookup (route handler adds the token) → backend
// GET /users/lookup. Any logged-in user may search; rows carry display name, @username and e-mail only.
// Used by the member invite dialog; the project application form reuses it for its member list.
import { Check, ChevronsUpDown, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { toUserLookup } from "@/lib/api/mappers";
import { withBase } from "@/lib/base-path";
import { cn } from "@/lib/utils";
import type { UserLookup } from "@/types/domain";

/** The backend answers [] below this many characters; the picker says so instead of searching. */
export const USER_PICKER_MIN_CHARS = 2;
const DEBOUNCE_MS = 250;

const text = {
  placeholder: "搜尋帳號、姓名或 email",
  pick: "選擇使用者",
  search: "搜尋使用者",
  clear: "清除選擇",
  tooShort: `輸入至少 ${USER_PICKER_MIN_CHARS} 個字`,
  searching: "搜尋中…",
  none: "找不到使用者",
  failed: "搜尋失敗，請再試一次",
} as const;

export interface UserPickerProps {
  value: UserLookup | null;
  onChange: (user: UserLookup | null) => void;
  placeholder?: string;
  /** Hidden from the results, e.g. people who are already members. */
  excludeIds?: number[];
  disabled?: boolean;
  /** id of the trigger button so a <Label htmlFor> can point at it. */
  id?: string;
  className?: string;
}

interface Lookup {
  q: string;
  users: UserLookup[];
  error: boolean;
}

/** GET /api/users/lookup?q= through the route handler (same origin, under the site's base path). */
export async function fetchUserLookup(q: string, signal?: AbortSignal): Promise<UserLookup[]> {
  const res = await fetch(withBase(`/api/users/lookup?q=${encodeURIComponent(q)}`), { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return ((await res.json()) as Record<string, unknown>[]).map(toUserLookup);
}

export function UserPicker({
  value,
  onChange,
  placeholder = text.placeholder,
  excludeIds,
  disabled,
  id,
  className,
}: UserPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const term = query.trim();
  const active = term.length >= USER_PICKER_MIN_CHARS;

  // Debounced lookup; the result remembers the term it answers so a stale response never shows for a newer one.
  useEffect(() => {
    if (!active) return;
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      try {
        setLookup({ q: term, users: await fetchUserLookup(term, ctrl.signal), error: false });
      } catch {
        if (!ctrl.signal.aborted) setLookup({ q: term, users: [], error: true });
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [term, active]);

  const current = active && lookup?.q === term ? lookup : null;
  const excluded = new Set(excludeIds ?? []);
  const users = current ? current.users.filter((u) => !excluded.has(u.id)) : [];
  const empty = !active ? text.tooShort : !current ? text.searching : current.error ? text.failed : text.none;

  const select = (user: UserLookup) => {
    onChange(user);
    setQuery("");
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <div className={cn("flex items-center gap-1", className)}>
        <PopoverTrigger asChild>
          <Button
            id={id}
            type="button"
            variant="outline"
            role="combobox"
            aria-expanded={open}
            aria-label={value ? `${text.pick}：${value.displayName}` : text.pick}
            disabled={disabled}
            className="h-9 min-w-0 flex-1 justify-between font-normal"
          >
            {value ? (
              <span className="flex min-w-0 items-center gap-2">
                <span className="truncate">{value.displayName}</span>
                <span className="truncate font-mono text-xs text-muted-foreground">@{value.username}</span>
              </span>
            ) : (
              <span className="truncate text-muted-foreground">{placeholder}</span>
            )}
            <ChevronsUpDown className="size-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        {value && !disabled ? (
          <Button type="button" variant="ghost" size="icon-sm" aria-label={text.clear} onClick={() => onChange(null)}>
            <X />
          </Button>
        ) : null}
      </div>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
        <Command shouldFilter={false} label={text.search}>
          <CommandInput value={query} onValueChange={setQuery} placeholder={placeholder} aria-label={text.search} />
          <CommandList>
            <CommandEmpty>{empty}</CommandEmpty>
            {users.length > 0 ? (
              <CommandGroup>
                {users.map((u) => (
                  <CommandItem key={u.id} value={String(u.id)} onSelect={() => select(u)}>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">
                        {u.displayName}
                        <span className="ml-2 font-mono text-xs text-muted-foreground">@{u.username}</span>
                      </span>
                      <span className="truncate font-mono text-xs text-muted-foreground">{u.email}</span>
                    </span>
                    <Check className={cn("size-4 shrink-0", value?.id === u.id ? "opacity-100" : "opacity-0")} />
                  </CommandItem>
                ))}
              </CommandGroup>
            ) : null}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
