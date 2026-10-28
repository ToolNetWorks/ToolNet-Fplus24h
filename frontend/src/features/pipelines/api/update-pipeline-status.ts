import { getCsrfToken } from "@/features/auth/api/auth-client";

import type { PipelineStatus } from "../types/pipeline";

interface UpdateStatusResponse {
  success?: boolean;
  message?: string;
  data?: {
    id: string;
    status: PipelineStatus;
  };
}

export async function updatePipelineStatus(
  pipelineId: string,
  newStatus: PipelineStatus,
): Promise<void> {
  if (!pipelineId) {
    throw new Error("Pipeline không hợp lệ.");
  }

  if (!["active", "disabled"].includes(newStatus)) {
    throw new Error("Trạng thái không hợp lệ.");
  }

  const csrfToken = await getCsrfToken();

  const response = await fetch(
    `/api/v1/admin/pipelines/${encodeURIComponent(pipelineId)}/status/`,
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

  const result: UpdateStatusResponse =
    await response.json().catch(() => ({}));

  if (response.status === 401 || response.status === 403) {
    throw new Error(
      "Phiên đăng nhập hoặc quyền truy cập không hợp lệ.",
    );
  }

  if (!response.ok || !result.success) {
    throw new Error(
      result.message || "Không thể cập nhật Pipeline.",
    );
  }

  if (
    String(result.data?.id) !== pipelineId ||
    result.data?.status !== newStatus
  ) {
    throw new Error(
      "Máy chủ trả về trạng thái không khớp.",
    );
  }
}
