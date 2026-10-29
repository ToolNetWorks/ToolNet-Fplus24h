/** Review SLA is advisory only: does not verify posts or change Job state. */
export type ReviewSLAFilter = "all" | "overdue" | "critical" | "awaiting";
export type ReviewSLANextAction =
  | "assign_owner"
  | "collect_evidence"
  | "document_terminal_evidence"
  | "close_after_review"
  | "await_independent_verification"
  | "request_independent_verification";

export interface ReviewSLAItem {
  case_id: string;
  job_id: string;
  case_status: string;
  job_state: string;
  account: { id: string; label: string };
  group: { id: string; name: string };
  assigned_to: string | null;
  age_minutes: number;
  idle_minutes: number;
  severity: "normal" | "warning" | "critical";
  evidence_count: number;
  external_post_verified: boolean;
  next_action: ReviewSLANextAction;
  updated_at: string;
}

export interface ReviewSLASnapshot {
  pipeline_id: string;
  summary: {
    total: number;
    unassigned: number;
    awaiting_verification: number;
    overdue: number;
    critical: number;
    terminal_not_closed: number;
  };
  items: ReviewSLAItem[];
  pagination: {
    page: number; page_size: number; total: number; total_pages: number;
    has_next: boolean; has_previous: boolean;
  };
  threshold_hours: { open: number; in_review: number; awaiting_verification: number; critical: number };
  read_only: true;
  auto_resolution_enabled: false;
  facebook_verification_enabled: false;
}

export async function getReviewSLA(
  pipelineId: string,
  opts: { page: number; filter: ReviewSLAFilter },
  signal?: AbortSignal,
): Promise<ReviewSLASnapshot> {
  const params = new URLSearchParams({
    page: String(opts.page), page_size: "20", filter_by: opts.filter,
  });
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/review-sla/?${params}`,
    { method: "GET", credentials: "same-origin", cache: "no-store", signal },
  );
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") {
    throw new Error(`Không đọc được SLA (HTTP ${response.status}).`);
  }
  const payload = raw as { success?: unknown; message?: unknown; detail?: unknown; data?: ReviewSLASnapshot };
  if (!response.ok || payload.success !== true) {
    throw new Error(typeof payload.message === "string" ? payload.message :
      typeof payload.detail === "string" ? payload.detail : `SLA HTTP ${response.status}`);
  }
  const data = payload.data;
  if (!data || data.pipeline_id !== pipelineId || !Array.isArray(data.items) || !data.pagination ||
      typeof data.summary?.overdue !== "number" || data.read_only !== true ||
      data.auto_resolution_enabled !== false || data.facebook_verification_enabled !== false) {
    throw new Error("Phản hồi SLA không hợp lệ hoặc sai Pipeline.");
  }
  return data;
}
