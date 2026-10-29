"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ChevronLeft, ChevronRight, RefreshCw, ShieldAlert } from "lucide-react";
import {
  getJobVerification, recordJobObservation, type JobVerification,
  type ObservationSource, type ObservationOutcome, type NewObservation,
} from "../api/post-verification";

const outcomes: { value: ObservationOutcome; label: string }[] = [
  { value: "submitted", label: "Facebook đã nhận thao tác gửi (chưa xác minh hiển thị)" },
  { value: "pending_moderation", label: "Đang chờ quản trị viên Group duyệt" },
  { value: "visible_reported", label: "Có báo cáo bài đã hiển thị (chưa xác minh độc lập)" },
  { value: "rejected_reported", label: "Có báo cáo bị từ chối (chưa xác minh độc lập)" },
  { value: "inconclusive", label: "Chưa đủ dữ liệu kết luận" },
];
const sourceName: Record<ObservationSource, string> = {
  manual_review: "Kiểm tra thủ công", sanitized_har: "Tóm tắt HAR đã xóa thông tin phiên",
};
const label = (value: ObservationOutcome) => outcomes.find((row) => row.value === value)?.label ?? value;
const message = (value: unknown) => value instanceof Error ? value.message : "Không thể xử lý yêu cầu.";
const btn = "rounded-md border border-slate-200 px-3 py-2 text-xs disabled:opacity-40";
const input = "w-full rounded-lg border border-slate-200 px-3 py-2 text-xs";

export default function CTVPostVerification({ pipelineId, jobId }: {
  pipelineId: string; jobId: string;
}) {
  const [data, setData] = useState<JobVerification | null>(null);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [source, setSource] = useState<ObservationSource>("manual_review");
  const [outcome, setOutcome] = useState<ObservationOutcome>("pending_moderation");
  const [note, setNote] = useState("");
  const [evidenceUrl, setEvidenceUrl] = useState("");
  const [requestKey, setRequestKey] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    getJobVerification(pipelineId, jobId, page, controller.signal)
      .then((value) => { if (!controller.signal.aborted) { setData(value); setError(""); } })
      .catch((cause: unknown) => { if (!controller.signal.aborted) { setData(null); setError(message(cause)); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [pipelineId, jobId, page, revision]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working || note.trim().length < 10) return;
    const idempotency_key = requestKey || crypto.randomUUID();
    setRequestKey(idempotency_key);
    setWorking(true); setError(""); setNotice("");
    try {
      const payload: NewObservation = { idempotency_key, source, outcome, note: note.trim(), evidence_url: evidenceUrl.trim() };
      await recordJobObservation(pipelineId, jobId, payload);
      setRequestKey(""); setNote(""); setEvidenceUrl("");
      setNotice("Đã ghi nhận quan sát. Job chưa được xác minh xuất bản và không được tự thử lại.");
      setPage(1); setRevision((value) => value + 1);
    } catch (cause) { setError(message(cause)); }
    finally { setWorking(false); }
  }

  return <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-3" aria-label="Quan sát tình trạng bài viết">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="text-sm font-semibold text-slate-900">Quan sát Facebook / chờ duyệt</h4>
      <button type="button" className={btn} disabled={loading} onClick={() => setRevision((value) => value + 1)}>
        <RefreshCw size={13} className="inline"/> Làm mới
      </button>
    </div>
    <div className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
      <ShieldAlert size={16} className="shrink-0"/>
      <p>HTTP 200, Story ID, HAR hoặc lời xác nhận thủ công không chứng minh bài đã hiển thị. Chỉ bộ đọc lại được cấp phép phía server mới được xác nhận published.</p>
    </div>
    <div className="grid gap-2 text-xs sm:grid-cols-2">
      <p>Job hiện tại: <b>{data?.job_state ?? "—"}</b></p>
      <p>Đã xác minh hiển thị: <b>{data?.verified_published ? "Có" : "Chưa"}</b></p>
      <p>Quan sát gần nhất: <b>{data?.most_recent_observation ? label(data.most_recent_observation) : "Chưa có"}</b></p>
      <p>Bộ xác minh độc lập: <b>{data?.facebook_readback_configured ? "Đã cấu hình adapter" : "Chưa cấu hình"}</b></p>
    </div>
    <form onSubmit={(event) => void submit(event)} className="space-y-2 border-t border-slate-100 pt-3">
      <p className="text-xs font-semibold">Ghi nhận quan sát (không đổi trạng thái Job)</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block space-y-1 text-xs">Nguồn quan sát
          <select className={input} value={source} onChange={(event) => { setSource(event.target.value as ObservationSource); setRequestKey(""); }}>
            <option value="manual_review">Kiểm tra thủ công</option>
            <option value="sanitized_har">Tóm tắt HAR đã làm sạch</option>
          </select>
        </label>
        <label className="block space-y-1 text-xs">Kết quả nhìn thấy
          <select className={input} value={outcome} onChange={(event) => { setOutcome(event.target.value as ObservationOutcome); setRequestKey(""); }}>
            {outcomes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
      </div>
      <label className="block space-y-1 text-xs">Mô tả bằng chứng (không dán HAR thô hoặc token)
        <textarea className={input} rows={3} minLength={10} maxLength={1000} required value={note} onChange={(event) => { setNote(event.target.value); setRequestKey(""); }} placeholder="Ví dụ: Facebook xác nhận gửi bài ẩn danh và thông báo chờ quản trị viên phê duyệt."/>
      </label>
      <label className="block space-y-1 text-xs">Liên kết Facebook (nếu có; không có dấu ? hoặc #)
        <input className={input} type="url" maxLength={800} value={evidenceUrl} onChange={(event) => { setEvidenceUrl(event.target.value); setRequestKey(""); }} placeholder="https://www.facebook.com/groups/..."/>
      </label>
      <button className="rounded-md bg-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40" type="submit" disabled={working || note.trim().length < 10}>
        {working ? "Đang ghi..." : "Lưu quan sát"}
      </button>
    </form>
    {notice && <p role="status" className="text-xs text-blue-700">{notice}</p>}
    {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    <div className="space-y-2 border-t border-slate-100 pt-3">
      <h5 className="text-xs font-semibold">Lịch sử quan sát ({data?.pagination.total ?? "—"})</h5>
      {data?.observations.map((row) => <div key={row.id} className="rounded-md border border-slate-100 p-2 text-xs">
        <p className="font-medium">{label(row.outcome)}</p>
        <p className="mt-1 text-slate-500">{sourceName[row.source]} · {row.actor} · {new Date(row.recorded_at).toLocaleString("vi-VN")}</p>
        <p className="mt-1 whitespace-pre-wrap break-words">{row.note}</p>
        {row.evidence_url && <a href={row.evidence_url} target="_blank" rel="noopener noreferrer" className="mt-1 block break-all text-blue-700 underline">Mở bằng chứng</a>}
      </div>)}
      {!loading && data?.observations.length === 0 && <p className="text-xs text-slate-500">Chưa có quan sát nào.</p>}
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>Trang {data?.pagination.page ?? page}/{data?.pagination.total_pages ?? "—"}</span>
        <div className="flex gap-2">
          <button type="button" aria-label="Trang trước" className={btn} disabled={!data?.pagination.has_previous || loading} onClick={() => setPage((v) => Math.max(1,v-1))}><ChevronLeft size={14}/></button>
          <button type="button" aria-label="Trang sau" className={btn} disabled={!data?.pagination.has_next || loading} onClick={() => setPage((v) => v+1)}><ChevronRight size={14}/></button>
        </div>
      </div>
    </div>
  </section>;
}
