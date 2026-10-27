export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}
const messages: Record<string, string> = {
  demo_session_required: "请返回演示首页，重新进入体验。",
  demo_session_expired: "本次体验已到期，请返回演示首页重新开始。",
  demo_key_required:
    "请点击顶部的“配置 DeepSeek”，连接你自己的 API Key 后再继续。",
  demo_credentials_rejected:
    "配置未保存。请检查 Key；同一体验只能重新连接原来的 Key 和模型，更换配置请重新开始。",
  demo_capacity_reached: "演示名额暂满，请稍后再试。",
  demo_rate_limited: "操作有些频繁，请稍后再试。",
  demo_busy: "本次体验正在处理请求，请完成后再操作。",
  demo_generation_limit: "本次演示已达到生成次数上限，请开始新的体验。",
  demo_endpoint_disabled: "公网演示不开放服务器目录或本机样本访问。",
  demo_origin_rejected: "访问来源不匹配，请从本站页面操作。",
  demo_record_limit: "本次演示的记录已达到上限，请开始新的体验。",
  demo_workspace_full: "本次演示的存储已达到上限。",
  demo_request_too_large:
    "演示版单次请求不能超过 2 MB，上传文件请控制在 1.5 MB 内。",
  demo_max_six_questions: "演示版每轮最多六题，请调整面试设置。",
  transcript_text_size:
    "请输入有效原文，最多 20 万字符，TXT 文件不超过 800 KB。",
  transcript_txt_required: "请选择 TXT 转写文档；DOCX 是复盘导出格式。",
  transcript_encoding: "文档编码无法读取，请另存为 UTF-8 TXT 后上传。",
  transcript_resolve_unknown_roles:
    "请先识别或手动标注所有待识别片段，再确认生成。",
  transcript_orphan_answers:
    "有回答尚未归属问题，请检查说话人、片段顺序和所属场次。",
  transcript_question_count:
    "需至少一个面试问题，每份文档最多 200 个问题及追问。",
  transcript_invalid_boundaries: "拆分范围不连续或超出原文，请刷新确认稿。",
  transcript_invalid_split:
    "请把光标放在片段中间再拆分；已有补充说明时请先保存处理。",
  external_review_revision_conflict:
    "确认稿已更新，请重新打开本场记录后再修改。",
  external_review_not_editable: "本场已进入生成阶段，当前不能修改问答拆分。",
  external_review_export_not_ready: "请等待整场复盘完成后再导出文档。",
  folder_not_found: "这个文件夹不存在或无法访问，请检查本机地址。",
  folder_absolute_path_required:
    "请填写完整的本机文件夹地址，例如 E:\\学习资料。",
  folder_select_subdirectory: "请选择具体文件夹，不要选择整个磁盘。",
  folder_scan_expired: "扫描结果已过期或服务已重启，请重新扫描。",
  folder_file_not_in_scan: "文件不在本次扫描清单中，请重新扫描。",
  profile_not_found: "这个档案不存在，请重新选择。",
  active_role_not_found: "请先补充目标岗位和 JD。",
  chat_model_not_configured: "对话模型尚未配置，请检查后端本地配置。",
  chat_model_request_failed: "模型服务调用失败，已保留会话状态。请稍后重试。",
  chat_model_connection_failed:
    "无法建立模型连接，已保留回答和会话。请检查网络或代理后重试。",
  chat_model_timeout: "模型响应超时，已保留回答和会话。请稍后重试。",
  chat_model_auth_failed:
    "模型服务拒绝了访问，请检查后端 API 密钥及访问权限。会话已保留。",
  chat_model_rate_limited:
    "模型服务触发限流或额度限制，已保留会话。请稍后重试或检查服务额度。",
  chat_model_upstream_unavailable:
    "模型服务暂时不可用，已保留回答和会话。请稍后重试。",
  chat_model_request_rejected:
    "模型服务拒绝了请求，请检查模型名称与请求配置。会话已保留。",
  invalid_model_response:
    "模型返回的内容格式不符合要求，请重试；当前输入已保留。",
  study_citation_not_in_retrieved_evidence:
    "模型引用了本次资料之外的来源，结果未保存，请重试。",
  study_material_section_missing_citation:
    "模型的材料解释缺少引用，结果未保存，请重试。",
  finish_interview_before_study: "请先结束模拟面试，再进入带会话的深度复习。",
  session_busy_or_not_retryable: "会话状态已经变化，请刷新后继续。",
  session_not_awaiting_answer: "当前会话还不能提交，请刷新状态。",
  file_too_large: "文件超过 15 MB，请选用较小的资料。",
};
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError)
    return (
      messages[error.code] ||
      (error.status === 502
        ? "模型输出未能完成，请重试。"
        : error.status === 422
          ? "资料或输入格式不符合要求，请检查后重试。"
          : error.status === 409
            ? "会话状态已变化，请刷新后继续。"
            : "请求失败，请检查服务状态后重试。")
    );
  return "无法连接本地服务，请确认后端已启动，再刷新。";
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-Interview-Demo", "1");
  if (!(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    ...options,
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      typeof body.detail === "string" ? body.detail : "invalid_input",
    );
  }
  return response.json() as Promise<T>;
}
export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
