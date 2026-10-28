import { getCsrfToken } from "@/features/auth/api/auth-client";
export interface UpdatePipelineInput {
  name: string;
  ctv_username: string;
  ctv_email: string;
}
interface UpdatePipelineResponse {
  success?: boolean;
  message?: string;
  detail?: string;
  data?: {
    id: string;
    name: string;
    ctv: {
      id: number;
      username: string;
      email: string;
    };
  };
  [key: string]: unknown;
}
function getApiError(data: UpdatePipelineResponse): string {
  const messages: string[] = [];
  for (const field of [
    "name",
    "ctv_username",
    "ctv_email",
    "non_field_errors",
  ]) {
    const value = data[field];
    if (Array.isArray(value)) {
      messages.push(...value.map(String));
      continue;
    }
    if (typeof value === "string") {
      messages.push(value);
    }
  }
  if (messages.length) return messages.join(" ");
  if (data.message) return data.message;
  if (data.detail) return data.detail;
  return "Không thể cập nhật thông tin Pipeline.";
}
export async function updatePipeline(
  pipelineId: string,
  input: UpdatePipelineInput,
): Promise<void> {
  if (!pipelineId) {
    throw new Error("Pipeline không hợp lệ.");
  }
  if (
    !input.name.trim() ||
    !input.ctv_username.trim() ||
    !input.ctv_email.trim()
  ) {
    throw new Error("Vui lòng nhập đầy đủ thông tin.");
  }
  const csrfToken = await getCsrfToken();
  const response = await fetch(
    `/api/v1/admin/pipelines/${encodeURIComponent(pipelineId)}/`,
    {
      method: "PATCH",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
        Accept: "application/json",
      },
      body: JSON.stringify({
        name: input.name.trim(),
        ctv_username: input.ctv_username.trim(),
        ctv_email: input.ctv_email.trim(),
      }),
    },
  );
  const data: UpdatePipelineResponse =
    await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) {
    throw new Error(
      "Phiên đăng nhập hết hạn hoặc không đủ quyền.",
    );
  }
  if (!response.ok || data.success !== true) {
    throw new Error(getApiError(data));
  }
  if (data.data?.id !== pipelineId) {
    throw new Error("Máy chủ trả về Pipeline không khớp.");
  }
}
