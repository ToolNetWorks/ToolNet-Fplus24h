export interface ReviewJob {
  job_id: string;
  state: string;
  reason_code: string;
  severity: "critical" | "warning";
  error_code: string | null;
  account: { id: string; label: string };
  group: { id: string; name: string };
  scheduled_at: string;
  updated_at: string;
  lease_expires_at: string | null;
  can_auto_retry: false;
}
export interface ReviewAccount {
  account_id: string;
  label: string;
  codes: string[];
}
export interface ReviewGroup {
  group_id: string;
  name: string;
  state: "paused" | "unavailable";
  reason_code: string | null;
  review_after: string | null;
}
export interface ReconciliationData {
  pipeline_id: string;
  summary: {
    total: number;
    queued: number;
    claimed: number;
    ready: number;
    dispatching: number;
    uncertain: number;
    failed: number;
    published_verified: number;
    published_missing_id: number;
    review_required_jobs: number;
    held_accounts: number;
    held_groups: number;
    group_health_alerts: number;
    account_alerts_shown: number;
  };
  jobs: ReviewJob[];
  account_alerts: ReviewAccount[];
  group_alerts: ReviewGroup[];
  pagination: {
    page: number; page_size: number; total: number; total_pages: number;
    has_next: boolean; has_previous: boolean;
  };
  account_alerts_truncated: boolean;
  group_alerts_truncated: boolean;
  facebook_dispatch_enabled: false;
  auto_retry_enabled: false;
}

export async function getPublishingReconciliation(
  pipelineId: string,
  page = 1,
  pageSize = 20,
  signal?: AbortSignal,
): Promise<ReconciliationData> {
  const query = new URLSearchParams({page: String(page), page_size: String(pageSize)});
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/publishing-reconciliation/?${query}`,
    {method: "GET", credentials: "same-origin", cache: "no-store", signal},
  );
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") {
    throw new Error(`Không đọc được kết quả đối soát (HTTP ${response.status}).`);
  }
  const body = raw as { success?: boolean; data?: ReconciliationData; message?: string; detail?: string };
  if (!response.ok || body.success !== true) {
    throw new Error(body.message || body.detail || `Đối soát HTTP ${response.status}`);
  }
  const data = body.data;
  if (!data || data.pipeline_id !== pipelineId || !Array.isArray(data.jobs) ||
      !Array.isArray(data.account_alerts) || !Array.isArray(data.group_alerts) ||
      !data.pagination || typeof data.summary?.uncertain !== "number" ||
      data.facebook_dispatch_enabled !== false || data.auto_retry_enabled !== false) {
    throw new Error("Phản hồi đối soát không hợp lệ hoặc sai Pipeline.");
  }
  return data;
}
