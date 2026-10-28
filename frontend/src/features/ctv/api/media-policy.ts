import { getCsrfToken } from "@/features/auth/api/auth-client";

export type MediaSelectionMode = "in_order" | "random";
export type MediaReusePolicy = "no_repeat" | "cycle";

export interface MediaAlbumSource {
  id: string;
  album_id: string;
  album_name: string;
  album_is_enabled: boolean;
  ready_image_count: number;
  position: number;
  is_enabled: boolean;
}

export interface PipelineMediaPolicy {
  pipeline_id: string;
  version: string | null;
  is_enabled: boolean;
  album_selection: MediaSelectionMode;
  image_selection: MediaSelectionMode;
  reuse_policy: MediaReusePolicy;
  images_per_post: number;
  sources: MediaAlbumSource[];
}

export interface MediaPolicyWrite {
  version: string | null;
  is_enabled: boolean;
  album_selection: MediaSelectionMode;
  image_selection: MediaSelectionMode;
  reuse_policy: MediaReusePolicy;
  images_per_post: number;
  sources: { album_id: string; is_enabled: boolean }[];
}

const endpoint = (pipelineId: string) =>
  `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/media-policy/`;

async function readPolicyResponse(response: Response): Promise<PipelineMediaPolicy> {
  const payload: unknown = await response.json().catch(() => null);
  if (!payload || typeof payload !== "object") {
    throw new Error(`Phản hồi cấu hình không hợp lệ (HTTP ${response.status}).`);
  }

  const body = payload as {
    success?: unknown;
    detail?: unknown;
    message?: unknown;
    data?: Partial<PipelineMediaPolicy>;
  };

  if (!response.ok || body.success !== true) {
    const detail = typeof body.message === "string"
      ? body.message
      : typeof body.detail === "string"
        ? body.detail
        : `Không thể xử lý cấu hình (HTTP ${response.status}).`;
    throw new Error(response.status === 409
      ? `${detail} Dữ liệu chưa lưu được giữ nguyên. Tải lại để lấy phiên bản mới.`
      : detail);
  }

  const data = body.data;
  if (!data || !Array.isArray(data.sources) ||
      (data.version !== null && typeof data.version !== "string") ||
      typeof data.is_enabled !== "boolean" ||
      typeof data.images_per_post !== "number") {
    throw new Error("Dữ liệu cấu hình Album không hợp lệ.");
  }

  return data as PipelineMediaPolicy;
}

export async function getPipelineMediaPolicy(
  pipelineId: string,
  signal?: AbortSignal,
): Promise<PipelineMediaPolicy> {
  const response = await fetch(endpoint(pipelineId), {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  return readPolicyResponse(response);
}

export async function savePipelineMediaPolicy(
  pipelineId: string,
  data: MediaPolicyWrite,
): Promise<PipelineMediaPolicy> {
  const csrf = await getCsrfToken();
  const response = await fetch(endpoint(pipelineId), {
    method: "PUT",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrf,
    },
    body: JSON.stringify(data),
  });
  return readPolicyResponse(response);
}
