// Row access into a CSV / JSONL the browser holds: the file is scanned once for record boundaries (byte
// offsets, honouring quoted newlines for CSV), after which any record is one small slice. Pure TypeScript.

const CHUNK = 1024 * 1024;
const QUOTE = 0x22;
const NEWLINE = 0x0a;

export class LineIndex {
  /** Byte offset where each record starts; the first is the header for CSV. */
  private readonly offsets: number[] = [0];
  private scanned = 0;
  private inQuotes = false;
  private done = false;

  constructor(
    private readonly file: Blob,
    /** CSV: a newline inside double quotes does not end the record. JSONL never has raw newlines in values. */
    private readonly quoted: boolean,
  ) {}

  get recordCount(): number {
    // the last offset starts a record only when bytes follow it
    const n = this.offsets.length - (this.offsets[this.offsets.length - 1] >= this.file.size ? 1 : 0);
    return this.done ? n : n;
  }

  /** Scan until at least `n + 1` record starts are known (or the file ends). */
  async ensure(n: number): Promise<void> {
    while (!this.done && this.offsets.length <= n) {
      const end = Math.min(this.file.size, this.scanned + CHUNK);
      const bytes = new Uint8Array(await this.file.slice(this.scanned, end).arrayBuffer());
      for (let i = 0; i < bytes.length; i++) {
        const b = bytes[i];
        if (this.quoted && b === QUOTE) this.inQuotes = !this.inQuotes;
        else if (b === NEWLINE && !this.inQuotes) this.offsets.push(this.scanned + i + 1);
      }
      this.scanned = end;
      if (end >= this.file.size) this.done = true;
    }
  }

  /** Raw text of record `n` (0 = first line of the file), without its line terminator; null past the end. */
  async raw(n: number): Promise<string | null> {
    await this.ensure(n + 1);
    const start = this.offsets[n];
    if (start === undefined || start >= this.file.size) return null;
    const end = this.offsets[n + 1] ?? this.file.size;
    const text = await this.file.slice(start, end).text();
    return text.replace(/\r?\n$/, "");
  }

  /** Scan every record (bounded) and return the first whose `pick` is true. */
  async find(pick: (raw: string, n: number) => boolean, limit = 2_000_000): Promise<{ n: number; raw: string } | null> {
    for (let n = 0; n < limit; n++) {
      const raw = await this.raw(n);
      if (raw === null) return null;
      if (pick(raw, n)) return { n, raw };
    }
    return null;
  }
}

/** One CSV record → fields (RFC 4180: quotes, doubled quotes, commas inside quotes). */
export function parseCsvLine(line: string, delimiter = ","): string[] {
  const out: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quoted) {
      if (c === '"') {
        if (line[i + 1] === '"') {
          field += '"';
          i++;
        } else quoted = false;
      } else field += c;
    } else if (c === '"') quoted = true;
    else if (c === delimiter) {
      out.push(field);
      field = "";
    } else field += c;
  }
  out.push(field);
  return out;
}
