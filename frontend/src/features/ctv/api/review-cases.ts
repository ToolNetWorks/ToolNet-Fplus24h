import { getCsrfToken } from "@/features/auth/api/auth-client";

export type ReviewStatus = "open" | "in_review" | "awaiting_verification" | "closed";
export type ReviewAction = "assign_me" | "unassign" | "add_evidence" | "request_verification" | "close";

export interface ReviewEvent {
  id: string;
  kind: string;
  actor: string;
  note: string;
  evidence_url: string | null;
  job_state_snapshot: string;
  created_at: string;
}
export interface ReviewCase {
  id: string;
  pipeline_id: string;
  job_id: string;
  job_state: string;
  job_error_code: string | null;
  has_verified_post_id: boolean;
  held: boolean;
  can_close: boolean;
  account: { id: string; label: string };
  group: { id: string; name: string };
  status: ReviewStatus;
  version: number;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  events?: ReviewEvent[];
  event_count?: number;
  events_truncated?: boolean;
}
export interface ReviewList {
  pipeline_id: string;
  data: ReviewCase[];
  pagination: {
    page: number; page_size: number; total: number; total_pages: number;
    has_next: boolean; has_previous: boolean;
  };
}

const root = (pipeline: string) => `/api/v1/pipelines/${encodeURIComponent(pipeline)}/review-cases/`;
const detail = (pipeline: string, id: string) => `${root(pipeline)}${encodeURIComponent(id)}/`;

async function request<T>(url: string, method: "GET" | "POST" = "GET", value?: object, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = {};
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    headers["X-CSRFToken"] = await getCsrfToken();
  }
  const response = await fetch(url, {
    method, credentials: "same-origin", cache: "no-store", headers,
    body: method === "POST" ? JSON.stringify(value ?? {}) : undefined, signal,
  });
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") throw new Error(`Phản hồi hồ sơ không hợp lệ (HTTP ${response.status}).`);
  const result = raw as { success?: unknown; message?: unknown; detail?: unknown; data?: unknown };
  if (!response.ok || result.success !== true) {
    throw new Error(typeof result.message === "string" ? result.message :
      typeof result.detail === "string" ? result.detail : `Lỗi HTTP ${response.status}`);
  }
  return result.data as T;
}

export async function listReviewCases(pipeline: string, page = 1, status = "all", signal?: AbortSignal) {
  const qs = new URLSearchParams({ page: String(page), page_size: "20" });
  if (status !== "all") qs.set("status", status);
  const data = await request<ReviewList>(`${root(pipeline)}?${qs}`, "GET", undefined, signal);
  if (data.pipeline_id !== pipeline || !Array.isArray(data.data) || !data.pagination) {
    throw new Error("Danh sách hồ sơ không khớp Pipeline.");
  }
  return data;
}
export const getReviewCase = (pipeline: string, id: string) =>
  request<ReviewCase>(detail(pipeline, id));
export const createReviewCase = (pipeline: string, jobId: string) =>
  request<ReviewCase>(root(pipeline), "POST", { job_id: jobId });
export const reviewCaseAction = (pipeline: string, id: string, value: {
  action: ReviewAction; expected_version: number; note?: string; evidence_url?: string;
}) => request<ReviewCase>(`${detail(pipeline, id)}actions/`, "POST", value);
