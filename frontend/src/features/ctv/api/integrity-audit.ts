export interface IntegrityFinding {
  code: string;
  severity: "critical" | "warning";
  object_type: string;
  object_id: string;
}
export interface IntegrityAudit {
  pipeline_id: string;
  status: "consistent" | "attention_required" | "incomplete";
  complete: boolean;
  summary: {
    total: number;
    queued: number;
    uncertain: number;
    published: number;
    failed: number;
    critical: number;
    warnings: number;
    findings_in_sample: number;
  };
  findings: IntegrityFinding[];
  scanned: Record<string, number>;
  truncated_categories: string[];
  sample_limit_per_category: number;
  read_only: true;
  facebook_publication_verified_by_audit: false;
  note: string;
}

export async function getIntegrityAudit(
  pipelineId: string,
  limit = 100,
  signal?: AbortSignal,
): Promise<IntegrityAudit> {
  const response = await fetch(
    `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/integrity-audit/?limit=${limit}`,
    { method: "GET", credentials: "same-origin", cache: "no-store", signal },
  );
  const raw: unknown = await response.json().catch(() => null);
  if (!raw || typeof raw !== "object") {
    throw new Error(`Phản hồi kiểm toán không hợp lệ (HTTP ${response.status}).`);
  }
  const value = raw as { success?: unknown; data?: IntegrityAudit; detail?: string; message?: string };
  if (!response.ok || value.success !== true) {
    throw new Error(value.message || value.detail || `Không thể kiểm toán (HTTP ${response.status}).`);
  }
  const data = value.data;
  if (!data || data.pipeline_id !== pipelineId || !Array.isArray(data.findings) ||
      !Array.isArray(data.truncated_categories) || !data.summary ||
      data.read_only !== true || data.facebook_publication_verified_by_audit !== false ||
      typeof data.complete !== "boolean") {
    throw new Error("Dữ liệu kiểm toán sai Pipeline hoặc không đúng định dạng.");
  }
  return data;
}
