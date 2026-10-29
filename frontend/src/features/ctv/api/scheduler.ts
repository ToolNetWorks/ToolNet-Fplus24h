import { getCsrfToken } from "@/features/auth/api/auth-client";

export interface PipelineSchedule {
  id: string;
  pipeline_id: string;
  name: string;
  enabled: boolean;
  interval_minutes: number;
  max_groups_per_run: number;
  timezone_name: string;
  start_at: string;
  next_run_at: string;
  caption_template: string;
  require_anonymous: boolean;
  require_nonmember: boolean;
  updated_at: string;
}

export type ScheduleWrite = Pick<PipelineSchedule,
  "name" | "enabled" | "interval_minutes" | "max_groups_per_run" |
  "timezone_name" | "start_at" | "caption_template" |
  "require_anonymous" | "require_nonmember"
>;

export interface ScheduledAssignment {
  group_id: string;
  account_id: string;
  proxy_id: string;
  exit_ip: string;
  scheduled_at: string;
  caption?: string;
  will_pin_proxy?: boolean;
  job_id?: string;
}
export interface SkipReason { group_id: string; code: string; }
export interface SchedulePreview {
  schedule_id: string;
  slot_at: string;
  status: string;
  committed: boolean;
  replayed?: boolean;
  batch_id?: string;
  assigned_count?: number;
  assignments: ScheduledAssignment[];
  skipped: SkipReason[];
  next_run_at?: string;
}
export interface ScheduledBatch {
  id: string;
  slot_at: string;
  assigned_count: number;
  skipped: SkipReason[];
  created_at: string;
}
export type EligibilityState = "unknown" | "verified" | "blocked";
export interface EligibilityRecord {
  account_id: string;
  group_id: string;
  state: EligibilityState;
  can_post_anonymous: boolean;
  can_post_nonmember: boolean;
  verified_at: string | null;
  expires_at: string | null;
  evidence_note: string;
}
export type EligibilityWrite = Pick<EligibilityRecord,
  "account_id" | "group_id" | "state" |
  "can_post_anonymous" | "can_post_nonmember" | "evidence_note"
> & { valid_days: number };
export type HealthState = "active" | "paused" | "unavailable";
export interface GroupHealth {
  group_id: string;
  state: HealthState;
  reason_code: string;
  evidence_note: string;
  review_after: string | null;
}

const root = (id: string) => `/api/v1/pipelines/${encodeURIComponent(id)}/`;
const schedulesPath = (id: string) => `${root(id)}schedules/`;
const schedulePath = (id: string, scheduleId: string) =>
  `${schedulesPath(id)}${encodeURIComponent(scheduleId)}/`;

async function request<T>(
  url: string,
  method: "GET" | "POST" | "PATCH" = "GET",
  data?: object,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-CSRFToken"] = await getCsrfToken();
  }
  const response = await fetch(url, {
    method, credentials: "same-origin", cache: "no-store",
    headers, body: method === "GET" ? undefined : JSON.stringify(data ?? {}), signal,
  });
  const unknown: unknown = await response.json().catch(() => null);
  if (!unknown || typeof unknown !== "object") {
    throw new Error(`Phản hồi không hợp lệ (HTTP ${response.status}).`);
  }
  const value = unknown as Record<string, unknown>;
  if (!response.ok || value.success !== true) {
    const message = typeof value.message === "string" ? value.message :
      typeof value.detail === "string" ? value.detail :
      typeof value.non_field_errors === "string" ? value.non_field_errors :
      Object.entries(value).filter(([key]) => key !== "success")
        .flatMap(([, val]) => Array.isArray(val) ? val.map(String) : typeof val === "string" ? [val] : [])
        .join(" ") || `Yêu cầu thất bại (HTTP ${response.status}).`;
    throw new Error(message);
  }
  if (!Object.prototype.hasOwnProperty.call(value, "data")) {
    throw new Error("Phản hồi thiếu trường data.");
  }
  return value.data as T;
}

export async function listSchedules(pipelineId: string, signal?: AbortSignal): Promise<PipelineSchedule[]> {
  const data = await request<PipelineSchedule[]>(schedulesPath(pipelineId), "GET", undefined, signal);
  if (!Array.isArray(data)) throw new Error("Danh sách lịch đăng không hợp lệ.");
  return data;
}
export const createSchedule = (id: string, value: ScheduleWrite) =>
  request<PipelineSchedule>(schedulesPath(id), "POST", value);
export const updateSchedule = (id: string, scheduleId: string, value: Partial<ScheduleWrite>) =>
  request<PipelineSchedule>(schedulePath(id, scheduleId), "PATCH", value);
export const previewSchedule = (id: string, scheduleId: string) =>
  request<SchedulePreview>(`${schedulePath(id, scheduleId)}preview/`);
export const runSchedule = (id: string, scheduleId: string) =>
  request<SchedulePreview>(`${schedulePath(id, scheduleId)}run/`, "POST", {});
export const listScheduleBatches = (id: string, scheduleId: string) =>
  request<ScheduledBatch[]>(`${schedulePath(id, scheduleId)}batches/`);
export const listEligibilities = (id: string, signal?: AbortSignal) =>
  request<EligibilityRecord[]>(`${root(id)}group-eligibility/`, "GET", undefined, signal);
export const saveEligibility = (id: string, data: EligibilityWrite) =>
  request<{id: string; state: EligibilityState}>(`${root(id)}group-eligibility/`, "POST", data);
export const listGroupHealth = (id: string, signal?: AbortSignal) =>
  request<GroupHealth[]>(`${root(id)}group-health/`, "GET", undefined, signal);
export const saveGroupHealth = (id: string, data: GroupHealth) =>
  request<{id: string; state: HealthState}>(`${root(id)}group-health/`, "POST", data);
