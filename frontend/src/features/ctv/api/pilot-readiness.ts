/** Pilot readiness is read-only; never equate a report with publication. */
export type PilotStage = 'ready' | 'blocked' | 'awaiting_review' | 'verified' | 'closed';
export type PilotStatus = 'incomplete' | 'not_configured' | 'blocked' | 'awaiting_review' |
  'ready_for_manual_pilot' | 'verified_records_only' | 'no_active_jobs';

export interface PilotJobRow {
  job_id: string;
  account: string;
  group: string;
  job_state: string;
  handoff_state: string | null;
  stage: PilotStage;
  blockers: string[];
  scheduled_at: string;
  verified_publication: boolean;
}
export interface PilotReadiness {
  pipeline_id: string;
  checked_at: string;
  status: PilotStatus;
  total_jobs: number;
  scanned_jobs: number;
  truncated: boolean;
  summary: Record<PilotStage, number>;
  items: PilotJobRow[];
  read_only: true;
  automatic_facebook_posting: false;
  no_real_publication_test_performed: true;
  note: string;
}

export async function getPilotReadiness(pipelineId: string, signal?: AbortSignal): Promise<PilotReadiness> {
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/pilot-readiness/?limit=50`,
    {method: 'GET', credentials: 'same-origin', cache: 'no-store', signal},
  );
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== 'object') {
    throw new Error(`Không đọc được Pilot (HTTP ${response.status}).`);
  }
  const payload = raw as {success?: unknown; data?: PilotReadiness; message?: string};
  if (!response.ok || payload.success !== true) {
    throw new Error(payload.message || `Lỗi Pilot HTTP ${response.status}`);
  }
  const data = payload.data;
  if (!data || data.pipeline_id !== pipelineId || !Array.isArray(data.items) ||
      !data.summary || !Number.isSafeInteger(data.total_jobs) ||
      !Number.isSafeInteger(data.scanned_jobs) ||
      data.read_only !== true || data.automatic_facebook_posting !== false ||
      data.no_real_publication_test_performed !== true || typeof data.truncated !== 'boolean') {
    throw new Error('Dữ liệu Pilot sai định dạng hoặc ngoài Pipeline.');
  }
  return data;
}
