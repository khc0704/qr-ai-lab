// 所有 UI 文案集中於此；元件只引用 key，不散落硬編碼。
import type {
  ArtifactKind,
  DataFormat,
  DataScale,
  DataSourceKind,
  DataType,
  InputKind,
  IssueStatus,
  IssueType,
  JobKind,
  JobMode,
  JobStage,
  JobStatus,
  ModelFamily,
  ProjectRole,
  ProjectStatus,
  RequestStatus,
  SystemRole,
  TaskType,
} from "@/types/domain";

export const dataTypeLabel: Record<DataType, string> = {
  TABULAR: "表格",
  IMAGE: "圖片",
  SEQUENCE: "序列",
  TEXT: "文字",
  SPECTRUM: "光譜",
};

export const taskTypeLabel: Record<TaskType, string> = {
  classification: "分類",
  regression: "迴歸",
  detection: "物件偵測",
  segmentation: "分割",
  anomaly_detection: "異常偵測",
};

export const modelFamilyLabel: Record<ModelFamily, string> = {
  "tabular.linear": "線性 / 邏輯迴歸",
  "tabular.svm": "SVM",
  "tabular.random_forest": "隨機森林",
  "tabular.xgboost": "XGBoost",
  "vision.yolo": "YOLO",
  "vision.dino": "DINOv2",
  "sequence.patch_autoencoder": "Patch Autoencoder",
  "text.bert_classifier": "BERT 分類器",
};

export const jobStatusLabel: Record<JobStatus, string> = {
  queued: "排隊中",
  scheduled: "已排程",
  running: "執行中",
  succeeded: "成功",
  failed: "失敗",
  cancelled: "已取消",
};

export const jobKindLabel: Record<JobKind, string> = { train: "訓練", inference: "推論" };
export const jobModeLabel: Record<JobMode, string> = { manual: "手動", auto: "自動 (AutoML)" };

export const jobStageLabel: Record<JobStage, string> = {
  fetching: "抓取資料中",
  preparing: "準備資料中",
  training: "模型訓練中",
  evaluating: "評估中",
  exporting: "匯出產物中",
  predicting: "推論中",
};

export const inputKindLabel: Record<InputKind, string> = {
  upload: "一次性上傳",
  data_source: "資料來源",
  inline: "直接輸入",
};

export const requestStatusLabel: Record<RequestStatus, string> = {
  submitted: "已送出",
  in_review: "審核中",
  approved: "已核准",
  rejected: "已退回",
  withdrawn: "已撤回",
};

export const dataScaleLabel: Record<DataScale, string> = {
  tiny: "極小（< 1k）",
  small: "小（1k–10k）",
  medium: "中（10k–100k）",
  large: "大（> 100k）",
};

export const issueTypeLabel: Record<IssueType, string> = {
  question: "問題",
  bug: "錯誤回報",
  feature: "功能建議",
};

export const issueStatusLabel: Record<IssueStatus, string> = { open: "開放", closed: "已關閉" };
export const projectStatusLabel: Record<ProjectStatus, string> = { active: "進行中", archived: "已封存" };
export const systemRoleLabel: Record<SystemRole, string> = { admin: "管理員", user: "使用者" };

export const projectRoleLabel: Record<ProjectRole, string> = {
  owner: "擁有者",
  maintainer: "維護者",
  member: "成員",
  viewer: "檢視者",
};

export const dataSourceKindLabel: Record<DataSourceKind, string> = { minio: "MinIO", url: "URL" };

export const dataFormatLabel: Record<DataFormat, string> = {
  csv: "CSV",
  parquet: "Parquet",
  image_folder: "圖片資料夾",
  coco: "COCO",
  yolo: "YOLO",
  npy: "NPY",
  jsonl: "JSONL",
  spectrum_csv: "光譜 CSV",
};

export const artifactKindLabel: Record<ArtifactKind, string> = {
  model: "模型",
  weights: "權重",
  preprocessor: "前處理器",
  report: "報告",
  metrics: "指標",
};

export const nav = {
  home: "首頁",
  discussions: "討論區",
  projectRequests: "專案申請",
  projects: "專案",
  admin: "管理",
  adminDashboard: "Dashboard",
  adminRequests: "申請審核",
  adminQueue: "佇列",
  adminUsers: "使用者",
  adminQuotas: "專案配額",
  adminAudit: "稽核紀錄",
} as const;

export const routeLabel: Record<string, string> = {
  discussions: nav.discussions,
  "project-requests": nav.projectRequests,
  projects: nav.projects,
  admin: nav.admin,
  queue: nav.adminQueue,
  requests: nav.adminRequests,
  users: nav.adminUsers,
  quotas: nav.adminQuotas,
  audit: nav.adminAudit,
  "data-sources": "資料來源",
  jobs: "任務",
  models: "模型",
  members: "成員",
  settings: "設定",
  new: "新增",
};

export const common = {
  appName: "QR AI Lab",
  search: "搜尋",
  searchPlaceholder: "搜尋專案、申請、任務…",
  noData: "沒有資料",
  loading: "載入中",
  retry: "重試",
  cancel: "取消",
  confirm: "確認",
  save: "儲存",
  delete: "刪除",
  download: "下載",
  dataNotStoredNotice: "本服務不保存您的資料：上傳的檔案與從資料來源抓取的副本只存在於該任務執行期間，任務結束即刪除。",
} as const;
