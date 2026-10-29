/** Internal Pipeline alert inbox. Neither a Facebook nor external-delivery API. */
export type AlertSeverity = "warning" | "critical";
export type AlertState = "open" | "resolved";
export type AlertFilter = AlertState | "all";

export interface OperationalAlert {
  id: string;
  code: string;
  title: string;
  severity: AlertSeverity;
  state: AlertState;
  version: number;
  first_seen_at: string;
  last_seen_at: string;
  resolved_at: string | null;
  acknowledged_at: string | null;
  snoozed_until: string | null;
  is_snoozed: boolean;
  seen_count: number;
  requires_attention: boolean;
}

export interface AlertInbox {
  pipeline_id: string;
  summary: {
    open: number;
    critical_open: number;
    unacknowledged_open: number;
    resolved: number;
    requires_attention: number;
  };
  items: OperationalAlert[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  };
  last_scan_at: string | null;
  scan_stale: boolean;
  read_only_get: true;
  notifications_internal_only: true;
  posting_or_auto_resolution_enabled: false;
}

function root(pipelineId: string): string {
  return `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/operational-alerts/`;
}

function errorText(raw: unknown, status: number): string {
  if (raw && typeof raw === "object") {
    const value = raw as { message?: unknown; detail?: unknown };
    if (typeof value.message === "string") return value.message;
    if (typeof value.detail === "string") return value.detail;
  }
  return `Yêu cầu cảnh báo thất bại (HTTP ${status}).`;
}

export async function fetchOperationalAlerts(
  pipelineId: string, state: AlertFilter, page: number, signal?: AbortSignal,
): Promise<AlertInbox> {
  const q = new URLSearchParams({ state, page: String(page), page_size: "20" });
  const response = await fetch(`${root(pipelineId)}?${q}`, {
    method: "GET", credentials: "same-origin", cache: "no-store", signal,
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok || !body || typeof body !== "object" ||
      (body as { success?: unknown }).success !== true) {
    throw new Error(errorText(body, response.status));
  }
  const data = (body as { data?: AlertInbox }).data;
  if (!data || data.pipeline_id !== pipelineId || !Array.isArray(data.items) ||
      !data.summary || !data.pagination ||
      data.read_only_get !== true ||
      data.notifications_internal_only !== true ||
      data.posting_or_auto_resolution_enabled !== false ||
      typeof data.scan_stale !== "boolean") {
    throw new Error("Dữ liệu cảnh báo sai Pipeline hoặc không hợp lệ.");
  }
  return data;
}

// Imported from existing authenticated session client; CSRF is required for POST.
import { getCsrfToken } from "@/features/auth/api/auth-client";

export async function mutateOperationalAlert(
  pipelineId: string,
  item: Pick<OperationalAlert, "id" | "version">,
  action: "acknowledge" | "snooze",
): Promise<OperationalAlert> {
  const token = await getCsrfToken();
  const payload = action === "snooze"
    ? { action, expected_version: item.version, snooze_minutes: 60 }
    : { action, expected_version: item.version };
  const response = await fetch(`${root(pipelineId)}${encodeURIComponent(item.id)}/actions/`, {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-CSRFToken": token },
    body: JSON.stringify(payload),
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok || !body || typeof body !== "object" ||
      (body as { success?: unknown }).success !== true) {
    throw new Error(errorText(body, response.status));
  }
  const data = (body as { data?: OperationalAlert }).data;
  if (!data || data.id !== item.id || data.version <= item.version) {
    throw new Error("Không thể xác nhận phiên bản cảnh báo vừa cập nhật.");
  }
  return data;
}

export interface AlertEventHistory {
  pipeline_id: string;
  alert_id: string;
  events: { id: string; kind: string; recorded_at: string }[];
  pagination: { page: number; page_size: number; total: number; total_pages: number; has_next: boolean };
  read_only: true;
}

export async function fetchAlertEvents(
  pipelineId: string, alertId: string, page = 1,
): Promise<AlertEventHistory> {
  const response = await fetch(`${root(pipelineId)}${encodeURIComponent(alertId)}/events/?page=${page}`, {
    method: "GET", credentials: "same-origin", cache: "no-store",
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok || !body || typeof body !== "object" ||
      (body as { success?: unknown }).success !== true) {
    throw new Error(errorText(body, response.status));
  }
  const data = (body as { data?: AlertEventHistory }).data;
  if (!data || data.pipeline_id !== pipelineId || data.alert_id !== alertId ||
      data.read_only !== true || !Array.isArray(data.events)) {
    throw new Error("Dữ liệu lịch sử cảnh báo không hợp lệ.");
  }
  return data;
}
