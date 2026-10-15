import {
  Activity,
  Brain,
  ChartScatter,
  Wand2,
  Database,
  FileText,
  Image as ImageIcon,
  Layers,
  Link as LinkIcon,
  ScanSearch,
  Sparkles,
  Table2,
  Tags,
  TrendingUp,
  TriangleAlert,
  Upload,
  Waves,
  type LucideIcon,
} from "lucide-react";
import {
  dataSourceKindLabel,
  dataTypeLabel,
  inputKindLabel,
  jobKindLabel,
  modelFamilyLabel,
  taskTypeLabel,
} from "@/i18n/zh-TW";
import { cn } from "@/lib/utils";
import type { DataSourceKind, DataType, InputKind, JobKind, ModelFamily, TaskType } from "@/types/domain";

/** DESIGN.md §6 fixed icon mapping. */
export const dataTypeIcon: Record<DataType, LucideIcon> = {
  TABULAR: Table2,
  IMAGE: ImageIcon,
  SEQUENCE: Activity,
  TEXT: FileText,
  SPECTRUM: Waves,
};
export const taskTypeIcon: Record<TaskType, LucideIcon> = {
  classification: Tags,
  regression: TrendingUp,
  detection: ScanSearch,
  segmentation: Layers,
  anomaly_detection: TriangleAlert,
};
export const jobKindIcon: Record<JobKind, LucideIcon> = {
  train: Brain,
  inference: Sparkles,
  preprocess: Wand2,
  analysis: ChartScatter,
};
export const sourceKindIcon: Record<DataSourceKind, LucideIcon> = { minio: Database, url: LinkIcon };
export const inputKindIcon: Record<InputKind, LucideIcon> = { upload: Upload, data_source: Database, inline: FileText };

export function Chip({
  icon: Icon,
  children,
  className,
  mono = true,
}: {
  icon?: LucideIcon;
  children: React.ReactNode;
  className?: string;
  mono?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground uppercase",
        mono && "font-mono tracking-wide",
        className,
      )}
    >
      {Icon ? <Icon className="size-3" /> : null}
      {children}
    </span>
  );
}

export const DataTypeChip = ({ dataType, className }: { dataType: DataType; className?: string }) => (
  <Chip icon={dataTypeIcon[dataType]} className={className}>
    {dataType} · {dataTypeLabel[dataType]}
  </Chip>
);
export const TaskChip = ({ taskType, className }: { taskType: TaskType; className?: string }) => (
  <Chip icon={taskTypeIcon[taskType]} className={className} mono={false}>
    {taskTypeLabel[taskType]}
  </Chip>
);
export const KindChip = ({ kind, className }: { kind: JobKind; className?: string }) => (
  <Chip icon={jobKindIcon[kind]} className={cn(kind === "inference" && "text-signal", className)} mono={false}>
    {jobKindLabel[kind]}
  </Chip>
);
export const SourceKindChip = ({ kind, className }: { kind: DataSourceKind; className?: string }) => (
  <Chip icon={sourceKindIcon[kind]} className={className}>
    {dataSourceKindLabel[kind]}
  </Chip>
);
export const InputKindChip = ({ kind, className }: { kind: InputKind; className?: string }) => (
  <Chip icon={inputKindIcon[kind]} className={className} mono={false}>
    {inputKindLabel[kind]}
  </Chip>
);
export const FamilyText = ({ family, className }: { family?: ModelFamily; className?: string }) =>
  family ? (
    <span className={cn("inline-flex flex-col leading-tight", className)}>
      <span className="text-sm">{modelFamilyLabel[family]}</span>
      <span className="font-mono text-[11px] text-subtle-foreground">{family}</span>
    </span>
  ) : (
    <span className="text-muted-foreground">—</span>
  );
