'use client';

import {useCallback, useEffect, useMemo, useState} from 'react';
import {ClipboardCheck, RefreshCw, ShieldAlert} from 'lucide-react';
import {getPilotReadiness, type PilotReadiness, type PilotStage} from '../api/pilot-readiness';

const titles: Record<PilotStage, string> = {
  ready: 'Sẵn sàng kiểm thử', blocked: 'Thiếu điều kiện',
  awaiting_review: 'Cần đối soát', verified: 'Xác minh độc lập', closed: 'Đã kết thúc',
};
const codes: Record<string, string> = {
  PUBLISHED_WITHOUT_TRUST_CHAIN: 'Không đủ chuỗi bằng chứng xuất bản',
  UNSUPPORTED_JOB_STATE: 'Trạng thái Job không hỗ trợ',
  PIPELINE_INACTIVE: 'Pipeline đã khóa',
  PREVIOUS_ATTEMPT_EXISTS: 'Job đã có lần xử lý trước',
  NOT_DUE: 'Job chưa tới thời điểm đăng',
  ACCOUNT_OR_GROUP_HAS_HELD_JOB: 'Account hoặc Group đang có Job khác bị giữ',
  ACCOUNT_NOT_CONNECTED: 'Account chưa có kết nối hợp lệ',
  GROUP_DISABLED: 'Group đã tắt',
  ANONYMOUS_ELIGIBILITY_UNVERIFIED: 'Chưa xác minh quyền đăng ẩn danh cho cặp Account/Group',
  PROXY_UNHEALTHY_OR_STALE: 'Proxy lỗi hoặc kết quả kiểm tra quá 24 giờ',
  PROXY_PIN_MISSING_OR_MISMATCH: 'Thiếu Proxy Pin hoặc IP thay đổi',
  MEDIA_SOURCE_NOT_READY: 'Nguồn ảnh không đủ sẵn sàng',
  PREPARED_MEDIA_INCONSISTENT: 'Ảnh đã chuẩn bị không còn ở trạng thái giữ chỗ',
  HANDOFF_CONFLICT: 'Handoff không nhất quán',
};

export default function CTVPilotTesting({pipelineId}: {pipelineId: string}) {
  const [data, setData] = useState<PilotReadiness | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [filter, setFilter] = useState<'all' | PilotStage>('all');
  const reload = useCallback(() => setRevision((x) => x + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    getPilotReadiness(pipelineId, controller.signal)
      .then((v) => {if (!controller.signal.aborted) {setData(v); setError('');}})
      .catch((e: unknown) => {if (!controller.signal.aborted) {setData(null); setError(e instanceof Error ? e.message : 'Lỗi tải Pilot.');}})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [pipelineId, revision]);
  const rows = useMemo(() => data?.items.filter((v) => filter === 'all' || v.stage === filter) ?? [], [data, filter]);
  const timestamp = data?.checked_at ? new Date(data.checked_at).toLocaleString('vi-VN') : '—';
  return <section className="space-y-4" aria-label="Kiểm thử Pilot ToolNet Fplus24h">
    <header className="flex flex-wrap items-center justify-between gap-2">
      <div><h1 className="text-xl font-bold text-slate-900">Kiểm thử Pilot</h1>
        <p className="mt-1 text-xs text-slate-500">Điều kiện thử đăng thủ công theo Pipeline · cập nhật {timestamp}</p></div>
      <button type="button" onClick={reload} disabled={loading}
        className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs disabled:opacity-50">
        <RefreshCw size={15}/>{loading ? 'Đang kiểm tra...' : 'Kiểm tra lại'}
      </button>
    </header>
    <div className="rounded-md border border-blue-200 bg-blue-50 p-3 text-xs text-blue-900">
      Chỉ kiểm tra điều kiện nội bộ. Không gửi Facebook, không xác minh bài ngoài Facebook và không tạo Job.
      Hãy dùng mục <strong>Đăng bài viết nhóm</strong> để bàn giao thử nghiệm có người thao tác.
    </div>
    {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-800">{error}</p>}
    {data && <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {(Object.keys(titles) as PilotStage[]).map((key) => <div key={key} className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="text-[11px] text-slate-500">{titles[key]}</div>
          <div className="mt-2 text-2xl font-bold tabular-nums text-slate-900">{data.summary[key]?.toLocaleString('vi-VN') ?? '—'}</div>
        </div>)}
      </div>
      <div role="status" className="flex items-start gap-2 rounded-md border border-slate-200 bg-white p-3 text-xs">
        {data.status === 'ready_for_manual_pilot' ? <ClipboardCheck size={17} /> : <ShieldAlert size={17} />}
        <span>{data.truncated ? 'Dữ liệu vượt giới hạn quét: không thể kết luận Pilot sẵn sàng.' :
          data.status === 'ready_for_manual_pilot' ? 'Có Job đáp ứng điều kiện để người dùng thử đăng thủ công.' :
          data.status === 'not_configured' ? 'Pipeline chưa có Job để thử nghiệm.' :
          data.status === 'awaiting_review' ? 'Đang có Job cần đối soát, không tự thử lại.' :
          data.status === 'blocked' ? 'Có Job thiếu điều kiện an toàn.' :
          data.status === 'verified_records_only' ? 'Chỉ có bản ghi được xác minh; chưa kiểm thử lần đăng mới.' :
          'Không có Job đang sẵn sàng để thử đăng.'}</span>
      </div>
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-900">Danh sách Job Pilot</h2>
          <select aria-label="Lọc giai đoạn Pilot" value={filter} onChange={(e) => setFilter(e.target.value as 'all' | PilotStage)}
            className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs">
            <option value="all">Tất cả trạng thái</option>
            {(Object.keys(titles) as PilotStage[]).map((k) => <option value={k} key={k}>{titles[k]}</option>)}
          </select>
        </div>
        <div className="overflow-x-auto"><table className="w-full min-w-[840px] text-left text-xs">
          <thead className="bg-slate-50 text-slate-600"><tr>
            {['Job', 'Account', 'Group', 'Giai đoạn', 'Lưu ý / thiếu điều kiện'].map((s) => <th className="px-3 py-3" key={s}>{s}</th>)}
          </tr></thead>
          <tbody>{rows.map((job) => <tr key={job.job_id} className="border-t border-slate-100 align-top">
            <td className="px-3 py-3 font-mono">{job.job_id.slice(0, 8)}</td>
            <td className="px-3 py-3">{job.account}</td><td className="px-3 py-3">{job.group}</td>
            <td className="px-3 py-3 font-medium">{titles[job.stage] ?? job.stage}</td>
            <td className="px-3 py-3 text-slate-600">{job.blockers.length ? job.blockers.map((c) => codes[c] || c).join(' · ') :
              job.stage === 'awaiting_review' ? 'Chờ đối soát, không tự retry.' : 'Không có cảnh báo trong phạm vi kiểm tra.'}</td>
          </tr>)}</tbody>
        </table>{rows.length === 0 && <p className="p-8 text-center text-xs text-slate-500">Chưa có Job phù hợp.</p>}</div>
      </div>
      <p className="text-[11px] text-slate-500">Đã quét {data.scanned_jobs}/{data.total_jobs} Job. Kiểm tra Pilot không thay thế việc xác minh bài đăng từ nguồn độc lập.</p>
    </>}
  </section>;
}
