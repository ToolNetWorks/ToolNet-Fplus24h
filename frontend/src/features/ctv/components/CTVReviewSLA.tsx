"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ChevronLeft, ChevronRight, RefreshCw, Timer } from "lucide-react";
import { getReviewSLA, type ReviewSLAFilter, type ReviewSLASnapshot, type ReviewSLANextAction } from "../api/review-sla";

const actionLabels: Record<ReviewSLANextAction, string> = {
  assign_owner: "Cần người phụ trách",
  collect_evidence: "Cần ghi bằng chứng",
  document_terminal_evidence: "Ghi kết quả cuối đã xác minh",
  close_after_review: "Có thể xem xét đóng hồ sơ",
  await_independent_verification: "Chờ xác minh độc lập",
  request_independent_verification: "Yêu cầu xác minh độc lập",
};
const statusLabels: Record<string, string> = {
  open: "Chưa nhận", in_review: "Đang xử lý", awaiting_verification: "Chờ xác minh",
};
const displayHours = (minutes: number) => `${Math.floor(minutes / 60)} giờ ${minutes % 60} phút`;
const errorText = (err: unknown) => err instanceof Error ? err.message : "Không thể đọc hồ sơ tồn đọng.";
const button = "rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 disabled:opacity-40 hover:bg-slate-50";

export default function CTVReviewSLA({ pipelineId, onOpenCase }: {
  pipelineId: string;
  onOpenCase: (caseId: string) => void;
}) {
  const [filter, setFilter] = useState<ReviewSLAFilter>("all");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [snapshot, setSnapshot] = useState<ReviewSLASnapshot | null>(null);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    getReviewSLA(pipelineId, { page, filter }, controller.signal)
      .then((data) => { if (!controller.signal.aborted) { setSnapshot(data); setError(""); } })
      .catch((cause: unknown) => { if (!controller.signal.aborted) { setSnapshot(null); setError(errorText(cause)); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [pipelineId, page, filter, revision]);

  useEffect(() => {
    const timer = window.setInterval(() => { if (!document.hidden) refresh(); }, 60000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const summary = snapshot?.summary;
  return <section className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4" aria-label="Theo dõi SLA hồ sơ đối soát">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Timer size={17}/> Hồ sơ tồn đọng & SLA</h3>
        <p className="mt-1 text-xs text-slate-500">Cảnh báo chỉ đọc. Bằng chứng do CTV ghi không xác nhận Facebook đã đăng bài.</p>
      </div>
      <button type="button" className={button} onClick={refresh} disabled={loading}><RefreshCw size={14} className="mr-1 inline"/>{loading ? "Đang tải" : "Làm mới"}</button>
    </div>
    {error && <p role="alert" className="rounded-md border border-red-200 bg-white p-3 text-xs text-red-700">{error}</p>}
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-5">
      {([
        ["Đang mở", summary?.total],
        ["Quá hạn", summary?.overdue],
        ["Nghiêm trọng", summary?.critical],
        ["Chưa nhận", summary?.unassigned],
        ["Chờ xác minh", summary?.awaiting_verification],
      ] as const).map(([label, value]) =>
        <div key={label} className="rounded-md border bg-white p-3">
          <p className="text-[11px] text-slate-500">{label}</p>
          <p className="mt-1 text-xl font-bold tabular-nums text-slate-900">{typeof value === "number" ? value.toLocaleString("vi-VN") : "—"}</p>
        </div>
      )}
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <label className="flex items-center gap-2 text-xs text-slate-700">Lọc hồ sơ
        <select className="rounded-md border bg-white px-3 py-2 text-xs" value={filter} onChange={(e) => { setFilter(e.target.value as ReviewSLAFilter); setPage(1); }}>
          <option value="all">Tất cả chưa đóng</option>
          <option value="overdue">Quá hạn</option>
          <option value="critical">Nghiêm trọng</option>
          <option value="awaiting">Đang chờ xác minh</option>
        </select>
      </label>
      <span className="text-[11px] text-slate-500">Ngưỡng: mới 2h · đang xử lý 6h · chờ xác minh 24h</span>
    </div>
    <div className="overflow-x-auto rounded-md border bg-white">
      <table className="w-full min-w-[780px] text-left text-xs">
        <thead><tr className="border-b bg-slate-50 text-slate-600"><th className="p-3">Hồ sơ / Account</th><th className="p-3">Group</th><th className="p-3">Trạng thái</th><th className="p-3">Chưa cập nhật</th><th className="p-3">Việc cần làm</th><th className="p-3">Chi tiết</th></tr></thead>
        <tbody>
          {snapshot?.items.map((row) => <tr key={row.case_id} className="border-b border-slate-100">
            <td className="p-3"><b className="font-mono">{row.case_id.slice(0, 8)}</b><p className="mt-1 text-slate-500">{row.account.label}</p></td>
            <td className="p-3">{row.group.name}</td>
            <td className="p-3"><span className="font-medium">{statusLabels[row.case_status] ?? row.case_status}</span>{row.severity !== "normal" && <p className={`mt-1 flex items-center gap-1 ${row.severity === "critical" ? "text-red-700" : "text-amber-700"}`}><AlertTriangle size={13}/>{row.severity === "critical" ? "Nghiêm trọng" : "Quá hạn"}</p>}</td>
            <td className="whitespace-nowrap p-3">{displayHours(row.idle_minutes)}</td>
            <td className="p-3">{actionLabels[row.next_action]}<p className="mt-1 text-slate-500">{row.evidence_count} ghi nhận bằng chứng</p></td>
            <td className="p-3"><button type="button" className={button} onClick={() => onOpenCase(row.case_id)}>Mở hồ sơ</button></td>
          </tr>)}
          {!loading && snapshot && snapshot.items.length === 0 && <tr><td colSpan={6} className="p-5 text-center text-slate-500">Không có hồ sơ phù hợp.</td></tr>}
        </tbody>
      </table>
    </div>
    <div className="flex items-center justify-between text-xs text-slate-500">
      <span>{snapshot ? `${snapshot.pagination.total} hồ sơ · trang ${snapshot.pagination.page}/${snapshot.pagination.total_pages}` : "Chưa có dữ liệu"}</span>
      <div className="flex gap-2">
        <button type="button" className={button} aria-label="Trang SLA trước" disabled={!snapshot?.pagination.has_previous || loading} onClick={() => setPage((p) => Math.max(1, p - 1))}><ChevronLeft size={14}/></button>
        <button type="button" className={button} aria-label="Trang SLA sau" disabled={!snapshot?.pagination.has_next || loading} onClick={() => setPage((p) => p + 1)}><ChevronRight size={14}/></button>
      </div>
    </div>
  </section>;
}
