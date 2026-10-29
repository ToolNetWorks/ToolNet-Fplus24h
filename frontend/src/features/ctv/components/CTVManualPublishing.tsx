"use client";

import { useEffect, useState } from 'react';
import { Copy, ExternalLink, RefreshCw } from 'lucide-react';
import { getCsrfToken } from '@/features/auth/api/auth-client';
import { listPublishingJobs, type PublishingJob } from '../api/publishing-jobs';
import {
  manualAction, readManualHandoff, manualMediaUrl,
  type ManualHandoff, type ReportedOutcome,
} from '../api/manual-handoff';

const stages: Record<string, string> = {
  prepared: 'Đã chuẩn bị', opened: 'Đã mở Facebook',
  submitted_reported: 'CTV báo đã gửi', pending_reported: 'CTV báo chờ duyệt',
  rejected_reported: 'CTV báo bị từ chối', inconclusive: 'Không rõ kết quả',
  abandoned: 'Đã hủy trước khi mở',
};
const outcomes: [ReportedOutcome, string][] = [
  ['submitted_reported', 'Đã nhấn gửi bài'],
  ['pending_reported', 'Bài đang chờ Group duyệt'],
  ['rejected_reported', 'Group từ chối bài'],
  ['inconclusive', 'Chưa xác định được kết quả'],
];
const baseButton = 'rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 disabled:opacity-40';

