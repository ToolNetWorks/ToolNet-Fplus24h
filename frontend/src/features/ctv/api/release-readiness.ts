/** One-shot read-only release assessment; NEVER an approval or deployment. */
export type ReleaseState = 'blocked' | 'pending_operator_signoff';
export type ReleaseCheckState = 'pass' | 'blocked' | 'manual_required' | 'not_checked';

export interface ReleaseCheck {
  code: string;
  status: ReleaseCheckState;
  description: string;
}

export interface ReleaseReadiness {
  pipeline_id: string;
  checked_at: string;
  status: ReleaseState;
  release_approved: false;
  automatic_facebook_posting_enabled: false;
  external_signoff_recorded: false;
  read_only: true;
  checks: ReleaseCheck[];
  summary: {
    total: number;
    passed: number;
    blocked: number;
    manual_required: number;
    probe_errors: number;
    verified_pilot_records: number;
  };
  errors: string[];
  duration_ms: number;
  notes: string[];
}

const checkStatuses = ['pass', 'blocked', 'manual_required', 'not_checked'];
const validCount = (n: unknown): n is number => Number.isSafeInteger(n) && (n as number) >= 0;

export async function readReleaseReadiness(pipelineId: string, signal?: AbortSignal): Promise<ReleaseReadiness> {
  const response = await fetch(`/api/v1/pipelines/${encodeURIComponent(pipelineId)}/release-readiness/`, {
    method: 'GET', credentials: 'same-origin', cache: 'no-store', signal,
  });
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== 'object') throw new Error(`Không nhận được phản hồi (HTTP ${response.status}).`);
  const body = raw as { success?: unknown; data?: ReleaseReadiness; message?: string };
  if (!response.ok || body.success !== true) throw new Error(body.message || `HTTP ${response.status}`);
  const data = body.data;
  if (!data || data.pipeline_id !== pipelineId ||
      !['blocked', 'pending_operator_signoff'].includes(data.status) ||
      data.release_approved !== false || data.external_signoff_recorded !== false ||
      data.automatic_facebook_posting_enabled !== false || data.read_only !== true ||
      typeof data.checked_at !== 'string' || Number.isNaN(Date.parse(data.checked_at)) ||
      !Array.isArray(data.checks) || data.checks.length !== 12 ||
      data.checks.some(check => typeof check.code !== 'string' ||
        typeof check.description !== 'string' || !checkStatuses.includes(check.status)) ||
      !data.summary || !validCount(data.summary.total) || !validCount(data.summary.passed) ||
      !validCount(data.summary.blocked) || !validCount(data.summary.manual_required) ||
      !validCount(data.summary.probe_errors) || !validCount(data.summary.verified_pilot_records) ||
      !Array.isArray(data.errors) || data.errors.some(x => typeof x !== 'string') ||
      !Array.isArray(data.notes) || data.notes.some(x => typeof x !== 'string') ||
      typeof data.duration_ms !== 'number' || !Number.isFinite(data.duration_ms)) {
    throw new Error('Phản hồi nghiệm thu không hợp lệ hoặc sai Pipeline.');
  }
  return data;
}
