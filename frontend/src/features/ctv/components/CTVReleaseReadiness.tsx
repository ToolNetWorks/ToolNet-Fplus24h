'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ClipboardCheck, RefreshCw, ShieldAlert } from 'lucide-react';
import { readReleaseReadiness, type ReleaseReadiness, type ReleaseCheckState } from '../api/release-readiness';

const checkNames: Record<string, string> = {
  PIPELINE_ACTIVE: 'Pipeline đang hoạt động',
  OPERATIONS_HEALTH: 'Operations Health',
  INTEGRITY_COMPLETE: 'Integrity Audit',
  TENANT_SECURITY: 'Tenant Isolation & Security',
  WORKER_LEASES: 'Worker Reliability',
  PILOT_SCAN_COMPLETE: 'Pilot scan hoàn tất',
  INDEPENDENT_POST_EVIDENCE: 'Bằng chứng bài đăng độc lập',
  PERFORMANCE_BASELINE: 'Performance Baseline',
  VPS_SERVICES_AND_HTTP: 'Kiểm tra dịch vụ VPS và HTTP',
  BACKUP_AND_RESTORE: 'Sao lưu và phục hồi',
  REAL_GROUP_PILOT: 'Pilot đăng thực tế trong Group',
  OPERATOR_APPROVAL: 'Người vận hành ký duyệt',
};
const checkLabels: Record<ReleaseCheckState, string> = {
  pass: 'Đạt', blocked: 'Chưa đạt', manual_required: 'Cần xác nhận thủ công', not_checked: 'Chưa kiểm tra',
};
const tones: Record<ReleaseCheckState, string> = {
  pass: 'bg-emerald-50 text-emerald-700',
  blocked: 'bg-rose-50 text-rose-700',
  manual_required: 'bg-slate-100 text-slate-700',
  not_checked: 'bg-amber-50 text-amber-800',
};
const fmt = (value: number) => value.toLocaleString('vi-VN');

export default function CTVReleaseReadiness({ pipelineId }: { pipelineId: string }) {
  const [data, setData] = useState<ReleaseReadiness | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    setData(null); setError('');
    return () => request.current?.abort();
  }, [pipelineId]);

  async function inspect() {
    if (loading) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true); setError(''); setData(null);
    try {
      const result = await readReleaseReadiness(pipelineId, controller.signal);
      if (!controller.signal.aborted) setData(result);
    } catch (cause: unknown) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Không kiểm tra được nghiệm thu.');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return <section className="space-y-4" aria-label="Nghiệm thu production ToolNet Fplus24h">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Production Release & Nghiệm thu</h1>
        <p className="mt-1 text-xs text-slate-500">ToolNet Fplus24h · Chỉ đọc dữ liệu nội bộ Pipeline</p>
      </div>
      <button type="button" onClick={() => void inspect()} disabled={loading}
        className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50">
        <RefreshCw size={14} aria-hidden="true" />{loading ? 'Đang kiểm tra...' : 'Đánh giá phát hành'}
      </button>
    </div>
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
      Bước 9.7.20 là cổng nghiệm thu, không phải nút phát hành. Kiểm tra này không xác nhận VPS đang chạy, backup đã phục hồi hoặc Facebook đã đăng thành công. Cần người vận hành kiểm tra và duyệt riêng.
    </div>
    {error && <div role="alert" className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
      <AlertTriangle size={15} aria-hidden="true" />{error}
    </div>}
    {!data && !loading && !error && <div className="rounded-lg border border-dashed border-slate-200 bg-white p-8 text-center text-sm text-slate-500">Chưa đánh giá trong phiên này.</div>}
    {loading && <p role="status" className="text-xs text-slate-500">Đang đối chiếu vận hành, bảo mật, Pilot và hiệu năng...</p>}
    {data && <>
      <div role="status" className={`flex items-start gap-3 rounded-lg border p-4 ${data.status === 'blocked'
        ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>
        <ShieldAlert size={18} className="shrink-0" aria-hidden="true" />
        <div>
          <p className="text-sm font-bold">{data.status === 'blocked' ? 'NO-GO — chưa đủ điều kiện nội bộ' : 'Chờ người vận hành ký duyệt — chưa được phát hành'}</p>
          <p className="mt-1 text-xs">Không có quyền tự động chấp thuận phát hành hoặc đăng Facebook. Bài chờ duyệt không được tính là đã xuất bản.</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {([
          ['Tiêu chí', data.summary.total], ['Đã đạt', data.summary.passed],
          ['Chưa đạt', data.summary.blocked], ['Cần ký duyệt', data.summary.manual_required],
        ] as const).map(([label, value]) => <div className="rounded-lg border border-slate-200 bg-white p-4" key={label}>
          <p className="text-xs text-slate-500">{label}</p>
          <p className="mt-2 text-2xl font-bold tabular-nums text-slate-900">{fmt(value)}</p>
        </div>)}
      </div>
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><ClipboardCheck size={16}/> Danh sách nghiệm thu</h2>
          <span className="text-[11px] text-slate-500">{new Date(data.checked_at).toLocaleString('vi-VN')} · {fmt(data.duration_ms)} ms</span>
        </div>
        <div className="overflow-x-auto"><table className="w-full min-w-[740px] text-left text-xs">
          <thead><tr className="bg-slate-50 text-slate-500"><th className="px-4 py-3">Hạng mục</th><th className="px-4 py-3">Trạng thái</th><th className="px-4 py-3">Ghi chú</th></tr></thead>
          <tbody>{data.checks.map(check => <tr className="border-t border-slate-100" key={check.code}>
            <td className="px-4 py-3 font-semibold text-slate-800">{checkNames[check.code] ?? check.code}</td>
            <td className="px-4 py-3"><span className={`inline-block whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-medium ${tones[check.status]}`}>{checkLabels[check.status]}</span></td>
            <td className="px-4 py-3 text-slate-600">{check.description}</td>
          </tr>)}</tbody>
        </table></div>
      </div>
      {data.errors.length > 0 && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
        {data.errors.length} lỗi truy vấn nội bộ: {data.errors.join(', ')}
      </p>}
      <p className="text-xs leading-relaxed text-slate-500">Đã xác minh độc lập trong dữ liệu nội bộ: {fmt(data.summary.verified_pilot_records)} bản ghi. Phép kiểm tra không thay thế quan sát Facebook thực tế hoặc kiểm thử xâm nhập/khôi phục VPS.</p>
    </>}
  </section>;
}
