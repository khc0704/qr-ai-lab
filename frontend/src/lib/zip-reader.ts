// Random access into a zip the browser already holds (a File from the Dropzone): the central directory is
// read from the tail, then one entry is sliced and inflated with the browser's DecompressionStream. The file is
// never loaded whole, so multi-GB datasets cost one small read per sample. Pure TypeScript, no dependency.

export interface ZipEntry {
  name: string;
  size: number;
  compressedSize: number;
  /** 0 = stored, 8 = deflate (the only methods zip tools produce for datasets). */
  method: number;
  localHeaderOffset: number;
}

const SIG_EOCD = 0x06054b50;
const SIG_EOCD64_LOCATOR = 0x07064b50;
const SIG_EOCD64 = 0x06064b50;
const SIG_CENTRAL = 0x02014b50;
const SIG_LOCAL = 0x04034b50;
const EOCD_MIN = 22;
const MAX_COMMENT = 0xffff;

export async function listZipEntries(file: Blob): Promise<ZipEntry[]> {
  const tailLen = Math.min(file.size, EOCD_MIN + MAX_COMMENT);
  const tail = new DataView(await file.slice(file.size - tailLen).arrayBuffer());
  let eocd = -1;
  for (let i = tail.byteLength - EOCD_MIN; i >= 0; i--) {
    if (tail.getUint32(i, true) === SIG_EOCD) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("不是 zip 檔（找不到目錄結尾）");
  let count = tail.getUint16(eocd + 10, true);
  let cdSize = tail.getUint32(eocd + 12, true);
  let cdOffset = tail.getUint32(eocd + 16, true);
  if (count === 0xffff || cdSize === 0xffffffff || cdOffset === 0xffffffff) {
    // zip64: the locator sits right before the EOCD and points at the zip64 EOCD record
    const loc = eocd - 20;
    if (loc >= 0 && tail.getUint32(loc, true) === SIG_EOCD64_LOCATOR) {
      const z64 = Number(tail.getBigUint64(loc + 8, true));
      const z = new DataView(await file.slice(z64, z64 + 56).arrayBuffer());
      if (z.byteLength >= 56 && z.getUint32(0, true) === SIG_EOCD64) {
        count = Number(z.getBigUint64(32, true));
        cdSize = Number(z.getBigUint64(40, true));
        cdOffset = Number(z.getBigUint64(48, true));
      }
    }
  }
  const cd = new DataView(await file.slice(cdOffset, cdOffset + cdSize).arrayBuffer());
  const decoder = new TextDecoder();
  const entries: ZipEntry[] = [];
  let p = 0;
  for (let i = 0; i < count && p + 46 <= cd.byteLength; i++) {
    if (cd.getUint32(p, true) !== SIG_CENTRAL) break;
    const method = cd.getUint16(p + 10, true);
    let compressedSize = cd.getUint32(p + 20, true);
    let size = cd.getUint32(p + 24, true);
    const nameLen = cd.getUint16(p + 28, true);
    const extraLen = cd.getUint16(p + 30, true);
    const commentLen = cd.getUint16(p + 32, true);
    let localHeaderOffset = cd.getUint32(p + 42, true);
    const name = decoder.decode(new Uint8Array(cd.buffer, cd.byteOffset + p + 46, nameLen));
    if (size === 0xffffffff || compressedSize === 0xffffffff || localHeaderOffset === 0xffffffff) {
      let q = p + 46 + nameLen;
      const end = q + extraLen;
      while (q + 4 <= end) {
        const id = cd.getUint16(q, true);
        const len = cd.getUint16(q + 2, true);
        if (id === 1) {
          let r = q + 4;
          if (size === 0xffffffff) {
            size = Number(cd.getBigUint64(r, true));
            r += 8;
          }
          if (compressedSize === 0xffffffff) {
            compressedSize = Number(cd.getBigUint64(r, true));
            r += 8;
          }
          if (localHeaderOffset === 0xffffffff) localHeaderOffset = Number(cd.getBigUint64(r, true));
          break;
        }
        q += 4 + len;
      }
    }
    if (!name.endsWith("/")) entries.push({ name, size, compressedSize, method, localHeaderOffset });
    p += 46 + nameLen + extraLen + commentLen;
  }
  return entries;
}

export async function readZipEntry(file: Blob, entry: ZipEntry): Promise<Blob> {
  const lh = new DataView(await file.slice(entry.localHeaderOffset, entry.localHeaderOffset + 30).arrayBuffer());
  if (lh.byteLength < 30 || lh.getUint32(0, true) !== SIG_LOCAL) throw new Error("zip 區塊損壞");
  const nameLen = lh.getUint16(26, true);
  const extraLen = lh.getUint16(28, true);
  const start = entry.localHeaderOffset + 30 + nameLen + extraLen;
  const data = file.slice(start, start + entry.compressedSize);
  if (entry.method === 0) return data;
  if (entry.method !== 8) throw new Error(`不支援的壓縮方式（method ${entry.method}）`);
  const inflated = data.stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Response(inflated).blob();
}

/** The entry whose name equals `id`, else the one whose path ends with `/id` (ids are zip-relative paths). */
export function findZipEntry(entries: ZipEntry[], id: string): ZipEntry | undefined {
  const norm = id.replace(/\\/g, "/").replace(/^\.\//, "");
  return entries.find((e) => e.name === norm) ?? entries.find((e) => e.name.endsWith(`/${norm}`));
}
