/** Read-only Neon operational telemetry; not a systemd or Facebook live check. */
export type OperationsStatus = "healthy" | "attention";

export interface OperationsHealth {
  pipeline_id: string;
  checked_at: string;
  status: OperationsStatus;
  pipeline_status: string;
  database: { connected: boolean; vendor: string };
  jobs_by_state: Record<string, number>;
  schedules: { total: number; enabled: number; due: number; overdue_15m: number };
  tick: { last_at: string | null; last_outcome: string | null; errors_1h: number };
  worker: { expired_claims: number; uncertain_over_48h: number };
  integrity: { status: string; complete: boolean; issues: number };
  alerts: string[];
  query_duration_ms: number;
  note: string;
}

const stateKeys = ["queued", "claimed", "ready", "dispatching", "uncertain", "published", "failed", "cancelled"];

function nonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

export async function getOperationsHealth(
  pipelineId: string,
  signal?: AbortSignal,
): Promise<OperationsHealth> {
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/operations-health/?limit=100`,
    { method: "GET", credentials: "same-origin", cache: "no-store", signal },
  );
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") {
    throw new Error(`Không đọc được kết quả vận hành (HTTP ${response.status}).`);
  }
  const body = raw as {
    success?: unknown; data?: OperationsHealth;
    message?: string; detail?: string;
  };
  if (!response.ok || body.success !== true) {
    throw new Error(body.message || body.detail || `Truy vấn vận hành HTTP ${response.status}`);
  }
  const data = body.data;
  if (!data || data.pipeline_id !== pipelineId || !["healthy", "attention"].includes(data.status) ||
      !Array.isArray(data.alerts) || !data.schedules || !data.tick || !data.worker ||
      !data.database || !data.integrity || !data.jobs_by_state ||
      !nonNegativeInteger(data.schedules.total) ||
      !nonNegativeInteger(data.schedules.enabled) ||
      !nonNegativeInteger(data.schedules.due) ||
      !nonNegativeInteger(data.schedules.overdue_15m) ||
      !nonNegativeInteger(data.tick.errors_1h) ||
      !nonNegativeInteger(data.worker.expired_claims) ||
      !nonNegativeInteger(data.worker.uncertain_over_48h) ||
      !nonNegativeInteger(data.integrity.issues) ||
      typeof data.integrity.complete !== "boolean" ||
      typeof data.database.connected !== "boolean" ||
      typeof data.checked_at !== "string" || Number.isNaN(Date.parse(data.checked_at)) ||
      !Object.keys(data.jobs_by_state).every((k) => stateKeys.includes(k) && nonNegativeInteger(data.jobs_by_state[k])) ||
      data.alerts.some((code) => typeof code !== "string")
  ) {
    throw new Error("Dữ liệu giám sát không hợp lệ hoặc sai Pipeline.");
  }
  return data;
}
