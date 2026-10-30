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

export type PublicationStatus =
  | 'awaiting_ai' | 'approved' | 'awaiting_handoff'
  | 'processing' | 'awaiting_verification' | 'published' | 'failed';

export const PUBLICATION_STATUS_LABELS: Record<PublicationStatus, string> = {
  awaiting_ai: 'Chờ AI',
  approved: 'Đã duyệt',
  awaiting_handoff: 'Chờ bàn giao',
  processing: 'Đang xử lý',
  awaiting_verification: 'Chờ xác minh',
  published: 'Thành công',
  failed: 'Thất bại',
};

export const PUBLICATION_STATUS_COLORS: Record<PublicationStatus, string> = {
  awaiting_ai: 'bg-slate-100 text-slate-600',
  approved: 'bg-amber-100 text-amber-800',
  awaiting_handoff: 'bg-blue-100 text-blue-800',
  processing: 'bg-purple-100 text-purple-800',
  awaiting_verification: 'bg-orange-100 text-orange-800',
  published: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
};

export interface QueueMedia {
  image_id: string;
  album_id: string;
  position: number;
}

export interface QueueItem {
  job_id: string;
  pipeline_id: string;
  state: string;
  unified_status: PublicationStatus;
  unified_status_label: string;
  caption: string;
  caption_state: string | null;
  caption_revision: number;
  account: { id: string; label: string };
  group: { id: string; name: string; url: string; key: string };
  scheduled_at: string;
  next_run_at: string;
  attempt_count: number;
  max_attempts: number;
  media_allocation_id: string | null;
  media: QueueMedia[];
  external_post_id: string | null;
  verified_published: boolean;
  error_code: string | null;
  handoff: ManualHandoff | null;
  can_prepare: boolean;
  automatic_facebook_posting: false;
  facebook_groups_api_supported: false;
}

export interface HandoffQueueResponse {
  pipeline_id: string;
  items: QueueItem[];
  summary: { total: Record<PublicationStatus, number> };
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  };
  status_labels: Record<PublicationStatus, string>;
  automatic_facebook_posting: false;
  facebook_groups_api_supported: false;
}

const queueEndpoint = (pipelineId: string) =>
  `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/handoff-queue/`;

export async function listHandoffQueue(
  pipelineId: string,
  options: { page?: number; pageSize?: number; status?: string },
  signal?: AbortSignal,
): Promise<HandoffQueueResponse> {
  const params = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 20),
  });
  if (options.status) params.set('status', options.status);
  const result = await parse<HandoffQueueResponse>(
    await fetch(`${queueEndpoint(pipelineId)}?${params}`, {
      credentials: 'same-origin', cache: 'no-store', signal,
    }),
  );
  if (result.automatic_facebook_posting !== false ||
      result.facebook_groups_api_supported !== false) {
    throw new Error('Cấu hình bảo mật không hợp lệ.');
  }
  return result;
}
