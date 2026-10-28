import { getCsrfToken } from "@/features/auth/api/auth-client";

export type ProxyProtocol = "http" | "https" | "socks5";
export type ProxyHealth = "untested" | "healthy" | "failed";

export interface ProxyAccount {
  id: string;
  label: string;
}

export interface ProxyItem {
  id: string;
  pipeline_id: string;
  protocol: ProxyProtocol;
  host: string;
  port: number;
  is_enabled: boolean;
  health_status: ProxyHealth;
  exit_ip: string | null;
  latency_ms: number | null;
  last_checked_at: string | null;
  notes: string;
  account: ProxyAccount | null;
  has_auth: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProxyInput {
  protocol: ProxyProtocol;
  host: string;
  port: number;
  is_enabled?: boolean;
  notes?: string;
  account_id?: string | null;
  username?: string;
  password?: string;
}

export interface ProxyPagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface ProxyListResult {
  success: true;
  data: ProxyItem[];
  pagination: ProxyPagination;
}

export interface ProxyCheckResult {
  id: string;
  health_status: ProxyHealth;
  exit_ip: string | null;
  latency_ms: number | null;
  last_checked_at: string;
}

const root = (pipelineId: string) =>
  `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/proxies/`;

const detail = (pipelineId: string, proxyId: string) =>
  `${root(pipelineId)}${encodeURIComponent(proxyId)}/`;

function getError(raw: Record<string, unknown>): string {
  if (typeof raw.message === "string") {
    return raw.message;
  }
  if (typeof raw.detail === "string") {
    return raw.detail;
  }
  if (raw.errors && typeof raw.errors === "object") {
    return Object.values(raw.errors)
      .flatMap((value) => (
        Array.isArray(value) ? value : [value]
      ))
      .map(String)
      .join(" ");
  }
  return "Không thể xử lý yêu cầu.";
}

async function api<T>(
  url: string,
  method: "GET" | "POST" | "PATCH" | "DELETE" = "GET",
  payload?: object,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-CSRFToken"] = await getCsrfToken();
  }
  const response = await fetch(url, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers,
    body: method === "GET"
      ? undefined
      : JSON.stringify(payload ?? {}),
    signal,
  });
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") {
    throw new Error(`Phản hồi không hợp lệ: HTTP ${response.status}`);
  }
  const result = raw as Record<string, unknown>;
  if (!response.ok || result.success !== true) {
    throw new Error(getError(result));
  }
  return raw as T;
}

export function listProxies(
  pipelineId: string,
  options: {
    page: number;
    pageSize: number;
    search: string;
    status: string;
    assigned: string;
  },
  signal?: AbortSignal,
): Promise<ProxyListResult> {
  const params = new URLSearchParams({
    page: String(options.page),
    page_size: String(options.pageSize),
  });
  if (options.search.trim()) {
    params.set("search", options.search.trim());
  }
  if (options.status !== "all") {
    params.set("status", options.status);
  }
  if (options.assigned !== "all") {
    params.set("assigned", options.assigned);
  }
  return api<ProxyListResult>(
    `${root(pipelineId)}?${params}`,
    "GET",
    undefined,
    signal,
  );
}

export async function searchFacebookAccounts(
  pipelineId: string,
  search: string,
  signal?: AbortSignal,
): Promise<ProxyAccount[]> {
  const params = new URLSearchParams({
    page: "1",
    page_size: "50",
  });
  if (search.trim()) {
    params.set("search", search.trim());
  }
  const url =
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}` +
    `/facebook-accounts/?${params}`;
  const result = await api<{
    success: true;
    data: ProxyAccount[];
  }>(url, "GET", undefined, signal);
  if (!Array.isArray(result.data)) {
    throw new Error("Danh sách Facebook Account không hợp lệ.");
  }
  return result.data;
}

export function createProxy(
  pipelineId: string,
  payload: ProxyInput,
): Promise<{ success: true; data: ProxyItem }> {
  return api(root(pipelineId), "POST", payload);
}

export function updateProxy(
  pipelineId: string,
  proxyId: string,
  payload: Partial<ProxyInput>,
): Promise<{ success: true; data: ProxyItem }> {
  return api(detail(pipelineId, proxyId), "PATCH", payload);
}

export function importProxies(
  pipelineId: string,
  items: ProxyInput[],
): Promise<{ success: true; data: { created: number } }> {
  return api(`${root(pipelineId)}bulk/`, "POST", { items });
}

export function deleteProxy(
  pipelineId: string,
  proxyId: string,
): Promise<{ success: true }> {
  return api(detail(pipelineId, proxyId), "DELETE");
}

export function checkProxyHealth(
  pipelineId: string,
  proxyId: string,
): Promise<{
  success: true;
  message: string;
  data: ProxyCheckResult;
}> {
  return api(`${detail(pipelineId, proxyId)}check/`, "POST");
}
