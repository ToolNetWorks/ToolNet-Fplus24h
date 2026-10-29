'use client';

import { useEffect, useRef, useState } from 'react';
import { Activity, AlertTriangle, RefreshCw } from 'lucide-react';
import { getPerformanceSnapshot, type PerformanceSnapshot, type ProbeStatus } from '../api/performance-stability';

const names: Record<string, string> = {
  database_ping: 'Neon PostgreSQL · Ping',
  operations_health: 'Operations Health',
  scheduler_preview: 'Scheduler · Preview (không tạo Job)',
  worker_guard: 'Worker Guard',
  pilot_readiness: 'Pilot Readiness',
  security_audit: 'Security Audit',
};
const statusLabels: Record<string, string> = {
  pass: 'Trong ngưỡng', slow: 'Chậm', incomplete: 'Chưa quét hết', error: 'Lỗi',
  attention: 'Cần kiểm tra', not_configured: 'Chưa có Job/Lịch',
};
const tone: Record<ProbeStatus, string> = {
  pass: 'bg-emerald-50 text-emerald-700',
  slow: 'bg-amber-50 text-amber-800',
  incomplete: 'bg-amber-50 text-amber-800',
  error: 'bg-rose-50 text-rose-700',
};
const fmt = (value: number) => value.toLocaleString('vi-VN', { maximumFractionDigits: 2 });

export default function CTVPerformanceStability({ pipelineId }: { pipelineId: string }) {
  const [data, setData] = useState<PerformanceSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    setData(null); setError('');
    return () => request.current?.abort();
  }, [pipelineId]);

  async function run() {
    if (loading) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true); setError(''); setData(null);
    try {
      const result = await getPerformanceSnapshot(pipelineId, controller.signal);
      if (!controller.signal.aborted) setData(result);
    } catch (cause: unknown) {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'Không đo được hiệu năng.');
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return <section className="space-y-4" aria-label="Hiệu năng và độ ổn định ToolNet Fplus24h">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Hiệu năng & Độ ổn định</h1>
        <p className="mt-1 text-xs text-slate-500">ToolNet Fplus24h · Đo độ trễ và số truy vấn Neon theo từng Pipeline</p>
      </div>
      <button type="button" disabled={loading} onClick={() => void run()}
        className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50">
        <RefreshCw size={14} aria-hidden="true" />{loading ? 'Đang kiểm tra...' : 'Chạy kiểm tra'}
      </button>
    </div>
    <p className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-700">
      Chỉ chạy khi bấm nút; phép đo tuần tự một lượt, giới hạn 25 bản ghi mỗi loại. Không gửi bài Facebook,
      không tạo Job và không sửa database. Đây không phải kiểm thử tải đồng thời hoặc chứng nhận production.
    </p>
    {error && <div role="alert" className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">
      <AlertTriangle size={16} />Không thể đo hiệu năng: {error}
    </div>}
    {!data && !loading && !error && <div className="rounded-lg border border-dashed border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
      Chưa chạy kiểm tra trong phiên này. Bấm “Chạy kiểm tra” để lấy dữ liệu mới.
    </div>}
    {loading && <p className="text-xs text-slate-500" role="status">Đang đo 6 nhóm truy vấn nội bộ...</p>}
    {data && <>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {([
          ['Nhóm đo', data.summary.probes], ['Đo chậm', data.summary.slow],
          ['Đo lỗi', data.summary.errors], ['Chưa quét hết', data.summary.incomplete],
        ] as const).map(([label, value]) => <div className="rounded-lg border border-slate-200 bg-white p-4" key={label}>
          <div className="flex items-center justify-between text-xs text-slate-500"><span>{label}</span><Activity size={15}/></div>
          <strong className="mt-2 block text-2xl font-semibold tabular-nums text-slate-900">{fmt(value)}</strong>
        </div>)}
      </div>
      <p className="text-xs text-slate-600">Kết quả: <strong>{statusLabels[data.status] ?? data.status}</strong>
        {' · '}Lần đo: {new Date(data.checked_at).toLocaleString('vi-VN')}
        {' · '}Job {fmt(data.summary.jobs)} · Lịch {fmt(data.summary.schedules)}</p>
      {data.summary.operational_attention > 0 && <p role="status" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
        Có {data.summary.operational_attention} nhóm có cảnh báo vận hành. Ngay cả khi độ trễ đạt ngưỡng, cần kiểm tra các cảnh báo này.
      </p>}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-900">Bảng đo hiệu năng theo dịch vụ</h2>
          <span className="text-[11px] text-slate-500">p50/p95 là số liệu của lần lấy mẫu, không phải percentile lịch sử</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="bg-slate-50 text-slate-500"><tr>
              {['Dịch vụ', 'p50 (ms)', 'p95 (ms)', 'Ngưỡng (ms)', 'Số query', 'Tình trạng'].map(x => <th key={x} className="px-3 py-3">{x}</th>)}
            </tr></thead>
            <tbody>{data.probes.map(p => <tr key={p.name} className="border-t border-slate-100">
              <th scope="row" className="px-3 py-3 font-medium text-slate-800">{names[p.name] ?? p.name}</th>
              <td className="px-3 py-3 tabular-nums">{fmt(p.p50_ms)}</td>
              <td className="px-3 py-3 tabular-nums">{fmt(p.p95_ms)}</td>
              <td className="px-3 py-3 tabular-nums">{fmt(p.budget_ms)}</td>
              <td className="px-3 py-3 tabular-nums">{fmt(p.query_count_max)}</td>
              <td className="px-3 py-3"><span className={`whitespace-nowrap rounded px-2 py-1 text-[11px] font-medium ${tone[p.status]}`}>
                {statusLabels[p.status]}
              </span>{p.operational_attention && <span className="ml-2 text-amber-700">Có cảnh báo</span>}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </div>
      <p className="text-[11px] text-slate-500">{data.note}</p>
    </>}
  </section>;
}
