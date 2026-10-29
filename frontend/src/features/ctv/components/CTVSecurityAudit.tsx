'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, FileCheck2, RefreshCw, ShieldAlert, ShieldCheck } from 'lucide-react';
import { getSecurityAudit, type SecurityAudit } from '../api/security-audit';

const issueNames: Record<string, string> = {
  JOB_ACCOUNT_FOREIGN: 'Job dùng Account của Pipeline khác',
  JOB_GROUP_FOREIGN: 'Job dùng Group của Pipeline khác',
  JOB_MEDIA_FOREIGN: 'Job liên kết ảnh của Pipeline khác',
  PROXY_ACCOUNT_FOREIGN: 'Proxy gắn Account ngoài Pipeline',
  PROXY_PIN_ACCOUNT_FOREIGN: 'Proxy Pin tham chiếu Account ngoài Pipeline',
  PROXY_PIN_PROXY_FOREIGN: 'Proxy Pin tham chiếu Proxy ngoài Pipeline',
  PROXY_PIN_ACCOUNT_MISMATCH: 'Proxy Pin liên kết sai Account',
  PROXY_PIN_EXIT_IP_MISMATCH: 'IP Proxy khác địa chỉ IP được ghim',
  ELIGIBILITY_ACCOUNT_FOREIGN: 'Xác minh quyền Group dùng Account ngoài Pipeline',
  ELIGIBILITY_GROUP_FOREIGN: 'Xác minh quyền Group tham chiếu Group ngoài Pipeline',
  ALBUM_SOURCE_FOREIGN: 'Nguồn Album tham chiếu Album ngoài Pipeline',
  HANDOFF_JOB_FOREIGN: 'Bàn giao đăng bài tham chiếu Job ngoài Pipeline',
  HANDOFF_ACTOR_FOREIGN: 'Người thực hiện bàn giao không thuộc Pipeline',
  WORKER_EVENT_JOB_FOREIGN: 'Nhật ký Worker tham chiếu Job ngoài Pipeline',
  ALERT_ACK_ACTOR_FOREIGN: 'Cảnh báo được xác nhận bởi người không có quyền',
  IMAGE_ALLOCATION_FOREIGN: 'Ảnh phân bổ từ Pipeline khác',
  IMAGE_ALLOCATION_IDENTITY_MISMATCH: 'Định danh ảnh phân bổ không khớp',
  COOKIE_CIPHERTEXT_EMPTY: 'Bản ghi cookie mã hóa bị rỗng',
  PROXY_CIPHERTEXT_EMPTY: 'Bản ghi xác thực Proxy mã hóa bị rỗng',
  ALBUM_IMAGE_STORAGE_SCOPE: 'Đường dẫn lưu ảnh không đúng phạm vi Pipeline',
};

export default function CTVSecurityAudit({ pipelineId }: { pipelineId: string }) {
  const [data, setData] = useState<SecurityAudit | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [revision, setRevision] = useState(0);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setError('');
    getSecurityAudit(pipelineId, controller.signal)
      .then(audit => { if (!controller.signal.aborted) setData(audit); })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setData(null); setError(cause instanceof Error ? cause.message : 'Không thể kiểm toán.');
        }
      })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [pipelineId, revision]);

  const items = (data?.findings ?? []).filter(item =>
    !filter || `${issueNames[item.code] ?? item.code} ${item.object_type} ${item.object_id}`
      .toLocaleLowerCase('vi-VN').includes(filter.toLocaleLowerCase('vi-VN')));
  const status = !data ? 'Không có kết quả' : data.status === 'incomplete' ?
    'Chưa quét đủ — không được kết luận' : data.status === 'attention_required' ?
    'Phát hiện dữ liệu cần kiểm tra' : 'Các quan hệ được kiểm tra không có sai lệch';
  return <section className="space-y-4" aria-label="Kiểm toán bảo mật Pipeline">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Kiểm toán bảo mật</h1>
        <p className="mt-1 text-xs text-slate-500">ToolNet Fplus24h · Kiểm tra cách ly dữ liệu nội bộ theo Pipeline</p>
        <p className="mt-1 text-[11px] text-slate-400">Không kiểm tra Facebook, không truy xuất cookie, không tự thay đổi dữ liệu.</p>
      </div>
      <button type="button" disabled={busy} onClick={() => setRevision(n => n + 1)}
        className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs disabled:opacity-40">
        <RefreshCw size={14} />{busy ? 'Đang kiểm tra...' : 'Kiểm tra lại'}
      </button>
    </header>
    {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-800">
      Không thể xác minh trạng thái bảo mật: {error}
    </p>}
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-800">
        {data?.status === 'consistent' ? <ShieldCheck size={18} /> : <ShieldAlert size={18} />}{status}
      </div>
      <p className="mt-2 text-xs text-slate-500">{data ? new Date(data.checked_at).toLocaleString('vi-VN') : 'Chưa kiểm tra'}</p>
      <p className="mt-2 text-[11px] text-amber-800">Đây là kiểm toán quan hệ dữ liệu và metadata. Không phải chứng nhận bảo mật production hoặc kết quả penetration test.</p>
    </div>
    {data && <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {([
          ['Vấn đề trong mẫu', data.summary.findings_in_sample],
          ['Mức nghiêm trọng', data.summary.critical_in_sample],
          ['Danh mục đã kiểm tra', Object.keys(data.sampled_violations_by_category).length],
        ] as const).map(([title, value]) => <div key={title} className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-xs text-slate-500">{title}</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{value.toLocaleString('vi-VN')}</p>
        </div>)}
      </div>
      {data.truncated_categories.length > 0 && <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        <AlertTriangle size={14} className="mr-1 inline" />Vượt giới hạn 50 bản ghi/danh mục ở: {data.truncated_categories.join(', ')}. Dùng CLI tăng --limit để kiểm toán đầy đủ.
      </div>}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800"><FileCheck2 size={16} />Danh sách vấn đề</h2>
          <input aria-label="Tìm vấn đề" value={filter} onChange={event => setFilter(event.target.value)}
            className="rounded-md border border-slate-200 px-3 py-2 text-xs" placeholder="Tìm loại lỗi hoặc mã bản ghi" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="bg-slate-50 text-slate-500"><tr><th className="px-4 py-3">Mức độ</th><th className="px-4 py-3">Vấn đề</th><th className="px-4 py-3">Đối tượng</th><th className="px-4 py-3">ID</th></tr></thead>
            <tbody>{items.length ? items.map((item, index) => <tr key={`${item.code}-${item.object_id}-${index}`} className="border-t border-slate-100">
              <td className="px-4 py-3 font-medium text-red-700">{item.severity === 'critical' ? 'Nghiêm trọng' : 'Cảnh báo'}</td>
              <td className="px-4 py-3 text-slate-700">{issueNames[item.code] ?? item.code}</td>
              <td className="px-4 py-3 text-slate-500">{item.object_type}</td>
              <td className="px-4 py-3 font-mono text-slate-500" title={item.object_id}>{item.object_id.slice(0, 12)}</td>
            </tr>) : <tr><td colSpan={4} className="px-4 py-10 text-center text-slate-500">
              {filter ? 'Không có kết quả phù hợp.' : 'Không phát hiện sai lệch trong phạm vi được quét.'}
            </td></tr>}</tbody>
          </table>
        </div>
      </div>
    </>}
    {!data && busy && <p role="status" className="text-xs text-slate-500">Đang truy vấn dữ liệu Pipeline...</p>}
  </section>;
}
