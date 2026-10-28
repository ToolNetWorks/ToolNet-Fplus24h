import { getCsrfToken } from "@/features/auth/api/auth-client";
export interface PipelineDeletePreview {
  pipeline_id: string;
  pipeline_name: string;
  ctv_username: string;
  can_delete: boolean;
  blockers: string[];
}
interface DeleteApiResponse {
  success?: boolean;
  message?: string;
  detail?: string;
  data?: unknown;
  [key: string]: unknown;
}
function getErrorMessage(data: DeleteApiResponse): string {
  if (data.message) return data.message;
  if (data.detail) return data.detail;
  for (const key of [
    "confirm_name",
    "confirm_username",
    "non_field_errors",
  ]) {
    const value = data[key];
    if (Array.isArray(value)) {
      return value.map(String).join(" ");
    }
  }
  return "Thao tác không thành công.";
}
async function parseResponse(
  response: Response,
): Promise<DeleteApiResponse> {
  const data: DeleteApiResponse =
    await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) {
    throw new Error(
      "Phiên đăng nhập hết hạn hoặc không đủ quyền.",
    );
  }
  if (!response.ok || data.success !== true) {
    throw new Error(getErrorMessage(data));
  }
  return data;
}
export async function getPipelineDeletePreview(
  pipelineId: string,
): Promise<PipelineDeletePreview> {
  const response = await fetch(
    `/api/v1/admin/pipelines/${encodeURIComponent(pipelineId)}/`,
    {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        Accept: "application/json",
      },
    },
  );
  const result = await parseResponse(response);
  const data = result.data as PipelineDeletePreview | undefined;
  if (
    !data ||
    data.pipeline_id !== pipelineId ||
    typeof data.pipeline_name !== "string" ||
    typeof data.ctv_username !== "string" ||
    typeof data.can_delete !== "boolean" ||
    !Array.isArray(data.blockers)
  ) {
    throw new Error("Dữ liệu kiểm tra xóa không hợp lệ.");
  }
  return data;
}
export async function deletePipeline(
  pipelineId: string,
  confirmName: string,
  confirmUsername: string,
): Promise<void> {
  if (!pipelineId || !confirmName || !confirmUsername) {
    throw new Error("Thông tin xác nhận không đầy đủ.");
  }
  const csrfToken = await getCsrfToken();
  const response = await fetch(
    `/api/v1/admin/pipelines/${encodeURIComponent(pipelineId)}/`,
    {
      method: "DELETE",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
        Accept: "application/json",
      },
      body: JSON.stringify({
        confirm_name: confirmName,
        confirm_username: confirmUsername,
      }),
    },
  );
  const result = await parseResponse(response);
  const deleted = result.data as
    | { pipeline_id?: string }
    | undefined;
  if (deleted?.pipeline_id !== pipelineId) {
    throw new Error(
      "Máy chủ trả về kết quả xóa không khớp.",
    );
  }
}
