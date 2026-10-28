import { getCsrfToken } from "@/features/auth/api/auth-client";

import type {
  CreatePipelineInput,
  PipelineResult,
} from "../types/pipeline";

interface ApiResponse {
  success?: boolean;
  data?: PipelineResult;
  message?: string;
  errors?: Record<string, string | string[]>;
}

export class PipelineApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "PipelineApiError";
  }
}

function getErrorMessage(data: ApiResponse): string {
  if (data.message) return data.message;

  if (!data.errors) {
    return "Không thể tạo Pipeline. Vui lòng thử lại.";
  }

  const messages = Object.values(data.errors).flat();

  return messages.join(" ") ||
    "Dữ liệu Pipeline không hợp lệ.";
}

export async function createPipeline(
  input: CreatePipelineInput,
): Promise<PipelineResult> {
  const csrfToken = await getCsrfToken();

  const response = await fetch("/api/v1/admin/pipelines/", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
    },
    body: JSON.stringify(input),
  });

  const data: ApiResponse = await response.json().catch(
    () => ({}),
  );

  if (!response.ok) {
    throw new PipelineApiError(
      getErrorMessage(data),
      response.status,
    );
  }

  if (!data.success || !data.data?.id) {
    throw new PipelineApiError(
      "Phản hồi máy chủ không hợp lệ.",
      response.status,
    );
  }

  return data.data;
}
