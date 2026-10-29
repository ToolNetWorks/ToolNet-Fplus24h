"use client";

import { useEffect, useState } from "react";
import { RefreshCw, ShieldCheck, AlertTriangle } from "lucide-react";
import { getReadbackStatus, type ReadbackStatus, type ReadbackOutcome } from "../api/readback";

const outcomeLabels: Record<ReadbackOutcome, string> = {
  pending: "Đang chờ duyệt", rejected: "Có tín hiệu bị từ chối (cần đối soát)",
  inconclusive: "Không đủ dữ liệu", mismatch: "Mã bài/Group không khớp",
  verified: "Đã xác minh hiển thị bằng nguồn độc lập",
};
const fmt = (value: string) => new Date(value).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });

export default function CTVReadbackStatus({ pipelineId, jobId }: { pipelineId: string; jobId: string }) {
  const [status, setStatus] = useState<ReadbackStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    getReadbackStatus(pipelineId, jobId, controller.signal)
      .then((value) => { if (!controller.signal.aborted) { setStatus(value); setError(""); } })
      .catch((cause: unknown) => { if (!controller.signal.aborted) { setStatus(null); setError(cause instanceof Error ? cause.message : "Lỗi tải dữ liệu."); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [pipelineId, jobId, revision]);

  return <section className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3" aria-label="Đối chiếu độc lập">
    <div className="flex items-center justify-between gap-2">
      <h4 className="text-sm font-semibold">Đối chiếu bài viết độc lập</h4>
      <button type="button" className="rounded-md border px-2 py-1 text-xs disabled:opacity-50" disabled={loading} onClick={() => setRevision((n) => n + 1)}>
        <RefreshCw size={13} className="mr-1 inline" /> Làm mới
      </button>
    </div>
    {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    <div className="grid gap-2 text-xs sm:grid-cols-2">
      <p>Mã nộp bài tin cậy: <b>{status?.trusted_submission_linked ? "Đã liên kết" : "Chưa có"}</b></p>
      <p>Adapter được cấp phép: <b>{status?.readback_enabled ? "Đã cấu hình" : "Chưa cấu hình"}</b></p>
      <p>Job: <b>{status?.job_state ?? "—"}</b></p>
      <p>Xác minh đã xuất bản: <b>{status?.trusted_publication_verified ? "Đã xác minh" : "Chưa xác minh"}</b></p>
    </div>
    <p className="flex items-start gap-2 text-xs text-amber-800">
      {status?.trusted_publication_verified ? <ShieldCheck size={16} className="shrink-0"/> : <AlertTriangle size={16} className="shrink-0"/>}
      Không coi HAR, mã Story hoặc trạng thái chờ duyệt là bằng chứng đã đăng. Không có nút xác nhận thủ công hoặc thử đăng lại.
    </p>
    <div className="space-y-2">
      <p className="text-xs font-semibold">Lịch sử đọc lại ({status?.pagination.total ?? "—"})</p>
      {status?.checks.map((row) => <div className="rounded-md border border-slate-200 bg-white p-2 text-xs" key={row.id}>
        <span className="font-semibold">{outcomeLabels[row.outcome] ?? row.outcome}</span>
        <p className="mt-1 text-slate-500">{row.source_id} · {fmt(row.checked_at)}{row.error_code ? ` · ${row.error_code}` : ""}</p>
      </div>)}
      {!loading && status?.checks.length === 0 && <p className="text-xs text-slate-500">Chưa có lần kiểm tra độc lập nào.</p>}
      {status && status.pagination.total > status.checks.length && <p className="text-xs text-slate-500">Hiển thị các lần kiểm tra mới nhất. Truy vấn API để xem thêm.</p>}
    </div>
  </section>;
}
