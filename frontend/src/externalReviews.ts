import { ref, onBeforeUnmount } from "vue";
import { request, post, ApiError, errorMessage } from "./api";
import type { Workspace } from "./workspace";
import type { MemoryAnswer } from "./types";

export interface TranscriptTurn {
  turn_id: string;
  start: number;
  end: number;
  role:
    "interviewer" | "candidate" | "assistant" | "system" | "note" | "unknown";
  session: string;
  topic: string;
  correction: string;
}
export interface ExternalSummary {
  review_id: string;
  title: string;
  status: "draft" | "parsing" | "generating" | "completed" | "error";
  revision: number;
  created_at: string;
}
export interface QuestionResult {
  content: {
    answer_clean: string;
    analysis: string;
    quotes: string[];
    suggestion: string;
    explanation: string;
    citations: string[];
    gaps: string[];
  };
  evidence: MemoryAnswer["evidence"];
  diagnostics: MemoryAnswer["diagnostics"];
}
export interface ExternalRecord extends ExternalSummary {
  raw_text: string;
  turns: TranscriptTurn[];
  role: { title: string; jd_text: string };
  warnings: string[];
  coverage: {
    characters: number;
    covered_characters: number;
    unknown_turns: number;
    orphan_answers: string[];
    question_count: number;
    reviewed_questions: number;
  };
  questions: {
    question_id: string;
    question: string;
    answer: string;
    session: string;
    topic: string;
    parent_question_id: string | null;
    start: number;
    end: number;
    status: string;
    result: QuestionResult | null;
    error: string | null;
  }[];
  jobs: {
    kind: string;
    item_id: string;
    status: string;
    error: string | null;
  }[];
  summary: {
    conclusion: string;
    priorities: string[];
    limitations: string[];
  } | null;
}

