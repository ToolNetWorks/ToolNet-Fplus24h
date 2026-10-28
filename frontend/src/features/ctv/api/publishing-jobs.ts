import { getCsrfToken } from "@/features/auth/api/auth-client";

export type JobState =
  | "queued" | "claimed" | "ready" | "dispatching"
  | "uncertain" | "published" | "failed" | "cancelled";
export interface PublishingJob {
  id: string;
  pipeline_id: string;
  request_key: string;
  state: JobState;
  caption: string;
  account: { id: string; label: string };
  group: { id: string; name: string; url: string };
  scheduled_at: string;
  next_run_at: string;
  attempt_count: number;
  max_attempts: number;
  media_allocation_id: string | null;
  external_post_id: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  finalized_at: string | null;
}
export interface JobAttempt {
  number: number;
  state: string;
  started_at: string;
  finalized_at: string | null;
  media_allocation_id: string | null;
}
export interface JobList {
  data: PublishingJob[];
  summary: { total: number; queued: number; ready: number; uncertain: number; published: number; failed: number };
  pagination: { page: number; page_size: number; total: number; total_pages: number; has_next: boolean; has_previous: boolean };
}
export interface NewJob {
  account_id: string;
  group_id: string;
  caption: string;
  request_key: string;
  max_attempts: number;
  scheduled_at?: string;
}
const endpoint = (p: string) => `/api/v1/pipelines/${encodeURIComponent(p)}/publishing-jobs/`;
const detail = (p: string, id: string) => `${endpoint(p)}${encodeURIComponent(id)}/`;

async function parse<T>(response: Response): Promise<T> {
  const raw: unknown = await response.json().catch(() => ({}));
  if (!raw || typeof raw !== "object") throw new Error(`HTTP ${response.status}: dữ liệu không hợp lệ.`);
  const object = raw as Record<string, unknown>;
  if (!response.ok || object.success !== true) {
    if (typeof object.message === "string") throw new Error(object.message);
    if (typeof object.detail === "string") throw new Error(object.detail);
    if (object.errors && typeof object.errors === "object") {
      throw new Error(Object.values(object.errors).flatMap((v) => Array.isArray(v) ? v : [v]).map(String).join(" "));
    }
    throw new Error(`Không thể xử lý yêu cầu (HTTP ${response.status}).`);
  }
  return object as T;
}

export async function listPublishingJobs(
  pipelineId: string,
  options: { page: number; pageSize: number; state: string; search: string },
  signal?: AbortSignal,
): Promise<JobList> {
  const params = new URLSearchParams({
    page: String(options.page), page_size: String(options.pageSize),
  });
  if (options.state !== "all") params.set("state", options.state);
  if (options.search.trim()) params.set("search", options.search.trim());
  const response = await fetch(`${endpoint(pipelineId)}?${params}`, {
    credentials: "same-origin", cache: "no-store", signal,
  });
  const raw = await parse<{ success: true } & JobList>(response);
  if (!Array.isArray(raw.data) || !raw.pagination || !raw.summary) {
    throw new Error("Danh sách Job không hợp lệ.");
  }
  return raw;
}

export async function createPublishingJob(pipelineId: string, data: NewJob): Promise<PublishingJob> {
  const csrf = await getCsrfToken();
  const response = await fetch(endpoint(pipelineId), {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
    body: JSON.stringify(data),
  });
  const raw = await parse<{ success: true; data: PublishingJob }>(response);
  return raw.data;
}

export async function cancelPublishingJob(pipelineId: string, jobId: string): Promise<PublishingJob> {
  const csrf = await getCsrfToken();
  const response = await fetch(`${detail(pipelineId, jobId)}cancel/`, {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
    body: "{}",
  });
  const raw = await parse<{ success: true; data: PublishingJob }>(response);
  return raw.data;
}

export async function getPublishingJob(
  pipelineId: string, jobId: string,
): Promise<PublishingJob & { attempts: JobAttempt[] }> {
  const response = await fetch(detail(pipelineId, jobId), {
    credentials: "same-origin", cache: "no-store",
  });
  const raw = await parse<{ success: true; data: PublishingJob & { attempts: JobAttempt[] } }>(response);
  return raw.data;
}
