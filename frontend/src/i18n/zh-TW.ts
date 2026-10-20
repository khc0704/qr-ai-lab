// 所有 UI 文案集中於此；元件只引用 key，不散落硬編碼。
import type {
  AnalysisKind,
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
  RetrieveOrder,
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
  "tabular.catboost": "CatBoost",
  "tabular.tabpfn": "TabPFN",
  "tabular.isolation_forest": "Isolation Forest",
  "vision.yolo": "YOLO",
  "vision.dino_fewshot": "DINO few-shot",
  "vision.dino_finetune": "DINO 微調",
  "vision.dino_patchcore": "DINO PatchCore",
  "vision.image_quality": "影像品質基準",
  "sequence.patch_autoencoder": "Patch Autoencoder",
  "spectrum.masked_autoencoder": "光譜 Masked AE",
  "spectrum.pls": "PLS / PLS-DA",
  "text.bert_classifier": "BERT 分類器",
  "text.qwen_embedding": "Qwen3 Embedding",
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

export const augmentOpLabel: Record<string, string> = {
  hflip: "水平翻轉",
  vflip: "垂直翻轉",
  rotate90: "旋轉 90°",
  crop: "隨機裁切",
  brightness: "亮度抖動",
  contrast: "對比抖動",
};

export const retrieveOrderLabel: Record<RetrieveOrder, string> = {
  both: "最相似與最不相似都列",
  similar: "只找最相似",
  dissimilar: "只找最不相似",
};

export const jobStatusLabel: Record<JobStatus, string> = {
  queued: "排隊中",
  scheduled: "已排程",
  running: "執行中",
  succeeded: "成功",
  failed: "失敗",
  cancelled: "已取消",
};

export const jobKindLabel: Record<JobKind, string> = {
  train: "訓練",
  inference: "推論",
  preprocess: "前處理",
  analysis: "分析",
};
export const analysisKindLabel: Record<AnalysisKind, string> = {
  tabular_profile: "表格資料探勘",
  image_quality: "影像品質分析",
};
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
  processing: "處理中",
  done: "完成",
  failed: "失敗",
  cancelled: "已取消",
};

export const inputKindLabel: Record<InputKind, string> = {
  upload: "一次性上傳",
  data_source: "資料來源",
  inline: "直接輸入",
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
export const projectStatusLabel: Record<ProjectStatus, string> = {
  pending: "申請中",
  in_review: "審核中",
  active: "進行中",
  rejected: "已退回",
  completed: "已結束",
  archived: "已封存",
};
export const projectStatusHint: Record<ProjectStatus, string> = {
  pending: "已送出申請，等待管理員審核",
  in_review: "管理員審核中，可在「申請」分頁往返討論",
  active: "已核准，可建立資料來源與任務",
  rejected: "申請被退回，修改後可重新送出",
  completed: "專案已結束：不再接受新任務，產物與 log 保留",
  archived: "已封存：唯讀",
};
export const systemRoleLabel: Record<SystemRole, string> = {
  superadmin: "系統管理員",
  admin: "管理員",
  user: "使用者",
};
export const systemRoleHint: Record<SystemRole, string> = {
  superadmin:
    "所有操作：資源池、專案配額、刪專案、模型庫、使用者角色、GPU 重置。只有一位，由環境變數 SUPERADMIN_USERNAME 指定，不能在這裡指派",
  admin: "日常營運：審核申請、中斷 / 重啟 / 重排任務、管理討論區；不能改資源或刪專案。這裡最多只能指派到這個角色",
  user: "沒有任何管理操作，只有專案內的角色",
};
/** The fixed superadmin row in /admin/users (no role select, no deactivate switch). */
export const superadminFixedLabel = "超級管理員（由 SUPERADMIN_USERNAME 指定）";

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
  projects: "專案管理",
  pendingProjects: "待審申請",
  tools: "資料前處理",
  analyze: "資料分析",
  admin: "管理",
  adminDashboard: "Dashboard",
  adminQueue: "佇列",
  adminJobs: "任務管理",
  adminUsers: "使用者",
  adminModelZoo: "模型庫",
  adminUsage: "使用率歷史",
  adminAudit: "稽核紀錄",
} as const;

export const routeLabel: Record<string, string> = {
  discussions: nav.discussions,
  projects: nav.projects,
  application: "申請",
  admin: nav.admin,
  queue: nav.adminQueue,
  users: nav.adminUsers,
  audit: nav.adminAudit,
  usage: nav.adminUsage,
  tools: "工具",
  preprocess: nav.tools,
  analyze: nav.analyze,
  "model-zoo": nav.adminModelZoo,
  "data-sources": "資料來源",
  jobs: "任務",
  models: "模型",
  infer: "推論",
  members: "成員",
  settings: "設定",
  new: "新增",
};

