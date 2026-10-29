/** On-demand, bounded read-only database baseline, not a Facebook or load test. */
export type PerformanceStatus = 'pass' | 'attention' | 'not_configured' | 'incomplete' | 'error';
export type ProbeStatus = 'pass' | 'slow' | 'incomplete' | 'error';

export interface PerformanceProbe {
  name: string;
  status: ProbeStatus;
  runs: number;
  p50_ms: number;
  p95_ms: number;
  max_ms: number;
  query_count_max: number;
  budget_ms: number;
  operational_attention: boolean;
}

export interface PerformanceSnapshot {
  pipeline_id: string;
  checked_at: string;
  status: PerformanceStatus;
  pipeline_status: string;
  summary: {
    probes: number;
    errors: number;
    slow: number;
    incomplete: number;
    operational_attention: number;
    jobs: number;
    schedules: number;
  };
  probes: PerformanceProbe[];
  repeats: number;
  sample_limit: number;
  read_only: true;
  facebook_dispatch_enabled: false;
  load_test_performed: false;
  production_capacity_certified: false;
  note: string;
}

const statuses = ['pass', 'attention', 'not_configured', 'incomplete', 'error'];
const probeStatuses = ['pass', 'slow', 'incomplete', 'error'];
const validCount = (x: unknown): x is number => Number.isSafeInteger(x) && (x as number) >= 0;
const validMetric = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x) && x >= 0;

export async function getPerformanceSnapshot(pipelineId: string, signal?: AbortSignal): Promise<PerformanceSnapshot> {
  const response = await fetch(`/api/v1/pipelines/${encodeURIComponent(pipelineId)}/performance/`, {
    method: 'GET', credentials: 'same-origin', cache: 'no-store', signal,
  });
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== 'object') throw new Error(`Không có dữ liệu (HTTP ${response.status}).`);
  const payload = raw as { success?: unknown; message?: unknown; data?: PerformanceSnapshot };
  if (!response.ok || payload.success !== true) {
    throw new Error(typeof payload.message === 'string' ? payload.message : `HTTP ${response.status}`);
  }
  const data = payload.data;
  if (!data || data.pipeline_id !== pipelineId || !statuses.includes(data.status) ||
      data.read_only !== true || data.facebook_dispatch_enabled !== false ||
      data.load_test_performed !== false || data.production_capacity_certified !== false ||
      !Array.isArray(data.probes) || data.probes.length !== 6 ||
      !data.summary || !validCount(data.summary.errors) || !validCount(data.summary.jobs) ||
      !validCount(data.summary.schedules) || !validCount(data.summary.incomplete) ||
      !validCount(data.summary.slow) || !validCount(data.summary.operational_attention) ||
      typeof data.checked_at !== 'string' || Number.isNaN(Date.parse(data.checked_at)) ||
      data.probes.some((p) => !probeStatuses.includes(p.status) || !validCount(p.runs) ||
        !validMetric(p.p50_ms) || !validMetric(p.p95_ms) || !validMetric(p.max_ms) ||
        !validCount(p.query_count_max) || !validCount(p.budget_ms) ||
        typeof p.operational_attention !== 'boolean')) {
    throw new Error('Dữ liệu đo hiệu năng không hợp lệ hoặc sai Pipeline.');
  }
  return data;
}
