import { getCsrfToken } from '@/features/auth/api/auth-client';

export type Provider = { id: string; name: string; provider_type: string; base_url: string; default_model: string; is_active: boolean; is_default: boolean; rotation_authorized: boolean; timeout_seconds: number; last_status: string; last_tested_at: string | null; key_count: number; model_count: number; custom_header_names: string[] };
export type Key = { id: string; name: string; is_active: boolean; priority: number; last_status: string; last_tested_at: string | null; last_http_status: number | null };
export type Model = { id: string; provider: string; model_id: string; display_name: string; is_enabled: boolean; availability: string; source: string; supports_temperature: boolean | null; supports_top_p: boolean | null; temperature: number | null; top_p: number | null; max_output_tokens: number | null; output_token_limit: number | null; token_parameter: string; request_timeout: number; retry_count: number };
export type Step = { model: string; provider: string; model_name?: string; priority: number; timeout: number; retries: number; key_policy: string };
export type Route = { task: string; primary_model: string; primary_provider: string; primary_model_name: string; key_policy: string; is_enabled: boolean; version: number; fallbacks: Step[] };
export type Catalog = { providers: { id: string; name: string; base_url: string; protocol: string }[]; tasks: { id: string; name: string }[]; legacy: { configured: boolean; has_key: boolean; base_url: string; model: string } };
export type TestResult = { success: boolean; text?: string; error?: string; http_status?: number; latency_ms?: number; provider?: string; model?: string; usage?: Record<string, number>; fallback_index?: number; discovered?: number };
export type ModelPage = { items: Model[]; total: number; page: number; pages: number };
const base = '/api/v1/admin/config/ai';

export async function aiAPI<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== 'GET') { headers['Content-Type'] = 'application/json'; headers['X-CSRFToken'] = await getCsrfToken(); }
  const [endpoint, query] = path.split('?');
  const url = `${base}/${endpoint.replace(/\/$/, '')}/${query ? `?${query}` : ''}`;
  const response = await fetch(url, { method, headers, credentials: 'same-origin', cache: 'no-store', body: body === undefined ? undefined : JSON.stringify(body), signal: signal ?? AbortSignal.timeout(60000) });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(response.status === 403 ? 'Chỉ Super Admin được truy cập.' : result?.error || result?.detail || (result ? JSON.stringify(result) : `HTTP ${response.status}`));
  return result as T;
}
