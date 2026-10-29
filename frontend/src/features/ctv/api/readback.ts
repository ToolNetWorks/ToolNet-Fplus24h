/** Step 9.7.10 is read-only for CTV. Never accept confirmation from browser. */
export type ReadbackOutcome = "pending" | "rejected" | "inconclusive" | "mismatch" | "verified";
export interface ReadbackCheck {
  id: string;
  outcome: ReadbackOutcome;
  error_code: string | null;
  source_id: string;
  checked_at: string;
}
export interface ReadbackStatus {
  pipeline_id: string;
  job_id: string;
  job_state: string;
  trusted_submission_linked: boolean;
  trusted_publication_verified: boolean;
  last_readback: ReadbackCheck | null;
  checks: ReadbackCheck[];
  pagination: { page: number; page_size: number; total: number; total_pages: number; has_next: boolean };
  readback_enabled: boolean;
  no_auto_retry: true;
}

export async function getReadbackStatus(pipelineId: string, jobId: string, signal?: AbortSignal): Promise<ReadbackStatus> {
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/publishing-jobs/${encodeURIComponent(jobId)}/readback/`,
    { method: "GET", credentials: "same-origin", cache: "no-store", signal },
  );
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") throw new Error(`Đọc trạng thái xác minh thất bại: HTTP ${response.status}`);
  const data = raw as { success?: boolean; data?: ReadbackStatus; message?: string; detail?: string };
  if (!response.ok || data.success !== true) {
    throw new Error(data.message || data.detail || `HTTP ${response.status}`);
  }
  if (!data.data || data.data.pipeline_id !== pipelineId || data.data.job_id !== jobId ||
      !Array.isArray(data.data.checks) || data.data.no_auto_retry !== true) {
    throw new Error("Dữ liệu xác minh không hợp lệ hoặc sai Pipeline/Job.");
  }
  return data.data;
}
