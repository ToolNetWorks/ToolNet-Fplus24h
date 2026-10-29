import { getCsrfToken } from "@/features/auth/api/auth-client";

export type ObservationSource = "manual_review" | "sanitized_har";
export type ObservationOutcome =
  | "submitted" | "pending_moderation" | "visible_reported"
  | "rejected_reported" | "inconclusive";

export interface VerificationObservation {
  id: string;
  job_id: string;
  source: ObservationSource;
  outcome: ObservationOutcome;
  note: string;
  evidence_url: string | null;
  actor: string;
  recorded_at: string;
}
export interface JobVerification {
  pipeline_id: string;
  job_id: string;
  job_state: string;
  verified_published: boolean;
  verified_post_id: string | null;
  trusted_receipt_recorded: boolean;
  most_recent_observation: ObservationOutcome | null;
  observations: VerificationObservation[];
  pagination: {
    page: number; page_size: number; total: number; total_pages: number;
    has_next: boolean; has_previous: boolean;
  };
  manual_observations_are_proof: false;
  facebook_readback_configured: boolean;
}
export interface NewObservation {
  idempotency_key: string;
  source: ObservationSource;
  outcome: ObservationOutcome;
  note: string;
  evidence_url: string;
}

const endpoint = (pipelineId: string, jobId: string) =>
  `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/publishing-jobs/${encodeURIComponent(jobId)}/verification/`;

async function request<T>(url: string, payload?: NewObservation, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = {};
  if (payload) {
    headers["Content-Type"] = "application/json";
    headers["X-CSRFToken"] = await getCsrfToken();
  }
  const response = await fetch(url, {
    method: payload ? "POST" : "GET",
    credentials: "same-origin", cache: "no-store", headers,
    body: payload ? JSON.stringify(payload) : undefined, signal,
  });
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") throw new Error(`Phản hồi Verification không hợp lệ (HTTP ${response.status}).`);
  const body = raw as { success?: unknown; data?: T; message?: string; detail?: string };
  if (!response.ok || body.success !== true || !body.data) {
    throw new Error(body.message || body.detail || `Verification HTTP ${response.status}`);
  }
  return body.data;
}

export async function getJobVerification(pipelineId: string, jobId: string, page: number, signal?: AbortSignal) {
  const value = await request<JobVerification>(`${endpoint(pipelineId, jobId)}?page=${page}&page_size=20`, undefined, signal);
  if (value.pipeline_id !== pipelineId || value.job_id !== jobId ||
      !Array.isArray(value.observations) || !value.pagination || value.manual_observations_are_proof !== false) {
    throw new Error("Dữ liệu Verification không đúng Pipeline hoặc Job.");
  }
  return value;
}
export function recordJobObservation(pipelineId: string, jobId: string, data: NewObservation) {
  return request<VerificationObservation>(endpoint(pipelineId, jobId), data);
}
