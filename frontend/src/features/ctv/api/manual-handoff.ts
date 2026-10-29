/** Manual handoff is only an operator observation, NEVER publication proof. */
export type ManualState =
  | 'prepared' | 'opened' | 'submitted_reported' | 'pending_reported'
  | 'rejected_reported' | 'inconclusive' | 'abandoned';
export type ReportedOutcome = Extract<ManualState,
  'submitted_reported' | 'pending_reported' | 'rejected_reported' | 'inconclusive'>;
export interface ManualMedia {
  image_id: string; album_id: string; position: number; available: boolean;
}
export interface ManualHandoff {
  id: string; job_id: string; pipeline_id: string; state: ManualState;
  version: number; account_label: string; group_name: string;
  group_url: string; caption: string; job_state: string;
  media: ManualMedia[]; note: string; prepared_at: string;
  opened_at: string | null; publication_verified: false;
  automatic_facebook_posting: false;
  events: { id: string; kind: string; outcome: string; note: string; recorded_at: string }[];
  events_truncated: boolean;
}
export interface ManualSnapshot {
  handoff: ManualHandoff | null; can_prepare: boolean;
  job_state: string; facebook_groups_api_supported: false;
}
const endpoint = (pipelineId: string, jobId: string) =>
  `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/publishing-jobs/${encodeURIComponent(jobId)}/manual-handoff/`;

async function parse<T>(res: Response): Promise<T> {
  const raw: unknown = await res.json().catch(() => null);
  if (!raw || typeof raw !== 'object') throw new Error(`HTTP ${res.status}: phản hồi không hợp lệ.`);
  const payload = raw as { success?: unknown; data?: T; message?: string; detail?: string };
  if (!res.ok || payload.success !== true) {
    throw new Error(payload.message || payload.detail || `HTTP ${res.status}`);
  }
  if (!payload.data) throw new Error('Không có dữ liệu từ server.');
  return payload.data;
}
export async function readManualHandoff(
  pipelineId: string, jobId: string, signal?: AbortSignal,
): Promise<ManualSnapshot> {
  const result = await parse<ManualSnapshot>(await fetch(endpoint(pipelineId, jobId), {
    credentials: 'same-origin', cache: 'no-store', signal,
  }));
  if (result.handoff && (result.handoff.pipeline_id !== pipelineId ||
      result.handoff.job_id !== jobId || result.handoff.publication_verified !== false ||
      result.handoff.automatic_facebook_posting !== false)) {
    throw new Error('Handoff không đúng Pipeline/Job hoặc dữ liệu xác minh không hợp lệ.');
  }
  return result;
}
export async function manualAction(
  pipelineId: string, jobId: string,
  body: { action: 'prepare' } | { action: 'open' | 'abandon'; expected_version: number } |
    { action: 'report'; expected_version: number; outcome: ReportedOutcome; note: string },
  csrfToken: string,
): Promise<ManualHandoff> {
  const result = await parse<ManualHandoff>(await fetch(endpoint(pipelineId, jobId), {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
    body: JSON.stringify(body),
  }));
  if (result.pipeline_id !== pipelineId || result.job_id !== jobId ||
      result.publication_verified !== false || result.automatic_facebook_posting !== false) {
    throw new Error('Dữ liệu handoff không hợp lệ.');
  }
  return result;
}
export function manualMediaUrl(pipelineId: string, item: ManualMedia): string {
  return `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/albums/${encodeURIComponent(item.album_id)}/images/${encodeURIComponent(item.image_id)}/content/`;
}
