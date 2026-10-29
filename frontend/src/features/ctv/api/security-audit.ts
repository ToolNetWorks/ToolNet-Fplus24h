/** Tenant-scoped metadata inspection; no penetration-test certification. */
export interface SecurityFinding {
  code: string;
  severity: 'critical' | 'warning';
  object_type: string;
  object_id: string;
}

export interface SecurityAudit {
  pipeline_id: string;
  checked_at: string;
  status: 'consistent' | 'attention_required' | 'incomplete';
  complete: boolean;
  findings: SecurityFinding[];
  summary: { findings_in_sample: number; critical_in_sample: number };
  sampled_violations_by_category: Record<string, number>;
  truncated_categories: string[];
  limit_per_category: number;
  read_only: true;
  production_security_certified: false;
  contains_credentials: false;
  note: string;
}

export async function getSecurityAudit(pipelineId: string, signal?: AbortSignal): Promise<SecurityAudit> {
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/security-audit/?limit=50`,
    { method: 'GET', credentials: 'same-origin', cache: 'no-store', signal },
  );
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== 'object') throw new Error(`Không đọc được phản hồi HTTP ${response.status}`);
  const result = raw as { success?: unknown; data?: SecurityAudit; message?: string; detail?: string };
  if (!response.ok || result.success !== true) {
    throw new Error(result.message || result.detail || `HTTP ${response.status}`);
  }
  const audit = result.data;
  if (!audit || audit.pipeline_id !== pipelineId ||
      !['consistent', 'attention_required', 'incomplete'].includes(audit.status) ||
      !Array.isArray(audit.findings) || !Array.isArray(audit.truncated_categories) ||
      !audit.summary || !audit.sampled_violations_by_category || typeof audit.complete !== 'boolean' ||
      audit.read_only !== true || audit.production_security_certified !== false ||
      audit.contains_credentials !== false ||
      typeof audit.checked_at !== 'string' || Number.isNaN(Date.parse(audit.checked_at)) ||
      !Number.isSafeInteger(audit.summary.findings_in_sample) ||
      audit.findings.some(row => !row || typeof row.code !== 'string' ||
        !['warning', 'critical'].includes(row.severity) ||
        typeof row.object_id !== 'string' || typeof row.object_type !== 'string') ||
      (audit.status === 'consistent' && (!audit.complete || audit.findings.length > 0)) ||
      (audit.status === 'incomplete' && audit.complete)) {
    throw new Error('Dữ liệu kiểm toán sai Pipeline hoặc không đúng định dạng.');
  }
  return audit;
}