/** Job lifecycle copy. Jobs are host processes (trainer venv subprocesses), never containers. */
export const jobCopy = {
  cancelRemovedFromQueue: "已從佇列移除",
  cancelRequested: "已送出取消請求，程序將在 10 秒內停止",
  cancelRunningDescription: "執行中的程序會被停止，已產生的指標會保留在 log，但不會產生產物。",
  cancelQueuedDescription: "任務會從佇列移除，可以之後重新建立。",
  forceStopDescription: "程序會在 10 秒寬限後停止，任務標記為「已取消」，理由會寫入 log 與稽核紀錄並顯示給任務建立者。",
  deleteDescription: "任務紀錄、log 與輸出資料夾會一併刪除，無法復原。",
  deleteTrainDescription:
    "任務紀錄、log、輸出資料夾與這次訓練產生的模型 / 報告會一併刪除，無法復原；還有推論任務在使用的模型要先刪除那些推論任務。",
  wizardInputNotice: "一次性上傳的檔案只存在於這個任務執行期間；資料來源則由任務程序直接抓取。",
  dataSourceNotice:
    "本服務不保存資料，只記錄連線資訊；任務執行時由任務程序直接向你的 MinIO / URL 抓取，結束即刪除副本。一次性上傳請在「新建訓練」中進行。",
  dataSourceCredentials: "憑證會加密儲存，只在任務程序內使用，不會顯示給任何人。",
  noLogYet: "尚無 log。任務排程後會在此即時顯示。",
  streaming: "即時串流中…",
  reconnecting: "連線中斷，重新連線中…",
  logTruncated: (n: number) => `畫面只保留最後 ${n} 行，更早的內容請下載完整 log。`,
  /** AutoML runs that exported the best-so-far model before finishing (`result.stopped`). */
  stoppedDeadline: "搜尋因逾時提前結束，已匯出目前最佳模型",
  stoppedCancelled: "取消時已匯出目前最佳模型",
} as const;

export const analysisCopy = {
  insufficient: "樣本不足",
  permutationSkipped: "未計算",
} as const;

export const pagination = {
  previous: "上一頁",
  next: "下一頁",
  summary: (page: number, pages: number, total: number) => `第 ${page} / ${pages} 頁 · 共 ${total} 筆`,
} as const;

export const errorCopy = {
  title: "這個頁面出了點問題",
  description: "資料暫時載入不了。先重試一次；若持續發生，請到討論區回報並附上下面的錯誤代碼。",
  retry: "重試",
  home: "回首頁",
  digest: "錯誤代碼",
  globalTitle: "應用程式發生錯誤",
  globalDescription: "整個頁面無法載入。請重新整理；若持續發生，請聯絡系統管理員。",
  authTitle: "登入頁面發生錯誤",
  authDescription: "請重試；若持續發生，請聯絡系統管理員確認認證設定。",
} as const;

export const uploadCopy = {
  tooLarge: (limit: string, actual: string) => `檔案太大：${actual}，上限 ${limit}`,
  failed: (reason: string) => `上傳失敗：${reason}`,
  rejectedByServer: (status: number) =>
    status === 413 ? "檔案超過伺服器允許的大小" : status === 401 ? "登入已過期，請重新登入" : `HTTP ${status}`,
} as const;

/** Markdown editor / renderer copy (shared by the discussion board and the project application form). */
export const markdownCopy = {
  hint: "支援 Markdown",
  write: "編輯",
  preview: "預覽",
  emptyPreview: "沒有內容可預覽",
  toolbar: "格式工具列",
  bold: "粗體",
  list: "清單",
  code: "程式碼",
  link: "連結",
  boldPlaceholder: "粗體文字",
  codePlaceholder: "程式碼",
  linkText: "連結文字",
  linkUrl: "https://",
  chars: (n: number) => `${n} 字`,
} as const;

export const discussionCopy = {
  fieldTitle: "標題",
  fieldType: "類型",
  fieldBody: "內容",
  fieldProject: "關聯專案（可選）",
  noProject: "不關聯",
  titlePlaceholder: "一句話說明問題",
  bodyPlaceholder: "說明背景、重現步驟、預期與實際結果；可用標題、清單、程式碼區塊與表格整理內容。",
  settings: "發表設定",
  create: "建立問題",
  created: (id: number) => `已建立問題 #${id}`,
  edit: "編輯",
  editComment: "編輯留言",
  edited: "已編輯",
  updated: "已更新問題",
  commentUpdated: "已更新留言",
  noBody: "（沒有內文）",
  resolution: "處理結果",
  composer: "留言",
  composerPlaceholder: "留言…",
  closedNoComposer: "討論已關閉，只有管理員可以留言。",
  send: "送出",
  adminTag: "管理員",
  guidanceTitle: "怎麼寫比較容易得到回覆",
  guidance: {
    question: [
      "說明想達成的目標，以及目前卡在哪一步",
      "寫出資料類型、任務與用到的模型家族",
      "附上任務編號或 log 片段（用程式碼區塊貼上）",
    ],
    bug: [
      "重現步驟一步一步寫，別人才能照做",
      "預期結果與實際結果各寫一段",
      "任務編號、發生時間與錯誤訊息（用程式碼區塊貼上）",
    ],
    feature: ["想解決的問題與使用情境", "目前的替代做法與它的不足", "期望的行為或畫面；有參考資料可附連結"],
  },
} as const;

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
