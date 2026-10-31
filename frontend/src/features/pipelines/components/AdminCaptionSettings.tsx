'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { LockKeyhole, Save } from 'lucide-react';
import { captionAPI, type CaptionConfig } from '@/features/ctv/api/caption-engine';

const input = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800';
const defaults: CaptionConfig = { destination: '', enabled: false, auto_generate: false,
  auto_approve: false, writing_guidance: '', version: 0 };

export default function AdminCaptionSettings({ pipelineId }: { pipelineId: string }) {
  const [form, setForm] = useState<CaptionConfig>(defaults);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let live = true;
    void captionAPI.settings(pipelineId).then(value => { if (live) setForm(value); })
      .catch((err: unknown) => { if (live) setError(err instanceof Error ? err.message : 'Lỗi tải cấu hình'); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [pipelineId]);

  async function save() {
    if (busy) return;
    if (!/^@[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$/.test(form.destination.trim()) || form.destination.trim().length > 33 || form.destination.trim().length < 3) {
      setError('Trang đích phải có dạng @hiu9h.'); return;
    }
    if (!window.confirm(`Lưu khóa trang đích ${form.destination}? Thay đổi có thể bị chặn nếu còn Job chưa hoàn tất.`)) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const updated = await captionAPI.saveSettings(pipelineId, form);
      setForm(updated);
      setNotice('Đã lưu và ghi nhật ký thay đổi cấu hình.');
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Không lưu được cấu hình.'); }
    finally { setBusy(false); }
  }

  return <div className="mx-auto max-w-2xl space-y-5 p-4 sm:p-6">
    <div><Link href="/pipelines/" className="text-sm text-blue-600">← Quản lý CTV</Link>
      <h1 className="mt-3 text-xl font-bold text-slate-900">Khóa trang đích & AI Caption</h1>
      <p className="mt-1 text-sm text-slate-500">ToolNet Fplus24h · Chỉ Admin được thay đổi trang đích.</p></div>
    {loading && <p className="text-sm text-slate-500">Đang tải cấu hình...</p>}
    {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
    {notice && <div role="status" className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">{notice}</div>}
    <div className="space-y-5 rounded-xl border border-slate-200 bg-white p-5">
      <div><label htmlFor="caption-destination" className="mb-2 block text-sm font-medium">Trang đích cố định</label>
        <div className="relative"><LockKeyhole size={17} className="absolute left-3 top-3 text-slate-400"/>
        <input id="caption-destination" className={`${input} pl-10`} maxLength={64}
          value={form.destination} placeholder="@hiu9h" disabled={loading || busy}
          onChange={e=>setForm(old=>({...old, destination:e.target.value}))}/></div>
        <p className="mt-2 text-xs text-slate-500">Mỗi CTV chỉ được khóa một @username. Không cho đổi khi còn Job chưa hoàn tất.</p></div>
      <label className="flex items-center gap-3 text-sm"><input type="checkbox" checked={form.enabled}
        disabled={loading || busy} onChange={e=>setForm(old=>({...old,enabled:e.target.checked}))}/>
        Bật AI Caption và yêu cầu caption đã duyệt</label>
      <label className="flex items-center gap-3 text-sm"><input type="checkbox" checked={form.auto_generate}
        disabled={loading || busy} onChange={e=>setForm(old=>({...old,auto_generate:e.target.checked}))}/>
        Tự tạo caption cho Job mới qua Caption Tick</label>
      <label className="flex items-center gap-3 text-sm"><input type="checkbox" checked={form.auto_approve}
        disabled={loading || busy} onChange={e=>setForm(old=>({...old,auto_approve:e.target.checked}))}/>
        Tự duyệt caption hợp lệ (không cần CTV bấm duyệt)</label>
      <div><label htmlFor="caption-guide" className="mb-2 block text-sm font-medium">Hướng dẫn văn phong</label>
        <textarea id="caption-guide" className={input} rows={4} maxLength={2000}
          disabled={loading || busy} value={form.writing_guidance}
          onChange={e=>setForm(old=>({...old,writing_guidance:e.target.value}))}
          placeholder="Ví dụ: viết thân thiện, ngắn gọn, không lặp nguyên mẫu..."/></div>
      <button disabled={loading || busy} onClick={()=>void save()}
        className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50">
        <Save size={16}/>{busy?'Đang lưu...':'Lưu cấu hình'}</button>
    </div>
  </div>;
}
