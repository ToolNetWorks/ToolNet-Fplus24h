'use client';
import { useEffect, useState } from 'react';
import { Plus, RefreshCw, Sparkles, Trash2, CheckCircle2, XCircle } from 'lucide-react';
import { captionAPI, type CaptionConfig, type CaptionSample, type CaptionJob } from '../api/caption-engine';

const field = 'w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-800 bg-white outline-none focus:border-blue-500';
const action = 'inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium hover:bg-slate-50 disabled:opacity-50';
const errorText = (e: unknown) => e instanceof Error ? e.message : 'Yêu cầu thất bại.';

export default function CTVCaptionEngine({ pipelineId }: { pipelineId: string }) {
  const [config, setConfig] = useState<CaptionConfig | null>(null);
  const [samples, setSamples] = useState<CaptionSample[]>([]);
  const [totalSamples, setTotalSamples] = useState(0);
  const [jobs, setJobs] = useState<CaptionJob[]>([]);
  const [sampleText, setSampleText] = useState('');
  const [sampleEditId, setSampleEditId] = useState('');
  const [sampleEditText, setSampleEditText] = useState('');
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [page, setPage] = useState(1);

  async function load(pageNum = page) {
    setLoading(true);
    try {
      const [c, s, j] = await Promise.all([
        captionAPI.settings(pipelineId), captionAPI.samples(pipelineId, pageNum),
        captionAPI.jobs(pipelineId),
      ]);
      setConfig(c); setSamples(s.items); setTotalSamples(s.total); setJobs(j.items);
      setPage(pageNum);
      setEditing(Object.fromEntries(j.items.map(job =>
        [job.job_id, job.caption?.text ?? ''])));
      setError('');
    } catch (e: unknown) { setError(errorText(e)); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    setConfig(null); setSamples([]); setJobs([]); setEditing({});
    void load(1);
    // Reload on tenant change, not every input keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipelineId]);

  async function run(fn: () => Promise<unknown>, message: string) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await fn(); setNotice(message); await load(); }
    catch (e: unknown) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  async function createSample() {
    const value = sampleText.trim();
    if (value.length < 8 || value.length > 1500) {
      setError('Caption mẫu phải có 8–1500 ký tự.'); return;
    }
    await run(() => captionAPI.addSample(pipelineId, value), 'Đã thêm caption mẫu.');
    setSampleText('');
  }

  return <section className="space-y-5" aria-label="AI viết caption ToolNet Fplus24h">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="text-xl font-semibold text-slate-900">AI viết Caption</h1>
        <p className="mt-1 text-sm text-slate-500">Kho mẫu riêng theo Pipeline · AI viết caption mới cho từng Job</p></div>
      <button className={action} onClick={() => void load()} disabled={loading || busy}><RefreshCw size={15} /> Làm mới</button>
    </div>
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">{notice}</p>}
    {loading && <p className="text-sm text-slate-500">Đang tải dữ liệu...</p>}
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="font-semibold text-slate-900">Trang đích cố định</h2>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span className="rounded-md bg-slate-100 px-3 py-2 font-mono text-base font-semibold text-slate-800">{config?.destination || 'Chưa cấu hình'}</span>
        <span className="text-xs text-slate-500">{config?.enabled ? 'Đã bật khóa · CTV không thể thay đổi' : 'Admin chưa bật AI Caption'}</span>
      </div>
      <p className="mt-2 text-xs text-slate-500">Admin cấu hình trang đích trong menu Thao tác của Pipeline. Backend kiểm tra đúng @username trước khi duyệt.</p>
    </div>
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
      <div className="flex items-center justify-between"><h2 className="font-semibold text-slate-900">Kho caption mẫu</h2>
        <span className="text-sm text-slate-500">{totalSamples} mẫu</span></div>
      <textarea className={field} rows={3} value={sampleText} maxLength={1500}
        onChange={(e) => setSampleText(e.target.value)} placeholder="Dán caption mẫu để AI học văn phong, độ dài và cách xưng hô..." />
      <button className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        disabled={busy} onClick={() => void createSample()}><Plus size={16}/> Thêm mẫu</button>
      <div className="divide-y divide-slate-100">
        {samples.map(sample => <div className="space-y-2 py-3" key={sample.id}>
          {sampleEditId === sample.id ? <textarea className={field} rows={3} maxLength={1500}
            value={sampleEditText} onChange={e => setSampleEditText(e.target.value)} /> :
            <p className={`whitespace-pre-wrap break-words text-sm ${sample.is_active ? 'text-slate-700' : 'text-slate-400'}`}>{sample.text}</p>}
          <div className="flex flex-wrap items-center gap-2">
            {sampleEditId === sample.id ? <>
              <button className={action} disabled={busy || sampleEditText.trim().length < 8} onClick={() => void run(
                () => captionAPI.updateSample(pipelineId, sample.id, { text: sampleEditText.trim() }), 'Đã sửa mẫu.').then(() => setSampleEditId(''))}>Lưu</button>
              <button className={action} onClick={() => setSampleEditId('')}>Hủy</button>
            </> : <button className={action} disabled={busy} onClick={() => {
              setSampleEditId(sample.id); setSampleEditText(sample.text);
            }}>Sửa mẫu</button>}
            <button className={action} disabled={busy} onClick={() => void run(
              () => captionAPI.updateSample(pipelineId, sample.id, { is_active: !sample.is_active }),
              sample.is_active ? 'Đã ẩn mẫu khỏi AI.' : 'Đã bật mẫu.')}>{sample.is_active ? 'Ẩn mẫu' : 'Bật mẫu'}</button>
            <button className={action} disabled={busy} aria-label="Xóa caption mẫu" onClick={() => {
              if (!window.confirm('Xóa caption mẫu này?')) return;
              void run(() => captionAPI.deleteSample(pipelineId, sample.id), 'Đã xóa mẫu.');
            }}><Trash2 size={15} /></button>
          </div>
        </div>)}
        {samples.length === 0 && !loading && <p className="py-5 text-sm text-slate-500">Kho chưa có caption mẫu.</p>}
      </div>
      <div className="flex items-center gap-3">
        <button className={action} disabled={page <= 1 || loading} onClick={() => void load(page - 1)}>Trang trước</button>
        <span className="text-xs text-slate-500">Trang {page}</span>
        <button className={action} disabled={page * 30 >= totalSamples || loading} onClick={() => void load(page + 1)}>Trang tiếp</button>
      </div>
    </div>
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="font-semibold text-slate-900">Caption theo từng Job</h2>
      <p className="mt-1 text-xs text-slate-500">Tự tạo được thực hiện bằng Caption Tick khi Admin bật. Chỉ caption đã duyệt mới được sử dụng.</p>
      <div className="mt-4 space-y-4">
        {jobs.map(job => <div key={job.job_id} className="space-y-3 rounded-lg border border-slate-200 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div><strong className="block text-sm text-slate-800">{job.group}</strong>
              <span className="text-xs text-slate-500">Job {job.job_id.slice(0, 8)} · {job.job_state}</span></div>
            <span className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600">{job.caption?.state ?? 'Chưa tạo AI'}</span>
          </div>
          {job.caption && <textarea className={field} rows={3} maxLength={5000} aria-label="Chỉnh sửa caption Job"
            value={editing[job.job_id] ?? job.caption.text}
            disabled={job.job_state !== 'queued' || busy}
            onChange={(e) => setEditing(prev => ({ ...prev, [job.job_id]: e.target.value }))}/>}
          <div className="flex flex-wrap items-center gap-2">
            <button className={action} disabled={busy || !config?.enabled || job.job_state !== 'queued'}
              onClick={() => void run(() => captionAPI.jobAction(pipelineId, job.job_id, { action: 'generate' }), 'AI đã tạo bản caption mới.')}
              ><Sparkles size={15}/> {job.caption ? 'Tạo lại' : 'AI tạo caption'}</button>
            {job.caption && (job.caption.state === 'draft' || job.caption.state === 'approved') && <button className={action}
              disabled={busy || job.job_state !== 'queued'}
              onClick={() => void run(() => captionAPI.jobAction(pipelineId, job.job_id,
                { action: 'approve', revision: job.caption!.revision,
                  text: editing[job.job_id] ?? job.caption!.text }), 'Đã duyệt caption cho Job.')}
              ><CheckCircle2 size={15}/> Duyệt</button>}
            {job.caption && job.caption.state === 'draft' && <button className={action}
              disabled={busy || job.job_state !== 'queued'}
              onClick={() => void run(() => captionAPI.jobAction(pipelineId, job.job_id,
                { action: 'reject', revision: job.caption!.revision }), 'Đã từ chối bản caption.')}
              ><XCircle size={15}/> Từ chối</button>}
          </div>
        </div>)}
        {jobs.length === 0 && !loading && <p className="text-sm text-slate-500">Pipeline chưa có Job. Tạo Job từ Lịch đăng bài để sinh caption riêng.</p>}
      </div>
    </div>
  </section>;
}
