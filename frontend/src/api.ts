export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}
const messages: Record<string, string> = {
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
  chat_model_timeout:
    "模型响应超时，已保留回答和会话。请稍后重试。",
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
  const response = await fetch(path, {
    ...options,
    headers:
      options.body instanceof FormData
        ? options.headers
        : { "Content-Type": "application/json", ...options.headers },
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
