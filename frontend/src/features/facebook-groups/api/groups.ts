import { getCsrfToken } from "@/features/auth/api/auth-client";
export interface FacebookGroup {
  id: string;
  pipeline_id: string;
  name: string;
  group_url: string;
  group_key: string;
  is_enabled: boolean;
  verification_status: string;
  notes: string;
  created_at: string;
  updated_at: string;
}
interface Pagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}
export interface GroupListResult {
  success: boolean;
  data: FacebookGroup[];
  pagination: Pagination;
  summary?: {
    total: number;
    enabled: number;
    disabled: number;
    verified: number;
    unknown: number;
    unavailable: number;
  };
}
export interface GroupInput {
  name: string;
  group_url: string;
  is_enabled: boolean;
  notes: string;
}
function endpoint(pipelineId: string): string {
  return `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/facebook-groups/`;
}
function getErrorMessage(data: Record<string, unknown>): string {
  const errors = data.errors;
  if (errors && typeof errors === "object") {
    const messages = Object.values(errors)
      .flat()
      .map(String);
    if (messages.length) return messages.join(" ");
  }
  for (const value of Object.values(data)) {
    if (Array.isArray(value) && value.length) {
      return value.map(String).join(" ");
    }
  }
  if (typeof data.detail === "string") return data.detail;
  if (typeof data.message === "string") return data.message;
  return "Không thể thực hiện yêu cầu.";
}
async function parseResponse(
  response: Response,
): Promise<Record<string, unknown>> {
  const data: Record<string, unknown> =
    await response.json().catch(() => ({}));
  if (!response.ok || data.success !== true) {
    throw new Error(getErrorMessage(data));
  }
  return data;
}
export async function listGroups(
  pipelineId: string,
  params: {
    page: number;
    search: string;
    enabled: "all" | "true" | "false";
    pageSize?: number;
    verificationStatus?: "all" | "unknown" | "verified" | "unavailable";
  },
  signal?: AbortSignal,
): Promise<GroupListResult> {
  const query = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.pageSize ?? 10),
  });
  if (params.search.trim()) {
    query.set("search", params.search.trim());
  }
  if (params.enabled !== "all") {
    query.set("enabled", params.enabled);
  }
  if (
    params.verificationStatus &&
    params.verificationStatus !== "all"
  ) {
    query.set("verification_status", params.verificationStatus);
  }
  const response = await fetch(
    `${endpoint(pipelineId)}?${query.toString()}`,
    {
      credentials: "same-origin",
      cache: "no-store",
      signal,
    },
  );
  const data = await parseResponse(response);
  if (!Array.isArray(data.data) || !data.pagination) {
    throw new Error("Danh sách Group không hợp lệ.");
  }
  return data as unknown as GroupListResult;
}
async function sendGroupRequest(
  url: string,
  method: "POST" | "PATCH",
  payload: Partial<GroupInput>,
): Promise<FacebookGroup> {
  const csrfToken = await getCsrfToken();
  const response = await fetch(url, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
    },
    body: JSON.stringify(payload),
  });
  const data = await parseResponse(response);
  if (!data.data || typeof data.data !== "object") {
    throw new Error("Phản hồi Group không hợp lệ.");
  }
  return data.data as unknown as FacebookGroup;
}
export function createGroup(
  pipelineId: string,
  input: GroupInput,
): Promise<FacebookGroup> {
  return sendGroupRequest(
    endpoint(pipelineId),
    "POST",
    input,
  );
}
export function updateGroup(
  pipelineId: string,
  groupId: string,
  changes: Partial<GroupInput>,
): Promise<FacebookGroup> {
  return sendGroupRequest(
    `${endpoint(pipelineId)}${encodeURIComponent(groupId)}/`,
    "PATCH",
    changes,
  );
}

export async function bulkUpdateGroupStatus(
  pipelineId: string,
  groupIds: string[],
  isEnabled: boolean,
): Promise<{
  selected_count: number;
  updated_count: number;
  is_enabled: boolean;
}> {
  if (groupIds.length < 1 || groupIds.length > 50) {
    throw new Error("Chọn từ 1 đến 50 Group.");
  }
  const csrfToken = await getCsrfToken();
  const response = await fetch(
    `${endpoint(pipelineId)}bulk-status/`,
    {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({
        group_ids: groupIds,
        is_enabled: isEnabled,
      }),
    },
  );
  const data = await parseResponse(response);
  if (!data.data || typeof data.data !== "object") {
    throw new Error("Phản hồi cập nhật Group không hợp lệ.");
  }
  return data.data as {
    selected_count: number;
    updated_count: number;
    is_enabled: boolean;
  };
}
