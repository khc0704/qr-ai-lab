// Shared between the server-rendered result summary and the client-side preview table (a plain module: a Set
// exported from a "use client" file would reach a Server Component as a client reference, not a Set).

/** Result columns that only exist for the sample viewer (overlay paths, grouping keys), never shown as text. */
export const PREVIEW_HIDDEN_COLUMNS: ReadonlySet<string> = new Set([
  "row_index",
  "attention",
  "map",
  "maps",
  "aspects",
]);
