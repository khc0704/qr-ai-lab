// The browser-side copy of what the user uploaded. The server never keeps datasets (a job's input is deleted
// when the job ends), but the File the Dropzone handed us is still here, so result pages can show the sample
// behind a row or a point by reading it locally: a zip entry, a CSV row, a single image. Nothing is sent
// anywhere and nothing is persisted: the store lives in this tab's memory and is gone on reload (the viewer
// then offers to re-attach the same file, verified by size and sha256).
import { useSyncExternalStore } from "react";
import { findZipEntry, listZipEntries, readZipEntry, type ZipEntry } from "@/lib/zip-reader";
import { LineIndex, parseCsvLine } from "@/lib/line-index";

export interface LocalFile {
  file: File;
  name: string;
  size: number;
  attachedAt: number;
}

export interface Fingerprint {
  name?: string;
  size?: number;
  sha256?: string;
}

/** What identifies one sample in a result: the id the trainer reported (zip path, id column value or row index). */
export interface SampleRef {
  id: string;
  /** 0-based row index when the id is not a row index (id column in use). */
  index?: number;
  idColumn?: string;
}

export type Sample =
  | { kind: "image"; blob: Blob; name: string }
  | { kind: "row"; columns: string[]; values: string[]; index: number }
  | { kind: "text"; text: string; name: string }
  | { kind: "missing"; reason: string };

const files = new Map<string, LocalFile>();
const aliases = new Map<string, string>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version += 1;
  for (const l of listeners) l();
}

export const uploadKey = (scope: "project" | "tool", id: number | string) => `upload:${scope}:${id}`;
export const jobKey = (id: number) => `job:${id}`;

function resolve(key: string): string {
  let k = key;
  for (let i = 0; i < 8 && aliases.has(k); i++) k = aliases.get(k)!;
  return k;
}

export function attachLocalFile(key: string, file: File): void {
  files.set(resolve(key), { file, name: file.name, size: file.size, attachedAt: Date.now() });
  emit();
}

/** Make `to` (e.g. job:12) find the file registered under `from` (upload:project:7). */
export function aliasLocalFile(from: string, to: string): void {
  if (from === to) return;
  aliases.set(to, from);
  emit();
}

export function getLocalFile(key: string): LocalFile | undefined {
  return files.get(resolve(key));
}

export function releaseLocalFile(key: string): void {
  files.delete(resolve(key));
  emit();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

/** Re-renders when the file behind `key` is attached, replaced or released. */
export function useLocalFile(key: string | null | undefined): LocalFile | undefined {
  const v = useSyncExternalStore(
    subscribe,
    () => version,
    () => 0,
  );
  void v;
  return key ? getLocalFile(key) : undefined;
}

// --- verification -------------------------------------------------------------------------------------

export const SHA256_MAX_BYTES = 256 * 1024 * 1024;

export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Does this file look like the one the job was created from? Size always, sha256 when known and affordable. */
export async function matchesFingerprint(file: File, fp: Fingerprint): Promise<{ ok: boolean; reason?: string }> {
  if (fp.size !== undefined && fp.size !== file.size)
    return { ok: false, reason: `大小不符：任務的檔案是 ${fp.size} bytes，這個檔案是 ${file.size} bytes` };
  if (fp.sha256 && file.size <= SHA256_MAX_BYTES) {
    const h = await sha256Hex(file);
    if (h !== fp.sha256) return { ok: false, reason: "內容不符（sha256 不同）" };
  }
  return { ok: true };
}

// --- readers --------------------------------------------------------------------------------------------

const IMAGE_EXT = /\.(png|jpe?g|bmp|tiff?|webp|gif)$/i;
const idColumnCache = new WeakMap<File, LineIndex>();
const zipCache = new WeakMap<File, Promise<ZipEntry[]>>();

function ext(name: string): string {
  const m = /\.([a-z0-9]+)$/i.exec(name);
  return m ? m[1].toLowerCase() : "";
}

function lineIndex(file: File, quoted: boolean): LineIndex {
  let idx = idColumnCache.get(file);
  if (!idx) {
    idx = new LineIndex(file, quoted);
    idColumnCache.set(file, idx);
  }
  return idx;
}

/** Read the sample `ref` out of the local file. Never throws: problems come back as `missing`. */
export async function readSample(local: LocalFile, ref: SampleRef): Promise<Sample> {
  const { file } = local;
  try {
    const e = ext(file.name);
    if (e === "zip") {
      let entries = zipCache.get(file);
      if (!entries) {
        entries = listZipEntries(file);
        zipCache.set(file, entries);
      }
      const entry = findZipEntry(await entries, ref.id);
      if (!entry) return { kind: "missing", reason: `zip 裡找不到 ${ref.id}` };
      const blob = await readZipEntry(file, entry);
      if (IMAGE_EXT.test(entry.name)) return { kind: "image", blob, name: entry.name };
      if (entry.size <= 512 * 1024) return { kind: "text", text: await blob.text(), name: entry.name };
      return { kind: "missing", reason: `${entry.name} 不是影像，也太大無法顯示` };
    }
    if (IMAGE_EXT.test(file.name)) return { kind: "image", blob: file, name: file.name };
    if (e === "csv") return readCsvRow(file, ref);
    if (e === "jsonl") {
      const idx = lineIndex(file, false);
      const n = rowIndex(ref);
      if (n === null) return { kind: "missing", reason: "沒有列索引可查" };
      const raw = await idx.raw(n);
      return raw === null
        ? { kind: "missing", reason: `第 ${n + 1} 列不存在` }
        : { kind: "text", text: raw, name: `${file.name}#${n}` };
    }
    return { kind: "missing", reason: `無法在瀏覽器裡讀取 .${e} 檔` };
  } catch (err) {
    return { kind: "missing", reason: err instanceof Error ? err.message : String(err) };
  }
}

function rowIndex(ref: SampleRef): number | null {
  if (ref.index !== undefined && Number.isInteger(ref.index) && ref.index >= 0) return ref.index;
  const n = Number(ref.id);
  return Number.isInteger(n) && n >= 0 ? n : null;
}

async function readCsvRow(file: File, ref: SampleRef): Promise<Sample> {
  const idx = lineIndex(file, true);
  const header = await idx.raw(0);
  if (header === null) return { kind: "missing", reason: "CSV 是空的" };
  const columns = parseCsvLine(header);
  const n = rowIndex(ref);
  const col = ref.idColumn ? columns.indexOf(ref.idColumn) : -1;
  if (n === null) {
    // no row index: look the id up in the id column, or in any column when none is known (ids are usually
    // the first column, and a scan over the file is cheap next to the job that produced the result)
    const match = col >= 0 ? (f: string[]) => f[col] === ref.id : (f: string[]) => f.includes(ref.id);
    const hit = await idx.find((raw, k) => k > 0 && match(parseCsvLine(raw)));
    if (!hit) return { kind: "missing", reason: `找不到 ${ref.idColumn ? `${ref.idColumn} = ` : ""}${ref.id} 的列` };
    return { kind: "row", columns, values: parseCsvLine(hit.raw), index: hit.n - 1 };
  }
  const raw = await idx.raw(n + 1);
  if (raw === null) return { kind: "missing", reason: `第 ${n + 1} 列不存在` };
  return { kind: "row", columns, values: parseCsvLine(raw), index: n };
}