export function useExternalReviews(w: Workspace) {
  const ownerProfileId = w.s.profileId;
  const items = ref<ExternalSummary[]>([]);
  const samples = ref<{ sample_id: string; filename: string }[]>([]);
  const record = ref<ExternalRecord | null>(null);
  const turns = ref<TranscriptTurn[]>([]);
  const role = ref({ title: "", jd_text: "" });
  const busy = ref("");
  const error = ref("");
  const dirty = ref(false);
  const base = () => `/api/profiles/${encodeURIComponent(ownerProfileId)}`;
  const url = () => `${base()}/external-reviews/${record.value!.review_id}`;
  const draftKey = () =>
    `mianshi.external.draft.${ownerProfileId}.${record.value?.review_id}`;
  function persist() {
    if (dirty.value && record.value?.status === "draft")
      localStorage.setItem(
        draftKey(),
        JSON.stringify({
          revision: record.value.revision,
          turns: turns.value,
          role: role.value,
        }),
      );
  }
  function apply(value: ExternalRecord) {
    record.value = value;
    turns.value = structuredClone(value.turns);
    role.value = { ...value.role };
    dirty.value = false;
    localStorage.setItem(`mianshi.external.${w.s.profileId}`, value.review_id);
  }
  async function run(label: string, action: () => Promise<void>) {
    if (busy.value) return;
    busy.value = label;
    error.value = "";
    try {
      await action();
    } catch (e) {
      error.value = errorMessage(e);
    } finally {
      busy.value = "";
    }
  }
  async function load() {
    const pid = w.s.profileId;
    if (!pid) return;
    await run("正在读取真实面试…", async () => {
      const [list, saved] = await Promise.all([
        request<ExternalSummary[]>(`${base()}/external-reviews`),
        request<{ sample_id: string; filename: string }[]>(
          `${base()}/external-review-samples`,
        ),
      ]);
      if (pid !== w.s.profileId) return;
      items.value = list;
      samples.value = saved;
      const id = localStorage.getItem(`mianshi.external.${pid}`);
      const selected = list.find((x) => x.review_id === id) || list[0];
      if (selected) {
        const value = await request<ExternalRecord>(
          `${base()}/external-reviews/${selected.review_id}`,
        );
        if (pid !== w.s.profileId) return;
        apply(value);
        try {
          const draft = JSON.parse(localStorage.getItem(draftKey()) || "null");
          if (value.status === "draft" && draft?.revision === value.revision) {
            turns.value = draft.turns;
            role.value = draft.role;
            dirty.value = true;
          }
        } catch {
          /* A malformed local draft must not replace server data. */
        }
      }
    });
  }
  async function open(id: string) {
    if (dirty.value) {
      error.value = "请先保存当前问答拆分，再切换记录。";
      return;
    }
    const pid = w.s.profileId;
    await run("正在读取复盘…", async () => {
      const value = await request<ExternalRecord>(
        `${base()}/external-reviews/${id}`,
      );
      if (pid === w.s.profileId) apply(value);
    });
  }
  async function importRecord(
    kind: "text" | "file" | "sample",
    value: unknown,
  ) {
    if (dirty.value) {
      error.value = "请先保存当前问答拆分，再导入其他记录。";
      return;
    }
    const pid = w.s.profileId;
    await run("正在导入并按原文拆分…", async () => {
      let result: ExternalRecord;
      if (kind === "file") {
        const form = new FormData();
        form.append("file", value as File);
        result = await request<ExternalRecord>(
          `${base()}/external-reviews/upload`,
          { method: "POST", body: form },
        );
      } else if (kind === "sample") {
        result = await post<ExternalRecord>(
          `${base()}/external-review-samples/${encodeURIComponent(value as string)}`,
        );
      } else
        result = await post<ExternalRecord>(
          `${base()}/external-reviews`,
          value,
        );
      if (pid !== w.s.profileId) return;
      apply(result);
      items.value = await request<ExternalSummary[]>(
        `${base()}/external-reviews`,
      );
    });
  }
  function draftBody() {
    return {
      revision: record.value!.revision,
      turns: turns.value,
      role_title: role.value.title,
      jd_text: role.value.jd_text,
    };
  }
  async function save() {
    if (!record.value) return;
    const pid = w.s.profileId,
      rid = record.value.review_id,
      key = draftKey();
    await run("正在保存确认稿…", async () => {
      const value = await post<ExternalRecord>(
        `${base()}/external-reviews/${rid}/draft`,
        draftBody(),
      );
      if (pid === w.s.profileId && rid === record.value?.review_id) {
        apply(value);
        localStorage.removeItem(key);
      }
    });
  }
  async function action(action: "parse" | "confirm" | "retry") {
    if (!record.value) return;
    if (action === "parse" && dirty.value) {
      error.value = "请先保存拆分修改，再进行智能识别。";
      return;
    }
    const pid = w.s.profileId,
      rid = record.value.review_id,
      key = draftKey();
    await run(
      action === "confirm" ? "正在提交完整复盘任务…" : "正在提交任务…",
      async () => {
        const value = await post<ExternalRecord>(
          `${base()}/external-reviews/${rid}/${action}`,
          action === "confirm"
            ? draftBody()
            : { revision: record.value!.revision },
        );
        if (pid === w.s.profileId && rid === record.value?.review_id) {
          apply(value);
          localStorage.removeItem(key);
        }
      },
    );
  }
  async function split(turn: TranscriptTurn, position: number) {
    if (dirty.value) {
      error.value = "请先保存角色和场次修改，再拆分片段。";
      return;
    }
    const pid = w.s.profileId,
      rid = record.value!.review_id;
    await run("正在拆分原文…", async () => {
      const value = await post<ExternalRecord>(
        `${base()}/external-reviews/${rid}/split`,
        {
          revision: record.value!.revision,
          turn_id: turn.turn_id,
          position,
        },
      );
      if (pid === w.s.profileId && rid === record.value?.review_id)
        apply(value);
    });
  }
  async function download(kind: "docx" | "raw") {
    if (!record.value) return;
    const target = url(),
      title = record.value.title;
    await run("正在准备下载…", async () => {
      const response = await fetch(`${target}/${kind}`);
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new ApiError(
          response.status,
          payload.detail || "download_failed",
        );
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download =
        title.replace(/\.txt$/i, "") +
        (kind === "docx" ? "复盘.docx" : "原文.txt");
      a.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    });
  }
  const timer = setInterval(async () => {
    if (
      !record.value ||
      busy.value ||
      !["parsing", "generating"].includes(record.value.status)
    )
      return;
    const pid = w.s.profileId,
      rid = record.value.review_id;
    try {
      const value = await request<ExternalRecord>(url());
      if (pid === w.s.profileId && record.value?.review_id === rid)
        apply(value);
    } catch {
      /* Preserve displayed progress until a later poll. */
    }
  }, 2500);
  function beforeUnload(e: BeforeUnloadEvent) {
    persist();
    if (dirty.value) {
      e.preventDefault();
      e.returnValue = "";
    }
  }
  window.addEventListener("beforeunload", beforeUnload);
  onBeforeUnmount(() => {
    persist();
    clearInterval(timer);
    window.removeEventListener("beforeunload", beforeUnload);
  });
  return {
    items,
    samples,
    record,
    turns,
    role,
    busy,
    error,
    dirty,
    load,
    open,
    importRecord,
    save,
    action,
    split,
    download,
  };
}
