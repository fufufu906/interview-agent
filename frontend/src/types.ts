export type Page = "home" | "interview" | "library" | "review" | "deep";
export interface Profile {
  profile_id: string;
  display_name: string;
  created_at: string;
}
export interface RoleTarget {
  role_target_id: string;
  title: string;
  level: string;
  company: string;
  jd_text: string;
  competencies: string[];
  active: boolean;
}
export type SourceKind =
  | "resume"
  | "job_description"
  | "project_repository"
  | "project_document"
  | "study_note"
  | "confirmed_answer"
  | "external_reference";
export interface Source {
  source_id: string;
  title: string;
  kind: SourceKind;
  content_hash: string;
  chunk_count: number;
  embedding_status: "indexed" | "degraded" | "not_requested";
  created_at: string;
  folder_root?: string | null;
  relative_path?: string | null;
}
export type Locator = Record<string, string | number>;
export interface Chunk {
  chunk_id: string;
  text: string;
  locator: Locator;
}
export interface SourceDetail {
  source_id: string;
  title: string;
  kind: SourceKind;
  content_hash: string;
  origin_uri: string;
  metadata: Record<string, unknown>;
  chunks: Chunk[];
}
export interface Evidence {
  source_id: string;
  chunk_id: string;
  source_title: string;
  locator: Locator;
  excerpt?: string;
  text?: string;
}
export interface Turn {
  turn_id: string;
  ordinal: number;
  speaker: "interviewer" | "candidate";
  kind: string;
  content: string;
  competency: string;
  evidence: Evidence[];
  created_at: string;
}
export interface Review {
  summary: string;
  dimensions: {
    dimension: string;
    rating: string;
    evidence: string;
    advice: string;
  }[];
  strengths: string[];
  improvements: string[];
  knowledge_gaps: string[];
  knowledge_gap_evidence?: { gap: string; quote: string }[];
  evidence_gaps: string[];
  next_practice: string[];
}
export type SessionStatus =
  "generating" | "awaiting_answer" | "completed" | "error";
export interface Summary {
  session_id: string;
  role_title: string;
  focus: string;
  status: SessionStatus;
  prompt_count: number;
  max_prompts: number;
  created_at: string;
  updated_at: string;
}
export interface MemoryAnswer {
  question_turn_id: string;
  status: "queued" | "generating" | "ready" | "error";
  content: {
    answer: string;
    basis: "user_material" | "general_knowledge" | "insufficient_evidence";
    citations: string[];
    evidence_gaps: string[];
  } | null;
  evidence: {
    chunk_id: string;
    source_id: string;
    source_title: string;
    text: string;
    locator: Locator;
  }[];
  diagnostics?: { embedding_status: string } | null;
  error: string | null;
  updated_at: string;
}
export interface Session extends Omit<Summary, "role_title"> {
  role_target_id: string;
  profile_id: string;
  turns: Turn[];
  review: Review | null;
  memory_answers?: MemoryAnswer[];
  error: string | null;
}
export interface Study {
  study_id: string;
  profile_id: string;
  topic: string;
  short_answer: string;
  plan: string[];
  sections: {
    title: string;
    content: string;
    basis: string;
    citations: string[];
  }[];
  evidence_gaps: string[];
  knowledge_gaps: string[];
  follow_up_questions: string[];
  evidence: Evidence[];
  diagnostics: { embedding_status: string };
  created_at: string;
}
export const sourceLabels: Record<SourceKind, string> = {
  resume: "简历",
  job_description: "岗位 JD",
  project_repository: "项目代码",
  project_document: "项目文档",
  study_note: "学习笔记",
  confirmed_answer: "用户补充",
  external_reference: "外部参考",
};
export const statusLabels: Record<SessionStatus, string> = {
  generating: "生成中",
  awaiting_answer: "等待回答",
  completed: "已完成",
  error: "生成失败",
};
export const ratingLabels: Record<string, string> = {
  strong: "较强",
  mixed: "一般",
  needs_work: "需加强",
  not_enough_evidence: "证据不足",
};
export function locatorLabel(l: Locator): string {
  if (l.line_start) return `第 ${l.line_start}–${l.line_end} 行`;
  if (l.page) return `第 ${l.page} 页`;
  return `${l.kind === "paragraph" ? "段落" : "位置"} ${l.index ?? ""}`;
}
export function dateLabel(value: string): string {
  return new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
export interface FolderScan {
  scan_id: string;
  root: string;
  model_status: "recommended" | "unavailable" | "not_needed";
  files: {
    file_id: string;
    path: string;
    bytes: number;
    preview: string;
    recommended: boolean;
    reason: string;
  }[];
  warnings: string[];
  stats: { excluded: number; unreadable: number; limited: boolean };
}
export interface FolderImportResult {
  imported: number;
  failed: number;
  files: {
    file_id: string;
    path: string;
    status: "imported" | "failed";
    deduplicated?: boolean;
    error?: string;
    source?: Source;
  }[];
}
