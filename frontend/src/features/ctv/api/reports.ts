export type ReportDays = 7 | 30 | 90;
export type ReportTab = "overview" | "batches" | "groups" | "accounts";

export interface ReportFilters {
  days: ReportDays;
  scheduleId: string;
  page: number;
  pageSize: number;
  search: string;
}

export type ReportJobState = "queued" | "claimed" | "ready" | "dispatching" |
  "uncertain" | "published" | "failed" | "cancelled";

export type ReportJobs = Record<ReportJobState, number> & {
  total: number;
  published_verified: number;
};

export interface ReportSummary {
  pipeline_id: string;
  window_days: number;
  schedule_id: string | null;
  job_created_at_from: string;
  batch_slot_at_from: string;
  jobs: ReportJobs;
  scheduled_jobs: number;
  manual_jobs: number;
  batches: number;
  skip_events: number;
  skip_reasons: Record<string, number>;
  semantics: {
    queued_is_published: false;
    published_requires_external_post_id: true;
    facebook_dispatch_enabled_by_reports: false;
  };
}

export interface Pagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}
export interface Page<T> { data: T[]; pagination: Pagination; }
export interface BatchSummary {
  id: string;
  schedule_id: string;
  schedule_name: string;
  slot_at: string;
  assigned_count: number;
  skip_events: number;
  created_at: string;
}
export interface BatchJob {
  job_id: string;
  account_id: string;
  account_label: string;
  group_id: string;
  group_name: string;
  group_url: string;
  proxy_id: string;
  exit_ip_snapshot: string;
  scheduled_at: string;
  job_state: ReportJobState;
  job_error_code: string | null;
  external_post_id: string | null;
  published_verified: boolean;
}
export interface BatchSkipped { group_id: string; group_name: string; code: string; }
export interface BatchDetail extends Omit<BatchSummary, "skip_events"> {
  assignments: BatchJob[];
  skipped: BatchSkipped[];
  tick: {
    outcome: "queued" | "replayed" | "error";
    attempt_count: number;
    error_code: string | null;
    updated_at: string;
  } | null;
}
export interface GroupReport {
  group_id: string;
  name: string;
  group_url: string;
  is_enabled: boolean;
  health_state: "active" | "paused" | "unavailable";
  jobs: number;
  queued: number;
  uncertain: number;
  published_verified: number;
  skip_events: number;
}
export interface AccountReport {
  account_id: string;
  label: string;
  connection_status: string;
  proxy_assigned: boolean;
  proxy_health: string | null;
  jobs: number;
  queued: number;
  uncertain: number;
  published_verified: number;
}

const root = (pipelineId: string) =>
  `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/reports/`;

function query(filters: ReportFilters): string {
  const params = new URLSearchParams({
    days: String(filters.days),
    page: String(filters.page),
    page_size: String(filters.pageSize),
  });
  if (filters.scheduleId) params.set("schedule_id", filters.scheduleId);
  if (filters.search.trim()) params.set("search", filters.search.trim());
  return params.toString();
}

async function api<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    method: "GET", credentials: "same-origin", cache: "no-store", signal,
  });
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") throw new Error(`Báo cáo HTTP ${response.status}: phản hồi không hợp lệ.`);
  const body = raw as Record<string, unknown>;
  if (!response.ok || body.success !== true) {
    const message = typeof body.message === "string" ? body.message :
      typeof body.detail === "string" ? body.detail :
      `Không tải được báo cáo (HTTP ${response.status}).`;
    throw new Error(message);
  }
  if (!Object.prototype.hasOwnProperty.call(body, "data")) {
    throw new Error("Phản hồi báo cáo thiếu dữ liệu.");
  }
  return body.data as T;
}

export async function reportSummary(p: string, filters: ReportFilters, signal?: AbortSignal): Promise<ReportSummary> {
  const data = await api<ReportSummary>(`${root(p)}summary/?${query({ ...filters, search: "" })}`, signal);
  if (data.pipeline_id !== p || data.window_days !== filters.days || !data.jobs || !data.semantics) {
    throw new Error("Dữ liệu báo cáo không thuộc Pipeline hoặc khoảng thời gian đã chọn.");
  }
  return data;
}
export async function reportBatches(p: string, filters: ReportFilters, signal?: AbortSignal): Promise<Page<BatchSummary>> {
  return pageResult<BatchSummary>(`${root(p)}batches/?${query({ ...filters, search: "" })}`, signal);
}
export async function reportGroups(p: string, filters: ReportFilters, signal?: AbortSignal): Promise<Page<GroupReport>> {
  return pageResult<GroupReport>(`${root(p)}groups/?${query(filters)}`, signal);
}
export async function reportAccounts(p: string, filters: ReportFilters, signal?: AbortSignal): Promise<Page<AccountReport>> {
  return pageResult<AccountReport>(`${root(p)}accounts/?${query(filters)}`, signal);
}
export async function reportBatchDetail(p: string, batchId: string, signal?: AbortSignal): Promise<BatchDetail> {
  const detail = await api<BatchDetail>(`${root(p)}batches/${encodeURIComponent(batchId)}/`, signal);
  if (!detail || detail.id !== batchId || !Array.isArray(detail.assignments) || !Array.isArray(detail.skipped)) {
    throw new Error("Chi tiết Batch không hợp lệ.");
  }
  return detail;
}
async function pageResult<T>(url: string, signal?: AbortSignal): Promise<Page<T>> {
  const data = await api<Page<T>>(url, signal);
  if (!data || !Array.isArray(data.data) || !data.pagination ||
      typeof data.pagination.total !== "number") {
    throw new Error("Danh sách báo cáo không hợp lệ.");
  }
  return data;
}
