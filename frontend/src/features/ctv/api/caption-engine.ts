import { getCsrfToken } from '@/features/auth/api/auth-client';

export type CaptionConfig = {
  enabled: boolean;
  destination: string;
  auto_generate: boolean;
  auto_approve: boolean;
  writing_guidance: string;
  version: number;
};
export type CaptionSample = { id: string; text: string; is_active: boolean; created_at: string };
export type CaptionItem = {
  job_id: string;
  state: 'generating' | 'draft' | 'approved' | 'failed' | 'rejected';
  text: string;
  revision: number;
  destination: string;
  model: string;
  settings_version: number;
  updated_at: string;
};
export type CaptionJob = {
  job_id: string;
  group: string;
  scheduled_at: string;
  job_state: string;
  caption: CaptionItem | null;
};

const base = (pipelineId: string) => `/api/v1/pipelines/${encodeURIComponent(pipelineId)}`;

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== 'GET') {
    headers.set('Content-Type', 'application/json');
    headers.set('X-CSRFToken', await getCsrfToken());
  }
  const response = await fetch(url, {
    ...init,
    headers,
    credentials: 'same-origin',
    cache: 'no-store',
  });
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== 'object') throw new Error(`HTTP ${response.status}`);
  const result = raw as { success?: boolean; data?: T; message?: string; detail?: string };
  if (!response.ok || result.success !== true) {
    throw new Error(result.message ?? result.detail ?? `HTTP ${response.status}`);
  }
  return result.data as T;
}

export const captionAPI = {
  settings: (pipelineId: string) => request<CaptionConfig>(`${base(pipelineId)}/caption-config/`),
  saveSettings: (pipelineId: string, data: CaptionConfig) => request<CaptionConfig>(
    `${base(pipelineId)}/caption-config/`, { method: 'PUT', body: JSON.stringify(data) }),
  samples: (pipelineId: string, page = 1) => request<{ items: CaptionSample[]; total: number; page: number }>(
    `${base(pipelineId)}/caption-samples/?page=${page}`),
  addSample: (pipelineId: string, text: string) => request<CaptionSample>(
    `${base(pipelineId)}/caption-samples/`, { method: 'POST', body: JSON.stringify({ text }) }),
  updateSample: (pipelineId: string, sampleId: string, data: { text?: string; is_active?: boolean }) => request<CaptionSample>(
    `${base(pipelineId)}/caption-samples/${encodeURIComponent(sampleId)}/`,
    { method: 'PATCH', body: JSON.stringify(data) }),
  deleteSample: (pipelineId: string, sampleId: string) => request<{ deleted: true }>(
    `${base(pipelineId)}/caption-samples/${encodeURIComponent(sampleId)}/`, { method: 'DELETE', body: '{}' }),
  jobs: (pipelineId: string) => request<{ items: CaptionJob[]; limit: number }>(
    `${base(pipelineId)}/caption-jobs/`),
  jobAction: (pipelineId: string, jobId: string, data: {
    action: 'generate' | 'approve' | 'reject'; revision?: number; text?: string;
  }) => request<CaptionItem>(`${base(pipelineId)}/publishing-jobs/${encodeURIComponent(jobId)}/caption/`,
    { method: 'POST', body: JSON.stringify(data) }),
};
