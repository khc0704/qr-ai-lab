// 所有 UI 文案集中於此；元件只引用 key，不散落硬編碼。
import type {
  ArtifactKind,
  DataFormat,
  DataScale,
  DataSourceKind,
  DataType,
  InferenceMode,
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
  "tabular.isolation_forest": "Isolation Forest",
  "vision.yolo": "YOLO",
  "vision.dino_fewshot": "DINOv2 few-shot",
  "vision.dino_patchcore": "DINOv2 PatchCore",
  "vision.image_quality": "影像品質基準",
  "sequence.patch_autoencoder": "Patch Autoencoder",
  "spectrum.masked_autoencoder": "光譜 Masked AE",
  "text.bert_classifier": "BERT 分類器",
};

/** Unknown ids (e.g. a family added to the catalog before the UI) fall back to the id itself. */
export const familyLabel = (f?: string | null): string => (f ? (modelFamilyLabel[f as ModelFamily] ?? f) : "—");

export const inferenceModeLabel: Record<InferenceMode, string> = {
  predict: "預測（類別 / 數值）",
  score: "異常分數",
  compare: "機台比對報告",
  embed: "向量（embedding）",
  retrieve: "找最相似 / 最不相似",
  detect: "物件偵測",
  segment: "分割",
  measure: "分割 + 幾何量測",
  extend: "新增類別（免重訓）",
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
  starting: "啟動中",
  fetching: "抓取資料中",
  preparing: "準備資料中",
  training: "模型訓練中",
  evaluating: "評估中",
  exporting: "匯出產物中",
  loading: "載入模型中",
  predicting: "推論中",
  done: "完成",
  failed: "失敗",
  cancelled: "已取消",
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
export const systemRoleLabel: Record<SystemRole, string> = {
  superadmin: "系統管理員",
  admin: "管理員",
  user: "使用者",
};
export const systemRoleHint: Record<SystemRole, string> = {
  superadmin: "所有操作：資源池、專案配額、刪專案、模型庫、使用者角色、GPU 重置",
  admin: "日常營運：審核申請、中斷 / 重啟 / 重排任務、管理討論區；不能改資源或刪專案",
  user: "沒有任何管理操作，只有專案內的角色",
};

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
  tools: "資料前處理",
  admin: "管理",
  adminDashboard: "Dashboard",
  adminRequests: "申請審核",
  adminQueue: "佇列",
  adminUsers: "使用者",
  adminQuotas: "專案配額",
  adminModelZoo: "模型庫",
  adminUsage: "使用率歷史",
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
  usage: nav.adminUsage,
  tools: "工具",
  preprocess: nav.tools,
  "model-zoo": nav.adminModelZoo,
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
