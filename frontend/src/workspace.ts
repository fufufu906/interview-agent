import { computed, reactive } from "vue";
import { errorMessage, post, request } from "./api";
import { publicDemo } from "./runtime";
import { importFolderBatch, type FolderImportProgress } from "./folderImport";
import type {
  Page,
  FolderScan,
  FolderImportResult,
  Profile,
  RoleTarget,
  Session,
  Source,
  SourceDetail,
  Study,
  Summary,
} from "./types";

export function createWorkspace() {
  const s = reactive({
    page: "home" as Page,
    profileId: localStorage.getItem("mianshi.profile") || "",
    profiles: [] as Profile[],
    roles: [] as RoleTarget[],
    sources: [] as Source[],
    history: [] as Summary[],
    studies: [] as Study[],
    session: null as Session | null,
    study: null as Study | null,
    detail: null as SourceDetail | null,
    loading: true,
    busy: "",
    error: "",
    notification: "",
    answer: "",
    focus: "",
    maxPrompts: publicDemo.value ? 3 : 8,
    mode: "quick" as "quick" | "deep",
    studyTopic: "",
    drawer: "" as
      | ""
      | "setup"
      | "role"
      | "upload"
      | "gap"
      | "sources"
      | "detail"
      | "profile",
    sourceQuery: "",
    sourceKind: "",
    importTab: "file",
  });
  let notificationTimer: ReturnType<typeof setTimeout>,
    poll: ReturnType<typeof setInterval>;
  let pendingAnswer: {
    request_id: string;
    answer: string;
    action: "answer" | "skip";
    session_id: string;
  } | null = null;
  const base = () => `/api/profiles/${encodeURIComponent(s.profileId)}`;
  const activeRole = computed(() => s.roles.find((r) => r.active));
  const currentRole = computed(() =>
    s.roles.find((r) => r.role_target_id === s.session?.role_target_id),
  );
  const profile = computed(() =>
    s.profiles.find((p) => p.profile_id === s.profileId),
  );
  const lastQuestion = computed(() =>
    s.session?.turns.filter((t) => t.speaker === "interviewer").at(-1),
  );
  const filteredSources = computed(() =>
    s.sources.filter(
      (item) =>
        (!s.sourceKind || item.kind === s.sourceKind) &&
        `${item.title} ${item.relative_path || ""} ${item.folder_root || ""}`
          .toLowerCase()
          .includes(s.sourceQuery.trim().toLowerCase()),
    ),
  );
  function notify(text: string) {
    clearTimeout(notificationTimer);
    s.notification = text;
    notificationTimer = setTimeout(() => {
      s.notification = "";
    }, 5000);
  }
  function selectPage(page: Page) {
    s.page = page;
    window.location.hash = page;
    window.scrollTo(0, 0);
  }
  function showSession(session: Session) {
    const justCompleted =
      session.status === "completed" && s.session?.status !== "completed";
    s.session = session;
    localStorage.setItem(`mianshi.session.${s.profileId}`, session.session_id);
    if (justCompleted && s.page === "interview") window.scrollTo(0, 0);
  }
  async function reloadData() {
    if (!s.profileId) return;
    const [sources, roles, history, studies] = await Promise.all([
      request<{ items: Source[] }>(`${base()}/sources`),
      request<RoleTarget[]>(`${base()}/roles`),
      request<Summary[]>(`${base()}/interviews`),
      request<Study[]>(`${base()}/studies`),
    ]);
    s.sources = sources.items;
    s.roles = roles;
    s.history = history;
    s.studies = studies;
  }
  async function load() {
    s.loading = true;
    s.error = "";
    try {
      s.profiles = await request<Profile[]>("/api/profiles");
      if (!s.profiles.some((p) => p.profile_id === s.profileId))
        s.profileId = s.profiles[0]?.profile_id || "";
      await reloadData();
      const stored = localStorage.getItem(`mianshi.session.${s.profileId}`);
      const latest =
        s.history.find((h) => h.session_id === stored) || s.history[0];
      if (latest)
        s.session = await request<Session>(
          `${base()}/interviews/${latest.session_id}`,
        );
      s.study = s.studies[0] || null;
      localStorage.setItem("mianshi.profile", s.profileId);
    } catch (error) {
      s.error = errorMessage(error);
    } finally {
      s.loading = false;
    }
  }
  async function run(
    label: string,
    action: () => Promise<void>,
  ): Promise<boolean> {
    if (s.busy || s.loading) return false;
    s.busy = label;
    s.error = "";
    try {
      await action();
      return true;
    } catch (error) {
      s.error = errorMessage(error);
      return false;
    } finally {
      s.busy = "";
    }
  }
  async function changeProfile(id: string) {
    if (s.busy || s.answer.trim()) {
      notify("请先提交或清空当前回答，再切换档案。");
      return;
    }
    if (id === s.profileId) return;
    s.session = null;
    s.study = null;
    s.detail = null;
    pendingAnswer = null;
    s.roles = [];
    s.sources = [];
    s.history = [];
    s.studies = [];
    s.focus = "";
    s.studyTopic = "";
    s.sourceQuery = "";
    s.sourceKind = "";
    s.mode = "quick";
    s.maxPrompts = publicDemo.value ? 3 : 8;
    s.profileId = id;
    s.drawer = "";
    selectPage("home");
    await load();
  }
  async function startInterview() {
    if (!activeRole.value) {
      s.drawer = "role";
      return;
    }
    if (s.answer.trim()) {
      notify("请先提交或清空当前回答，再开始新一轮。");
      return;
    }
    s.drawer = "";
    selectPage("interview");
    await run("正在准备第一道问题…", async () => {
      try {
        const result = await post<{ session: Session }>(
          `${base()}/interviews`,
          { mode: "quick", focus: s.focus, max_prompts: s.maxPrompts },
        );
        showSession(result.session);
        pendingAnswer = null;
      } catch (error) {
        // Failed start still creates a durable session; make it visible and retryable.
        await reloadData();
        if (s.history[0])
          showSession(
            await request<Session>(
              `${base()}/interviews/${s.history[0].session_id}`,
            ),
          );
        throw error;
      } finally {
        await reloadData();
      }
    });
  }
  async function refreshSession() {
    await run("正在刷新会话…", async () => {
      if (s.session)
        showSession(
          await request<Session>(
            `${base()}/interviews/${s.session.session_id}`,
          ),
        );
      await reloadData();
    });
  }
  async function answer(action: "answer" | "skip" = "answer") {
    const session = s.session,
      text = action === "skip" ? "" : s.answer.trim();
    if (
      !session ||
      (action === "answer" && !text) ||
      session.status !== "awaiting_answer"
    )
      return;
    if (action === "skip" && s.answer.trim()) {
      notify("请先提交或清空草稿，再跳过本题。");
      return;
    }
    // Retain the same key after an uncertain network response.
    if (
      !pendingAnswer ||
      pendingAnswer.answer !== text ||
      pendingAnswer.action !== action ||
      pendingAnswer.session_id !== session.session_id
    )
      pendingAnswer = {
        request_id: crypto.randomUUID(),
        answer: text,
        action,
        session_id: session.session_id,
      };
    const payload = pendingAnswer;
    const ok = await run("面试官正在处理本题并整理后续内容…", async () => {
      try {
        const result = await post<{ session: Session }>(
          `${base()}/interviews/${session.session_id}/answers`,
          payload,
        );
        showSession(result.session);
      } catch (error) {
        const recovered = await request<Session>(
          `${base()}/interviews/${session.session_id}`,
        ).catch(() => null);
        if (recovered) {
          showSession(recovered);
          if (
            recovered.turns.some(
              (t) =>
                t.speaker === "candidate" &&
                t.ordinal > (session.turns.at(-1)?.ordinal ?? -1),
            )
          ) {
            s.answer = "";
            pendingAnswer = null;
          }
        }
        throw error;
      } finally {
        await reloadData();
      }
    });
    if (ok) {
      s.answer = "";
      pendingAnswer = null;
    }
  }
  async function finish() {
    if (!s.session || s.answer.trim()) {
      notify("请先提交或清空草稿，再结束面试。");
      return;
    }
    const sessionId = s.session.session_id;
    await run("正在生成本轮复盘…", async () => {
      try {
        showSession(
          await post<Session>(`${base()}/interviews/${sessionId}/finish`),
        );
      } catch (error) {
        s.session = await request<Session>(
          `${base()}/interviews/${sessionId}`,
        ).catch(() => s.session);
        throw error;
      } finally {
        await reloadData();
      }
    });
  }
  async function retry() {
    if (!s.session) return;
    await run("正在重试上次生成…", async () => {
      try {
        showSession(
          await post<Session>(
            `${base()}/interviews/${s.session!.session_id}/retry`,
          ),
        );
      } finally {
        await reloadData();
        s.session = await request<Session>(
          `${base()}/interviews/${s.session!.session_id}`,
        );
      }
    });
  }
  async function generateMemoryAnswers() {
    const session = s.session;
    if (!session || session.status !== "completed") return;
    const pid = s.profileId;
    await run("正在准备建议回答…", async () => {
      const updated = await post<Session>(
        `${base()}/interviews/${session.session_id}/memory-answers`,
        {},
      );
      if (s.profileId === pid && s.session?.session_id === session.session_id) {
        showSession(updated);
        notify("已开始生成，完成后逐题显示。已有结果会保留。");
      }
    });
  }
  async function openSession(id: string) {
    if (s.answer.trim()) {
      notify("请先提交或清空草稿，再切换面试。");
      return;
    }
    await run("正在读取面试记录…", async () => {
      showSession(await request<Session>(`${base()}/interviews/${id}`));
      selectPage(s.session?.status === "completed" ? "review" : "interview");
      pendingAnswer = null;
    });
  }
  async function openSource(sourceId: string) {
    await run("正在读取资料…", async () => {
      s.detail = await request<SourceDetail>(`${base()}/sources/${sourceId}`);
      s.drawer = "detail";
    });
  }
  async function saveRole(data: Record<string, unknown>) {
    return run("正在保存岗位信息…", async () => {
      await post(`${base()}/roles`, data);
      await reloadData();
      s.drawer = "";
      notify("目标岗位已保存，之后的新面试会采用这个岗位。");
    });
  }
  async function activateRole(id: string) {
    await run("正在切换目标岗位…", async () => {
      await post(`${base()}/roles/${id}/activate`);
      await reloadData();
      notify("目标岗位已切换；已有会话仍保留原岗位。");
    });
  }
  async function importSource(body: FormData | Record<string, unknown>) {
    return run("正在导入并建立索引…", async () => {
      const source =
        body instanceof FormData
          ? await request<Source>(`${base()}/sources/file`, {
              method: "POST",
              body,
            })
          : await post<Source>(`${base()}/sources/text`, body);
      await reloadData();
      s.drawer = "";
      notify(
        source.embedding_status === "degraded"
          ? "正文已保存；向量服务不可用，当前可使用文字检索。"
          : "资料已保存并完成索引。",
      );
    });
  }
  async function scanFolder(path: string, focus: string) {
    let result: FolderScan | null = null;
    await run("正在扫描文件夹，并请模型推荐相关资料…", async () => {
      result = await post<FolderScan>(`${base()}/sources/folder/scan`, {
        path,
        focus,
      });
    });
    return result as FolderScan | null;
  }
  async function importFolder(
    scanId: string,
    files: { file_id: string; path: string }[],
    kind: string,
    onProgress: (progress: FolderImportProgress) => void,
  ) {
    let result: FolderImportResult | null = null;
    const endpoint = `${base()}/sources/folder/import`;
    await run("正在读取所选文件并建立索引，请保持页面打开…", async () => {
      const batch = await importFolderBatch(
        files,
        (fileId) =>
          post<FolderImportResult>(endpoint, {
            scan_id: scanId,
            file_ids: [fileId],
            kind,
          }),
        onProgress,
      );
      result = batch.result;
      if (batch.error) {
        await reloadData().catch(() => {});
        throw batch.error;
      }
      await reloadData();
    });
    return result as FolderImportResult | null;
  }
  async function reindex() {
    await run("正在重建缺失向量…", async () => {
      const result = await post<{ embedding_status: string }>(
        `${base()}/sources/reindex`,
      );
      await reloadData();
      notify(
        result.embedding_status === "unavailable"
          ? "向量服务仍不可用，文字检索可继续使用。"
          : "向量索引已更新。",
      );
    });
  }
  async function createProfile(id: string, name: string) {
    if (s.profiles.some((p) => p.profile_id === id)) {
      s.error = "档案编号已存在，请使用新编号。";
      return false;
    }
    const ok = await run("正在创建个人档案…", async () => {
      await post("/api/profiles", { profile_id: id, display_name: name });
      s.drawer = "";
    });
    if (ok) {
      await changeProfile(id);
      notify("新档案已创建，请先填写目标岗位并导入简历。");
    }
    return ok;
  }
  async function createStudy(withSession = false) {
    const topic = s.studyTopic.trim();
    if (!topic) return;
    if (!activeRole.value) {
      s.drawer = "role";
      return;
    }
    selectPage("deep");
    await run("正在拆解问题、检索资料并整理解释…", async () => {
      s.study = await post<Study>(`${base()}/studies`, {
        topic,
        session_id: withSession ? s.session?.session_id : undefined,
      });
      await reloadData();
      notify("复习内容已保存。");
    });
  }
  function studyFromReview(topic: string) {
    s.studyTopic = topic;
    selectPage("deep");
    void createStudy(true);
  }
  function dispose() {
    clearTimeout(notificationTimer);
    clearInterval(poll);
  }
  function startPolling() {
    poll = setInterval(async () => {
      const waitingForMemory = s.session?.memory_answers?.some(
        (item) => item.status === "queued" || item.status === "generating",
      );
      if (
        s.loading ||
        s.busy ||
        !s.session ||
        (s.session.status !== "generating" && !waitingForMemory)
      )
        return;
      const id = s.session.session_id,
        pid = s.profileId;
      try {
        const session = await request<Session>(`${base()}/interviews/${id}`);
        if (s.profileId === pid && s.session?.session_id === id)
          showSession(session);
      } catch {
        /* Explicit refresh remains available. */
      }
    }, 5000);
  }
  return {
    s,
    activeRole,
    currentRole,
    profile,
    lastQuestion,
    filteredSources,
    notify,
    selectPage,
    load,
    run,
    changeProfile,
    startInterview,
    refreshSession,
    answer,
    finish,
    retry,
    generateMemoryAnswers,
    openSession,
    openSource,
    saveRole,
    activateRole,
    importSource,
    scanFolder,
    importFolder,
    reindex,
    createProfile,
    createStudy,
    studyFromReview,
    startPolling,
    dispose,
  };
}
export type Workspace = ReturnType<typeof createWorkspace>;
