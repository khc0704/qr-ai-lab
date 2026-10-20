import { deflateRawSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { LineIndex, parseCsvLine } from "@/lib/line-index";
import {
  aliasLocalFile,
  attachLocalFile,
  getLocalFile,
  matchesFingerprint,
  readSample,
  sha256Hex,
} from "@/lib/local-data";
import { findZipEntry, listZipEntries, readZipEntry } from "@/lib/zip-reader";

/** Minimal zip writer (stored or deflated entries) so the reader is tested against real structures. */
function buildZip(entries: { name: string; data: Uint8Array; deflate?: boolean }[]): Uint8Array<ArrayBuffer> {
  const enc = new TextEncoder();
  const parts: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  const u16 = (v: number) => [v & 0xff, (v >> 8) & 0xff];
  const u32 = (v: number) => [v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff, (v >>> 24) & 0xff];
  for (const e of entries) {
    const name = enc.encode(e.name);
    const payload = e.deflate ? new Uint8Array(deflateRawSync(e.data)) : e.data;
    const method = e.deflate ? 8 : 0;
    const local = new Uint8Array([
      ...u32(0x04034b50),
      ...u16(20),
      ...u16(0),
      ...u16(method),
      ...u16(0),
      ...u16(0),
      ...u32(0),
      ...u32(payload.length),
      ...u32(e.data.length),
      ...u16(name.length),
      ...u16(0),
      ...name,
    ]);
    central.push(
      new Uint8Array([
        ...u32(0x02014b50),
        ...u16(20),
        ...u16(20),
        ...u16(0),
        ...u16(method),
        ...u16(0),
        ...u16(0),
        ...u32(0),
        ...u32(payload.length),
        ...u32(e.data.length),
        ...u16(name.length),
        ...u16(0),
        ...u16(0),
        ...u16(0),
        ...u16(0),
        ...u32(0),
        ...u32(offset),
        ...name,
      ]),
    );
    parts.push(local, payload);
    offset += local.length + payload.length;
  }
  const cdSize = central.reduce((n, c) => n + c.length, 0);
  const eocd = new Uint8Array([
    ...u32(0x06054b50),
    ...u16(0),
    ...u16(0),
    ...u16(entries.length),
    ...u16(entries.length),
    ...u32(cdSize),
    ...u32(offset),
    ...u16(0),
  ]);
  const total = offset + cdSize + eocd.length;
  const out = new Uint8Array(total);
  let p = 0;
  for (const part of [...parts, ...central, eocd]) {
    out.set(part, p);
    p += part.length;
  }
  return out;
}

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3, 4]);

describe("zip reader", () => {
  it("lists entries and inflates one on demand", async () => {
    const text = new TextEncoder().encode("hello hello hello hello hello");
    const zip = new File(
      [
        buildZip([
          { name: "a/img.png", data: PNG },
          { name: "b/note.txt", data: text, deflate: true },
        ]),
      ],
      "x.zip",
    );
    const entries = await listZipEntries(zip);
    expect(entries.map((e) => e.name)).toEqual(["a/img.png", "b/note.txt"]);
    expect(entries[1].method).toBe(8);
    const img = await readZipEntry(zip, findZipEntry(entries, "a/img.png")!);
    expect(new Uint8Array(await img.arrayBuffer())).toEqual(PNG);
    const note = await readZipEntry(zip, findZipEntry(entries, "note.txt")!);
    expect(await note.text()).toBe("hello hello hello hello hello");
    expect(findZipEntry(entries, "nope.png")).toBeUndefined();
  });
});

describe("line index", () => {
  it("finds CSV records across quoted newlines and parses fields", async () => {
    const csv = 'id,note,y\n1,"a, b",0.5\n2,"two\nlines",0.7\n3,plain,0.9\n';
    const idx = new LineIndex(new File([csv], "t.csv"), true);
    expect(parseCsvLine(await (await idx.raw(0))!)).toEqual(["id", "note", "y"]);
    expect(parseCsvLine((await idx.raw(2))!)).toEqual(["2", "two\nlines", "0.7"]);
    expect(await idx.raw(4)).toBeNull();
    expect(parseCsvLine('a,"b ""q"" c",,d')).toEqual(["a", 'b "q" c', "", "d"]);
    const hit = await idx.find((raw, n) => n > 0 && parseCsvLine(raw)[0] === "3");
    expect(hit?.n).toBe(3);
  });
});

describe("local data store", () => {
  it("resolves aliases, reads samples and verifies fingerprints", async () => {
    const csv = "lot,x1,x2\nL1,1,2\nL2,3,4\n";
    const file = new File([csv], "wat.csv");
    attachLocalFile("upload:project:7", file);
    aliasLocalFile("upload:project:7", "job:12");
    const local = getLocalFile("job:12")!;
    expect(local.name).toBe("wat.csv");
    expect(await readSample(local, { id: "1" })).toMatchObject({ kind: "row", values: ["L2", "3", "4"], index: 1 });
    expect(await readSample(local, { id: "L1", idColumn: "lot" })).toMatchObject({ kind: "row", index: 0 });
    expect(await readSample(local, { id: "L2" })).toMatchObject({ kind: "row", index: 1 }); // id column unknown: scan
    expect(await readSample(local, { id: "9" })).toMatchObject({ kind: "missing" });
    const zip = new File([buildZip([{ name: "g/0.png", data: PNG }])], "imgs.zip");
    attachLocalFile("job:13", zip);
    expect(await readSample(getLocalFile("job:13")!, { id: "g/0.png" })).toMatchObject({
      kind: "image",
      name: "g/0.png",
    });
    const sha = await sha256Hex(file);
    expect(await matchesFingerprint(file, { size: file.size, sha256: sha })).toEqual({ ok: true });
    expect((await matchesFingerprint(file, { size: file.size + 1 })).ok).toBe(false);
    expect((await matchesFingerprint(file, { sha256: "00" })).ok).toBe(false);
  });
});
