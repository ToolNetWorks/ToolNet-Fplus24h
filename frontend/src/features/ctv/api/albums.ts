import { getCsrfToken } from "@/features/auth/api/auth-client";
import type { Album, PageResult } from "@/features/albums/api/albums";

type EnabledFilter = "all" | "true" | "false";

export interface CTVAlbumList extends PageResult<Album> {
  summary: {
    total: number;
    enabled: number;
    disabled: number;
  };
}

const root = (pipelineId: string) =>
  `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/albums/`;

export async function listCTVAlbums(
  pipelineId: string,
  opts: { page: number; pageSize: number; search: string; enabled: EnabledFilter },
  signal?: AbortSignal,
): Promise<CTVAlbumList> {
  const params = new URLSearchParams({
    page: String(opts.page),
    page_size: String(opts.pageSize),
  });
  if (opts.search.trim()) params.set("search", opts.search.trim());
  if (opts.enabled !== "all") params.set("enabled", opts.enabled);

  const response = await fetch(`${root(pipelineId)}?${params}`, {
    credentials: "same-origin", cache: "no-store", signal,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success !== true || !Array.isArray(payload.data) ||
      !payload.pagination || !payload.summary) {
    throw new Error(typeof payload.message === "string" ? payload.message :
      typeof payload.detail === "string" ? payload.detail :
      `Không thể tải Album (HTTP ${response.status}).`);
  }
  return payload as CTVAlbumList;
}

export async function bulkUpdateAlbums(
  pipelineId: string,
  ids: string[],
  enabled: boolean,
): Promise<{ selected_count: number; updated_count: number; is_enabled: boolean }> {
  if (ids.length < 1 || ids.length > 50) throw new Error("Chọn từ 1 đến 50 Album.");
  const csrf = await getCsrfToken();
  const response = await fetch(`${root(pipelineId)}bulk-status/`, {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
    body: JSON.stringify({ album_ids: ids, is_enabled: enabled }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success !== true || !payload.data) {
    throw new Error(typeof payload.message === "string" ? payload.message :
      `Không thể cập nhật Album (HTTP ${response.status}).`);
  }
  return payload.data;
}
