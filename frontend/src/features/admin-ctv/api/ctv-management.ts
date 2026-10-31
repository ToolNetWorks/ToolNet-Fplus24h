import { getCsrfToken } from "@/features/auth/api/auth-client";

import type {
  CreateCTVInput,
  CTVAuditLogParams,
  CTVAuditLogResponse,
  CTVListParams,
  CTVListResponse,
} from "../types/ctv-management";

const API_BASE = "/api/v1/admin/ctv";

interface ApiErrorPayload {
  success?: boolean;
  message?: string;
  detail?: string;
  errors?: Record<string, string | string[]>;
  new_password?: string[];
  confirm_password?: string[];
  non_field_errors?: string[];
}

export class CTVManagementError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "CTVManagementError";
  }
}

function flattenErrors(payload: ApiErrorPayload): string {
  const messages: string[] = [];

  if (payload.errors) {
    for (const value of Object.values(payload.errors)) {
      messages.push(...(Array.isArray(value) ? value : [value]));
    }
  }

  messages.push(
    ...(payload.new_password ?? []),
    ...(payload.confirm_password ?? []),
    ...(payload.non_field_errors ?? []),
  );

  if (messages.length > 0) {
    return messages.join(" ");
  }

  return (
    payload.message ||
    payload.detail ||
    "Yêu cầu không thành công. Vui lòng thử lại."
  );
}

async function parseResponse<T>(
  response: Response,
): Promise<T> {
  const payload: ApiErrorPayload & T = await response
    .json()
    .catch(() => ({} as ApiErrorPayload & T));

  if (response.status === 401 || response.status === 403) {
    throw new CTVManagementError(
      "Phiên đăng nhập hết hạn hoặc không đủ quyền Super Admin.",
      response.status,
    );
  }

  if (!response.ok) {
    throw new CTVManagementError(
      flattenErrors(payload),
      response.status,
    );
  }

  return payload;
}

export async function listCTVs(
  params: CTVListParams,
  signal?: AbortSignal,
): Promise<CTVListResponse> {
  const query = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.pageSize),
  });

  if (params.search.trim()) {
    query.set("search", params.search.trim());
  }

  if (params.status !== "all") {
    query.set("status", params.status);
  }

  const response = await fetch(
    `${API_BASE}/?${query.toString()}`,
    {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal,
      headers: {
        Accept: "application/json",
      },
    },
  );

  const result = await parseResponse<CTVListResponse>(response);

  if (
    result.success !== true ||
    !Array.isArray(result.data) ||
    !result.pagination
  ) {
    throw new CTVManagementError(
      "Dữ liệu API quản lý CTV không hợp lệ.",
      response.status,
    );
  }

  return result;
}

export async function createCTV(
  input: CreateCTVInput,
): Promise<void> {
  const csrfToken = await getCsrfToken();

  const response = await fetch(`${API_BASE}/`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
      Accept: "application/json",
    },
    body: JSON.stringify(input),
  });

  const result = await parseResponse<{ success?: boolean }>(
    response,
  );

  if (result.success !== true) {
    throw new CTVManagementError(
      "Máy chủ không xác nhận tạo CTV.",
      response.status,
    );
  }
}

export async function updateCTVStatus(
  pipelineId: string,
  newStatus: "active" | "disabled",
): Promise<void> {
  if (!pipelineId) {
    throw new CTVManagementError(
      "Pipeline không hợp lệ.",
      400,
    );
  }

  const csrfToken = await getCsrfToken();

  const response = await fetch(
    `${API_BASE}/${encodeURIComponent(pipelineId)}/status/`,
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
        status: newStatus,
      }),
    },
  );

  const result = await parseResponse<{ success?: boolean }>(
    response,
  );

  if (result.success !== true) {
    throw new CTVManagementError(
      "Máy chủ không xác nhận cập nhật trạng thái.",
      response.status,
    );
  }
}

export async function resetCTVPassword(
  pipelineId: string,
  password: string,
  confirmPassword: string,
): Promise<void> {
  if (!pipelineId) {
    throw new CTVManagementError(
      "Pipeline không hợp lệ.",
      400,
    );
  }

  if (!password || !confirmPassword) {
    throw new CTVManagementError(
      "Vui lòng nhập đầy đủ mật khẩu.",
      400,
    );
  }

  if (password !== confirmPassword) {
    throw new CTVManagementError(
      "Mật khẩu xác nhận không khớp.",
      400,
    );
  }

  const csrfToken = await getCsrfToken();

  const response = await fetch(
    `${API_BASE}/${encodeURIComponent(pipelineId)}/password/`,
    {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
        Accept: "application/json",
      },
      body: JSON.stringify({
        new_password: password,
        confirm_password: confirmPassword,
      }),
    },
  );

  const result = await parseResponse<{ success?: boolean }>(
    response,
  );

  if (result.success !== true) {
    throw new CTVManagementError(
      "Máy chủ không xác nhận đặt lại mật khẩu.",
      response.status,
    );
  }
}

export async function listCTVAuditLog(
  params: CTVAuditLogParams,
  signal?: AbortSignal,
): Promise<CTVAuditLogResponse> {
  const query = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.pageSize),
  });

  const response = await fetch(
    `${API_BASE}/audit-log/?${query.toString()}`,
    {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal,
      headers: {
        Accept: "application/json",
      },
    },
  );

  const result = await parseResponse<CTVAuditLogResponse>(
    response,
  );

  if (
    result.success !== true ||
    !Array.isArray(result.data) ||
    !result.pagination
  ) {
    throw new CTVManagementError(
      "Dữ liệu audit log không hợp lệ.",
      response.status,
    );
  }

  return result;
}
