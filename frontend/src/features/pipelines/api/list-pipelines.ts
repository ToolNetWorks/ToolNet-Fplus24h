import type {
  PipelineListParams,
  PipelineListResponse,
} from "../types/list";

export async function listPipelines(
  params: PipelineListParams,
  signal?: AbortSignal,
): Promise<PipelineListResponse> {
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
    `/api/v1/admin/pipelines/?${query.toString()}`,
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

  if (response.status === 401 || response.status === 403) {
    throw new Error(
      "Phiên đăng nhập hết hạn hoặc không đủ quyền.",
    );
  }

  const result: Partial<PipelineListResponse> =
    await response.json().catch(() => ({}));

  if (!response.ok || result.success !== true) {
    throw new Error(
      result.message || "Không thể tải danh sách Pipeline.",
    );
  }

  if (!Array.isArray(result.data) || !result.pagination) {
    throw new Error("Dữ liệu API không hợp lệ.");
  }

  return result as PipelineListResponse;
}
