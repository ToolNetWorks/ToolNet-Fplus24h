import { getCsrfToken } from "@/features/auth/api/auth-client";
export type ConnectionStatus =
  | "not_connected"
  | "connected"
  | "expired"
  | "disabled";
export interface FacebookAccount {
  id: string;
  pipeline_id: string;
  label: string;
  profile_url: string;
  connection_status: ConnectionStatus;
  last_verified_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface AccountListResponse {
  success: boolean;
  data: FacebookAccount[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  };
}
interface ApiError {
  detail?: string;
  message?: string;
  [key: string]: unknown;
}
async function readApiResponse(
  response: Response,
): Promise<Record<string, unknown>> {
  const data: ApiError = await response.json()
    .catch(() => ({}));
  if (!response.ok || data.success === false) {
    const fieldErrors = Object.values(data)
      .filter(Array.isArray)
      .flat()
      .map(String);
    throw new Error(
      fieldErrors.join(" ") ||
      data.detail ||
      data.message ||
      `API trả về HTTP ${response.status}`,
    );
  }
  return data;
}
export async function getFacebookAccounts(
  pipelineId: string,
  page = 1,
  search = "",
  signal?: AbortSignal,
): Promise<AccountListResponse> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: "10",
  });
  if (search.trim()) {
    query.set("search", search.trim());
  }
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/facebook-accounts/?${query}`,
    {
      credentials: "same-origin",
      cache: "no-store",
      signal,
    },
  );
  const data = await readApiResponse(response);
  if (
    data.success !== true ||
    !Array.isArray(data.data) ||
    !data.pagination
  ) {
    throw new Error("Danh sách Facebook không hợp lệ.");
  }
  return data as unknown as AccountListResponse;
}
export async function uploadFacebookCookie(
  pipelineId: string,
  input: {
    label: string;
    profileUrl: string;
    file: File;
  },
): Promise<void> {
  if (!input.label.trim()) {
    throw new Error("Vui lòng nhập tên tài khoản.");
  }
  if (!input.file.name.toLowerCase().endsWith(".json")) {
    throw new Error("Chỉ hỗ trợ file JSON.");
  }
  if (input.file.size > 64 * 1024) {
    throw new Error("File vượt quá 64 KB.");
  }
  const csrfToken = await getCsrfToken();
  const body = new FormData();
  body.append("label", input.label.trim());
  body.append("profile_url", input.profileUrl.trim());
  body.append("file", input.file);
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/facebook-accounts/cookie-upload/`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": csrfToken,
      },
      body,
    },
  );
  const data = await readApiResponse(response);
  if (data.success !== true) {
    throw new Error("Không thể lưu tài khoản Facebook.");
  }
}
