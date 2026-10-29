import type { JobList } from "./publishing-jobs";

export type TickOutcome = "queued" | "replayed" | "error";

export interface TickRecord {
  outcome: TickOutcome;
  slot_at: string;
  attempt_count: number;
  assigned_count: number;
  skipped_count: number;
  error_code: string | null;
  updated_at: string;
}

export interface BatchRecord {
  id: string;
  slot_at: string;
  assigned_count: number;
}

export interface ScheduleTickRow {
  schedule_id: string;
  name: string;
  enabled: boolean;
  due: boolean;
  next_run_at: string;
  last_tick: TickRecord | null;
  last_batch: BatchRecord | null;
}

export interface PipelineTickStatus {
  pipeline_id: string;
  schedule_count: number;
  active_schedule_count: number;
  due_schedule_count: number;
  schedules: ScheduleTickRow[];
}

interface TickResponse {
  success: boolean;
  data?: PipelineTickStatus;
  message?: string;
  detail?: string;
}

/** CTV-scoped read-only endpoint from Step 9.7.3; no server mutations. */
export async function getSchedulerTickStatus(
  pipelineId: string,
  signal?: AbortSignal,
): Promise<PipelineTickStatus> {
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/scheduler-ticks/status/`,
    { method: "GET", credentials: "same-origin", cache: "no-store", signal },
  );
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") {
    throw new Error(`Không đọc được trạng thái Scheduler (HTTP ${response.status}).`);
  }
  const body = raw as TickResponse;
  if (!response.ok || body.success !== true) {
    throw new Error(body.message || body.detail || `Scheduler HTTP ${response.status}`);
  }
  const data = body.data;
  if (!data || !Array.isArray(data.schedules) ||
      typeof data.schedule_count !== "number" ||
      typeof data.active_schedule_count !== "number" ||
      typeof data.due_schedule_count !== "number") {
    throw new Error("Dữ liệu Scheduler không hợp lệ.");
  }
  if (data.pipeline_id !== pipelineId) {
    throw new Error("Dữ liệu Scheduler không thuộc Pipeline đang xem.");
  }
  return data;
}

export interface DashboardMetrics {
  scheduledTotal: number | null;
  enabled: number | null;
  due: number | null;
  jobsTotal: number | null;
  queued: number | null;
  ready: number | null;
  uncertain: number | null;
  published: number | null;
  failed: number | null;
  latestSkipped: number | null;
  tickErrors: number | null;
  latestTick: ScheduleTickRow | null;
}

/** Accurate only for the data window of the existing Tick Status API (up to 100 schedules). */
export function dashboardMetrics(
  ticks: PipelineTickStatus | null,
  jobs: JobList | null,
): DashboardMetrics {
  const schedules = ticks?.schedules ?? [];
  const withTick = schedules.filter((row) => row.last_tick !== null);
  const latestTick = [...withTick].sort((a, b) =>
    Date.parse(b.last_tick!.updated_at) - Date.parse(a.last_tick!.updated_at))[0] ?? null;
  return {
    scheduledTotal: ticks?.schedule_count ?? null,
    enabled: ticks?.active_schedule_count ?? null,
    due: ticks?.due_schedule_count ?? null,
    jobsTotal: jobs?.summary.total ?? null,
    queued: jobs?.summary.queued ?? null,
    ready: jobs?.summary.ready ?? null,
    uncertain: jobs?.summary.uncertain ?? null,
    published: jobs?.summary.published ?? null,
    failed: jobs?.summary.failed ?? null,
    latestSkipped: ticks ? withTick.reduce((acc, row) => acc + row.last_tick!.skipped_count, 0) : null,
    tickErrors: ticks ? schedules.filter((row) => row.last_tick?.outcome === "error").length : null,
    latestTick,
  };
}

export interface WorkspaceAccountStats {
  facebook_accounts: number;
  connected_accounts: number;
}

/** Refresh existing Workspace counters instead of showing stale page-load counts. */
export async function getWorkspaceAccountStats(
  pipelineId: string, signal?: AbortSignal,
): Promise<WorkspaceAccountStats> {
  const response = await fetch('/api/v1/ctv/workspace/', {
    method: 'GET', credentials: 'same-origin', cache: 'no-store', signal,
  });
  const body: unknown = await response.json().catch(() => null);
  if (!body || typeof body !== 'object') {
    throw new Error(`Không đọc được tài khoản Facebook (HTTP ${response.status}).`);
  }
  const result = body as {
    success?: unknown;
    message?: string;
    data?: { pipeline?: { id?: string }; stats?: WorkspaceAccountStats };
  };
  if (!response.ok || result.success !== true) {
    throw new Error(result.message || `Workspace HTTP ${response.status}`);
  }
  if (result.data?.pipeline?.id !== pipelineId ||
      typeof result.data?.stats?.facebook_accounts !== 'number' ||
      typeof result.data.stats.connected_accounts !== 'number') {
    throw new Error('Số liệu Facebook không thuộc Pipeline hiện tại.');
  }
  return result.data.stats;
}
