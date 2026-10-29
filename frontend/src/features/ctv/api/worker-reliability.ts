/** Read-only worker lease diagnostics. No Facebook, retry or worker controls. */
export interface WorkerGuardItem {
  job_id: string;
  state: "claimed" | "ready" | "dispatching";
  attempt_number: number;
  account: { id: string; label: string };
  group: { id: string; name: string };
  lease_expires_at: string | null;
  reason: "LEASE_MISSING" | "LEASE_EXPIRED";
  requires_reconciliation: true;
  can_auto_retry: false;
}
export interface WorkerGuardSnapshot {
  pipeline_id: string;
  checked_at: string;
  summary: {
    queued: number; in_flight: number; expired_or_missing_lease: number;
    uncertain: number; published: number;
    expired_claimed: number; expired_ready: number; expired_dispatching: number;
    held_accounts: number; held_groups: number; recorded_quarantines: number;
  };
  items: WorkerGuardItem[];
  truncated: boolean;
  read_only: true;
  facebook_dispatch_enabled: false;
  auto_retry_enabled: false;
  note: string;
}
const validNumber = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;

export async function getWorkerGuard(pipelineId: string, signal?: AbortSignal): Promise<WorkerGuardSnapshot> {
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/worker-guard/?limit=20`,
    { method: "GET", credentials: "same-origin", cache: "no-store", signal },
  );
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") throw new Error(`Worker API HTTP ${response.status}`);
  const body = raw as { success?: unknown; data?: WorkerGuardSnapshot; message?: string; detail?: string };
  if (!response.ok || body.success !== true) {
    throw new Error(body.message || body.detail || `Worker API HTTP ${response.status}`);
  }
  const value = body.data;
  if (!value || value.pipeline_id !== pipelineId ||
      value.read_only !== true || value.auto_retry_enabled !== false ||
      value.facebook_dispatch_enabled !== false || !Array.isArray(value.items) ||
      typeof value.truncated !== "boolean" ||
      !validNumber(value.summary?.expired_or_missing_lease) ||
      !validNumber(value.summary?.held_accounts) ||
      !validNumber(value.summary?.held_groups) ||
      !value.items.every((item) => item && typeof item.job_id === "string" &&
        ["claimed", "ready", "dispatching"].includes(item.state) &&
        item.can_auto_retry === false && item.requires_reconciliation === true &&
        ["LEASE_MISSING", "LEASE_EXPIRED"].includes(item.reason) &&
        typeof item.account?.label === "string" && typeof item.group?.name === "string")
  ) {
    throw new Error("Phản hồi Worker sai định dạng hoặc không thuộc Pipeline.");
  }
  return value;
}
