"use client";

import { useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, ChevronLeft, ChevronRight, ClipboardCheck, FilePlus2, RefreshCw, X } from "lucide-react";
import type { ReviewJob } from "../api/reconciliation";
import {
  createReviewCase, getReviewCase, listReviewCases, reviewCaseAction,
  type ReviewAction, type ReviewCase, type ReviewList, type ReviewStatus,
} from "../api/review-cases";

const labels: Record<ReviewStatus, string> = {
  open: "Chưa nhận", in_review: "Đang xử lý",
  awaiting_verification: "Chờ xác minh", closed: "Đã đóng",
};
const eventNames: Record<string, string> = {
  opened: "Mở hồ sơ", assigned: "Nhận xử lý", unassigned: "Trả hồ sơ",
  evidence: "Ghi bằng chứng", escalated: "Yêu cầu xác minh", closed: "Đóng hồ sơ",
};
const dt = (value: string | null | undefined) => value ? new Date(value).toLocaleString("vi-VN") : "—";
const errorText = (err: unknown) => err instanceof Error ? err.message : "Không thể thực hiện thao tác.";
const button = "rounded-md border border-slate-200 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40";
const primary = "rounded-md bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-40";

export default function CTVReviewCases({ pipelineId, flaggedJobs }: {
  pipelineId: string; flaggedJobs: ReviewJob[];
}) {
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("all");
  const [revision, setRevision] = useState(0);
  const [listing, setListing] = useState<ReviewList | null>(null);
  const [selected, setSelected] = useState<ReviewCase | null>(null);
  const [jobId, setJobId] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [note, setNote] = useState("");
  const [evidenceUrl, setEvidenceUrl] = useState("");
  const reload = () => setRevision((v) => v + 1);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    listReviewCases(pipelineId, page, filter, controller.signal)
      .then((data) => { if (!controller.signal.aborted) { setListing(data); setError(""); } })
      .catch((cause: unknown) => { if (!controller.signal.aborted) { setError(errorText(cause)); setListing(null); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [pipelineId, page, filter, revision]);

  async function openDetail(id: string) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const data = await getReviewCase(pipelineId, id);
      setSelected(data); setNote(""); setEvidenceUrl("");
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (busy || !jobId) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const data = await createReviewCase(pipelineId, jobId);
      setSelected(data); setJobId(""); setNote(""); setEvidenceUrl("");
      setNotice("Đã mở hồ sơ. Job và trạng thái giữ Account/Group không thay đổi.");
      reload();
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }

  async function act(action: ReviewAction) {
    if (!selected || busy) return;
    if (action === "close" && !window.confirm("Chỉ đóng hồ sơ nếu Job đã có trạng thái cuối hợp lệ. Xác nhận?")) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await reviewCaseAction(pipelineId, selected.id, {
        action, expected_version: selected.version,
        note: action === "add_evidence" ? note : "",
        evidence_url: action === "add_evidence" ? evidenceUrl : "",
      });
      setSelected(updated); setNote(""); setEvidenceUrl("");
      setNotice("Đã ghi lịch sử thao tác. Không thay đổi trạng thái bài đăng Facebook.");
      reload();
    } catch (cause) {
      setError(errorText(cause));
      // optimistic version conflict: user must reload explicitly
    } finally { setBusy(false); }
  }

  return <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><ClipboardCheck size={17} /> Hồ sơ xử lý sự cố</h2>
        <p className="mt-1 text-xs text-slate-500">Ghi bằng chứng và lịch sử xử lý. Không có chức năng tự xác nhận đăng hoặc gỡ giữ.</p>
      </div>
      <button type="button" disabled={loading} onClick={reload} className={button}><RefreshCw size={14} className="inline" /> Làm mới</button>
    </div>
    {notice && <p role="status" className="rounded-lg bg-blue-50 p-3 text-xs text-blue-800">{notice}</p>}
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}</p>}
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => void create(e)}>
      <label className="min-w-[250px] flex-1 space-y-1 text-xs text-slate-700">Job cần đối soát
        <select className="mt-1 w-full rounded-md border px-3 py-2" value={jobId} onChange={(e) => setJobId(e.target.value)} required>
          <option value="">Chọn Job trong danh sách cảnh báo hiện tại</option>
          {flaggedJobs.map((job) => <option key={job.job_id} value={job.job_id}>
            {job.job_id.slice(0, 8)} · {job.group.name} · {job.account.label}
          </option>)}
        </select>
      </label>
      <button type="submit" disabled={busy || !jobId} className={primary}><FilePlus2 size={14} className="inline"/> Mở hồ sơ</button>
    </form>
    <div className="flex flex-wrap gap-2">
      <label className="sr-only" htmlFor="review-case-status">Lọc trạng thái</label>
      <select id="review-case-status" className="rounded border px-3 py-2 text-xs" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }}>
        <option value="all">Tất cả trạng thái</option>
        {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <span className="self-center text-xs text-slate-500">{listing?.pagination.total ?? "—"} hồ sơ</span>
    </div>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] text-xs">
        <thead><tr className="border-b text-left text-slate-500"><th className="p-2">Job</th><th className="p-2">Account / Group</th><th className="p-2">Người phụ trách</th><th className="p-2">Trạng thái</th><th className="p-2">Cập nhật</th><th className="p-2">Chi tiết</th></tr></thead>
        <tbody>
          {listing?.data.map((row) => <tr key={row.id} className="border-b border-slate-100">
            <td className="p-2 font-mono">{row.job_id.slice(0, 8)}</td>
            <td className="p-2">{row.account.label}<p className="text-slate-500">{row.group.name}</p></td>
            <td className="p-2">{row.assigned_to ?? "Chưa giao"}</td>
            <td className="p-2">{labels[row.status]}{row.held && <p className="text-amber-700">Còn giữ</p>}</td>
            <td className="p-2">{dt(row.updated_at)}</td>
            <td className="p-2"><button type="button" className={button} disabled={busy} onClick={() => void openDetail(row.id)}>Xem</button></td>
          </tr>)}
          {!loading && !listing?.data.length && <tr><td colSpan={6} className="p-5 text-center text-slate-500">Chưa có hồ sơ phù hợp.</td></tr>}
        </tbody>
      </table>
    </div>
    <div className="flex items-center justify-between text-xs text-slate-500">
      <span>Trang {listing?.pagination.page ?? page}/{listing?.pagination.total_pages ?? "—"}</span>
      <div className="flex gap-2">
        <button type="button" aria-label="Trang trước" className={button} disabled={!listing?.pagination.has_previous || loading} onClick={() => setPage(Math.max(1, page - 1))}><ChevronLeft size={14}/></button>
        <button type="button" aria-label="Trang sau" className={button} disabled={!listing?.pagination.has_next || loading} onClick={() => setPage(page + 1)}><ChevronRight size={14}/></button>
      </div>
    </div>

    {selected && <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-3">
      <div role="dialog" aria-modal="true" aria-label="Chi tiết hồ sơ đối soát" className="max-h-[90dvh] w-full max-w-2xl space-y-4 overflow-y-auto rounded-xl bg-white p-5 shadow-xl">
        <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">Hồ sơ {selected.id.slice(0, 8)}</h3><button type="button" aria-label="Đóng" onClick={() => setSelected(null)}><X size={18}/></button></div>
        <div className="grid gap-2 rounded-lg bg-slate-50 p-3 text-xs sm:grid-cols-2">
          <span>Job: <b className="font-mono">{selected.job_id.slice(0, 8)}</b></span>
          <span>Trạng thái Job: <b>{selected.job_state}</b></span>
          <span>Account: <b>{selected.account.label}</b></span>
          <span>Group: <b>{selected.group.name}</b></span>
          <span>Hồ sơ: <b>{labels[selected.status]}</b></span>
          <span>Người phụ trách: <b>{selected.assigned_to ?? "Chưa nhận"}</b></span>
          <span>Phiên bản: <b>{selected.version}</b></span>
          <span>Đang giữ: <b>{selected.held ? "Có" : "Không"}</b></span>
        </div>
        <p className="flex items-center gap-2 text-xs text-amber-800"><AlertTriangle size={16}/> Ghi bằng chứng không đồng nghĩa xác nhận bài đăng. Hồ sơ không thể tự bỏ giữ Account/Group.</p>
        {selected.status !== "closed" && <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {!selected.assigned_to && <button type="button" disabled={busy} className={primary} onClick={() => void act("assign_me")}>Nhận hồ sơ</button>}
            {selected.assigned_to && <button type="button" disabled={busy} className={button} onClick={() => void act("unassign")}>Trả hồ sơ</button>}
            {selected.assigned_to && <button type="button" disabled={busy} className={button} onClick={() => void act("request_verification")}>Yêu cầu xác minh</button>}
            {selected.can_close && selected.assigned_to && <button type="button" disabled={busy} className={button} onClick={() => void act("close")}>Đóng hồ sơ</button>}
          </div>
          <label className="block space-y-1 text-xs">Mô tả bằng chứng (tối thiểu 10 ký tự)
            <textarea className="w-full rounded-lg border p-2" rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ghi rõ thời điểm, kết quả kiểm tra và nguồn chứng cứ"/>
          </label>
          <label className="block space-y-1 text-xs">Liên kết bài Facebook (không bắt buộc)
            <input className="w-full rounded-lg border p-2" type="url" value={evidenceUrl} onChange={(e) => setEvidenceUrl(e.target.value)} placeholder="https://www.facebook.com/..." />
          </label>
          <button type="button" disabled={busy || note.trim().length < 10 || !selected.assigned_to} className={primary} onClick={() => void act("add_evidence")}>Lưu bằng chứng vào lịch sử</button>
        </div>}
        <div><h4 className="mb-2 text-sm font-semibold">Lịch sử sự kiện ({selected.event_count ?? 0})</h4>
          <div className="max-h-[300px] space-y-2 overflow-y-auto">
            {selected.events?.map((event) => <div key={event.id} className="rounded-lg border p-3 text-xs">
              <p><b>{eventNames[event.kind] ?? event.kind}</b> · {event.actor} · {dt(event.created_at)}</p>
              {event.note && <p className="mt-1 whitespace-pre-wrap break-words text-slate-600">{event.note}</p>}
              {event.evidence_url && <a href={event.evidence_url} target="_blank" rel="noopener noreferrer" className="mt-1 block break-all text-blue-700 underline">Mở liên kết Facebook</a>}
              <p className="mt-1 text-slate-500">Job tại thời điểm ghi: {event.job_state_snapshot}</p>
            </div>)}
          </div>
          {selected.events_truncated && <p className="text-xs text-amber-700">Chỉ hiển thị 500 sự kiện đầu tiên. Nhật ký gốc vẫn lưu trong Neon.</p>}
        </div>
        <div className="flex justify-end gap-2"><button type="button" className={button} disabled={busy} onClick={() => void openDetail(selected.id)}>Tải lại phiên bản</button><button type="button" className={button} onClick={() => setSelected(null)}>Đóng</button></div>
        {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
      </div>
    </div>}
  </section>;
}
