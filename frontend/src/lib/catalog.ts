// Pure helpers over the model catalog (plain module: usable from Server Components and client code alike).
import type { Catalog, DataType, TaskType } from "@/types/domain";

/** data type → tasks at least one model family supports (the backend refuses anything else: TASK_NOT_SUPPORTED). */
export function supportedTasks(catalog: Catalog): Record<DataType, TaskType[]> {
  const out = {} as Record<DataType, TaskType[]>;
  for (const dt of Object.keys(catalog.data_types) as DataType[]) {
    out[dt] = (Object.keys(catalog.tasks) as TaskType[]).filter((t) =>
      Object.values(catalog.families).some((f) => (f.supports[dt] ?? []).includes(t)),
    );
  }
  return out;
}