export default function CTVManualPublishing({ pipelineId }: { pipelineId: string }) {
  const [jobs, setJobs] = useState<PublishingJob[]>([]);
  const [jobId, setJobId] = useState('');
  const [lookupId, setLookupId] = useState('');
  const [record, setRecord] = useState<ManualHandoff | null>(null);
  const [canPrepare, setCanPrepare] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [outcome, setOutcome] = useState<ReportedOutcome>('pending_reported');
  const [note, setNote] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    listPublishingJobs(pipelineId, { page: 1, pageSize: 50, state: 'all', search: '' }, controller.signal)
      .then((rows) => { if (!controller.signal.aborted) setJobs(rows.data); })
      .catch((e: unknown) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Không tải được Job.'); });
    return () => controller.abort();
  }, [pipelineId, revision]);

  useEffect(() => {
    if (!jobId) { setRecord(null); setCanPrepare(false); return; }
    const controller = new AbortController();
    readManualHandoff(pipelineId, jobId, controller.signal)
      .then((res) => { if (!controller.signal.aborted) { setRecord(res.handoff); setCanPrepare(res.can_prepare); setError(''); } })
      .catch((e: unknown) => { if (!controller.signal.aborted) { setRecord(null); setCanPrepare(false); setError(e instanceof Error ? e.message : 'Không đọc được bàn giao.'); } });
    return () => controller.abort();
  }, [pipelineId, jobId, revision]);

  async function action(value: 'prepare' | 'open' | 'abandon' | 'report') {
    if (!jobId || pending) return;
    if (value === 'open' && !window.confirm('Xác nhận mở Facebook để tự đăng? Job sẽ được giữ ở trạng thái chưa xác minh, không được tự retry.')) return;
    if (value === 'abandon' && !window.confirm('Chỉ hủy nếu CHƯA mở Facebook/chưa thực hiện đăng. Hủy Job này?')) return;
    // Open a blank tab synchronously (popup blockers often reject async open).
    // Never navigate to Facebook until the server has recorded the safety boundary.
    const popup = value === 'open' ? window.open('about:blank', '_blank') : null;
    if (popup) popup.opener = null;
    setPending(true); setError(''); setNotice('');
    try {
      const csrf = await getCsrfToken();
      const data = value === 'prepare'
        ? await manualAction(pipelineId, jobId, { action: 'prepare' }, csrf)
        : value === 'report'
          ? await manualAction(pipelineId, jobId, { action: 'report', expected_version: record!.version, outcome, note }, csrf)
          : await manualAction(pipelineId, jobId, { action: value, expected_version: record!.version }, csrf);
      setRecord(data); setCanPrepare(false); setNotice('Đã lưu thao tác. Không xác nhận bài được xuất bản.');
      if (value === 'open') {
        if (popup && !popup.closed) {
          popup.location.replace(data.group_url);
        } else {
          setNotice('Đã ghi mốc bắt đầu. Trình duyệt chặn tab mới: mở Group bằng liên kết bên dưới.');
        }
      }
      setRevision((v) => v + 1);
    } catch (e) {
      if (popup && !popup.closed) popup.close();
      setError(e instanceof Error ? e.message : 'Không xử lý được.');
    } finally {
      setPending(false);
    }
  }

  async function copyCaption() {
    if (!record) return;
    try { await navigator.clipboard.writeText(record.caption); setNotice('Đã sao chép caption.'); }
    catch { setError('Không có quyền sao chép; hãy chọn và sao chép thủ công.'); }
  }

  return <section className="space-y-4" aria-label="Đăng bài nhóm thủ công">
    <div>
      <h1 className="text-xl font-bold text-slate-900">Đăng bài viết nhóm</h1>
      <p className="mt-1 text-xs text-slate-500">ToolNet Fplus24h chuẩn bị ảnh và caption. Bạn đăng trực tiếp trên Facebook, không qua API nội bộ.</p>
    </div>
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
      Facebook Groups API đăng bài đã ngừng hoạt động. Chỉ chọn Account và Group được phép đăng; tự kiểm tra đúng Proxy/IP của Account trong trình duyệt. Báo “đã gửi” hoặc “chờ duyệt” không đồng nghĩa bài đã được xuất bản. Sau khi mở Facebook, Job và ảnh tiếp tục bị giữ để đối soát.
    </div>
    {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">{notice}</p>}
    <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex-1 min-w-[220px] space-y-1 text-xs text-slate-700">Chọn Job (50 bản ghi gần nhất)
          <select value={jobId} onChange={(e) => { setJobId(e.target.value); setNote(''); }}
            className="mt-1 w-full rounded-md border border-slate-200 bg-white px-3 py-2">
            <option value="">Chọn Job để chuẩn bị nội dung</option>
            {jobs.map((job) => <option key={job.id} value={job.id}>{job.id.slice(0, 8)} · {job.group.name} · {job.account.label} · {job.state}</option>)}
          </select>
        </label>
        <button type="button" className={baseButton} onClick={() => setRevision((v) => v + 1)}><RefreshCw size={14} className="inline" /> Làm mới</button>
      </div>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (/^[a-fA-F0-9-]{36}$/.test(lookupId.trim())) setJobId(lookupId.trim()); else setError('Mã Job UUID không hợp lệ.'); }}>
        <input value={lookupId} onChange={(e) => setLookupId(e.target.value)} placeholder="Hoặc nhập Job UUID để mở bản ghi cũ"
          className="min-w-[220px] flex-1 rounded-md border border-slate-200 px-3 py-2 text-xs" />
        <button type="submit" className={baseButton}>Mở theo UUID</button>
      </form>
      {jobId && !record && <button type="button" disabled={pending || !canPrepare} onClick={() => void action('prepare')}
        className="rounded-md bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-40">Chuẩn bị caption và giữ ảnh</button>}
      {jobId && !record && !canPrepare && <p className="text-xs text-slate-500">Job chưa đủ điều kiện hoặc đã có thao tác. Kiểm tra trạng thái Job và quyền đăng ẩn danh tại Group.</p>}
    </div>
    {record && <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap justify-between gap-2"><h2 className="text-sm font-semibold">Phiếu bàn giao đăng bài</h2>
        <span className="text-xs text-slate-600">{stages[record.state] ?? record.state} · Job {record.job_state}</span></div>
      <dl className="grid gap-2 text-xs sm:grid-cols-2">
        <div><dt className="text-slate-500">Account được chỉ định</dt><dd className="font-semibold">{record.account_label}</dd></div>
        <div><dt className="text-slate-500">Group đích</dt><dd className="font-semibold">{record.group_name}</dd></div>
      </dl>
      <div className="space-y-2"><div className="flex justify-between"><strong className="text-xs">Caption</strong><button type="button" className={baseButton} onClick={() => void copyCaption()}><Copy size={13} className="inline"/> Sao chép</button></div>
        <textarea value={record.caption} readOnly rows={5} className="w-full rounded-md border border-slate-200 p-3 text-xs" /></div>
      <div><strong className="text-xs">Ảnh đã giữ từ Album nguồn</strong>
        <div className="mt-2 flex flex-wrap gap-2">{record.media.map((item) => <a
          key={item.image_id} href={manualMediaUrl(pipelineId, item)} target="_blank" rel="noopener noreferrer"
          className="rounded-md border border-slate-200 px-3 py-2 text-xs text-blue-700">
          Ảnh {item.position} {item.available ? '· Xem / lưu' : '· Không còn khả dụng'}
        </a>)}</div>
      </div>
      {record.state === 'prepared' && <div className="flex flex-wrap gap-2">
        <button type="button" disabled={pending} onClick={() => void action('open')}
          className="rounded-md bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-40"><ExternalLink size={13} className="inline"/> Mở Facebook để đăng thủ công</button>
        <button type="button" disabled={pending} onClick={() => void action('abandon')} className={baseButton}>Hủy trước khi mở</button>
      </div>}
      {record.state !== 'prepared' && record.state !== 'abandoned' && <p className="text-xs">
        <a href={record.group_url} target="_blank" rel="noopener noreferrer" className="text-blue-700 underline">Mở lại Group trên Facebook (không gửi lại bài tự động)</a>
      </p>}
      {record.state !== 'prepared' && record.state !== 'abandoned' && <div className="space-y-2 rounded-lg bg-slate-50 p-3">
        <p className="text-xs">Sau khi thao tác trên Facebook, ghi lại quan sát. Không điền cookie, HAR hoặc token.</p>
        <select value={outcome} onChange={(e) => setOutcome(e.target.value as ReportedOutcome)} className="w-full rounded-md border p-2 text-xs">
          {outcomes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <textarea value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} rows={2}
          placeholder="Ghi chú đã làm sạch, tối đa 500 ký tự" className="w-full rounded-md border p-2 text-xs" />
        <button type="button" disabled={pending} onClick={() => void action('report')} className="rounded-md bg-blue-600 px-4 py-2 text-xs text-white disabled:opacity-40">Lưu quan sát</button>
      </div>}
      <div className="text-xs text-slate-500">Lịch sử ({record.events.length}{record.events_truncated ? '+' : ''})
        <div className="mt-2 max-h-40 overflow-auto space-y-1">{record.events.map((event) => <p key={event.id}>
          {new Date(event.recorded_at).toLocaleString('vi-VN')} · {event.kind} {event.outcome || ''}
        </p>)}</div>
      </div>
    </div>}
  </section>;
}
