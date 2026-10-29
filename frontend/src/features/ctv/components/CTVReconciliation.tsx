"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ChevronLeft, ChevronRight, RefreshCw, ShieldAlert } from "lucide-react";
import { getPublishingReconciliation, type ReconciliationData } from "../api/reconciliation";
import CTVReviewCases from "./CTVReviewCases";

const dateTime = (value: string | null) => value ? new Date(value).toLocaleString("vi-VN") : "—";
const errorText = (value: unknown) => value instanceof Error ? value.message : "Không tải được cảnh báo.";
const reasonNames: Record<string, string> = {
  UNVERIFIED_POST_RESULT: "Chưa xác minh kết quả đăng",
  DISPATCH_LEASE_EXPIRED: "Hết hạn khi đang xử lý đăng",
  DISPATCH_AWAITING_VERIFICATION: "Đang chờ xác minh bài đăng",
  WORKER_LEASE_EXPIRED: "Worker quá hạn",
  PUBLISHED_MISSING_POST_ID: "Đã đánh dấu thành công nhưng thiếu mã bài đăng",
  JOB_FAILED: "Job thất bại",
  ACCOUNT_HAS_IN_FLIGHT_OR_UNVERIFIED_JOB: "Account đang có Job chưa xác minh",
  ACCOUNT_NOT_CONNECTED: "Account chưa kết nối",
  PROXY_MISSING: "Chưa gắn Proxy",
  PROXY_NOT_HEALTHY: "Proxy chưa hoạt động ổn định",
  PROXY_HEALTH_STALE: "Proxy quá 24 giờ chưa kiểm tra",
  PROXY_PIN_MISMATCH: "Proxy hoặc IP khác bản ghim",
};
const card = "rounded-xl border border-slate-200 bg-white p-4 shadow-sm";
const button = "inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-2 text-xs disabled:opacity-40";

export default function CTVReconciliation({ pipelineId }: { pipelineId: string }) {
  const [data, setData] = useState<ReconciliationData | null>(null);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const reload = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    getPublishingReconciliation(pipelineId, page, 20, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setData(result); })
      .catch((cause: unknown) => { if (!controller.signal.aborted) { setData(null); setError(errorText(cause)); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [pipelineId, page, revision]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (!document.hidden) reload();
    }, 60000);
    return () => window.clearInterval(interval);
  }, [reload]);

  const summary = data?.summary;
  const kpis = [
    ["Job cần kiểm tra", summary?.review_required_jobs],
    ["Chưa xác minh", summary?.uncertain],
    ["Account đang được giữ", summary?.held_accounts],
    ["Group đang được giữ", summary?.held_groups],
    ["Đăng đã xác minh", summary?.published_verified],
    ["Group đang tạm dừng / không khả dụng", summary?.group_health_alerts],
  ] as const;

  return <section className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Đối soát & Cảnh báo</h1>
        <p className="mt-1 text-xs text-slate-500">Chỉ đọc dữ liệu Neon. Không tự thử đăng lại hoặc kết luận thành công khi thiếu mã bài đăng xác minh.</p>
      </div>
      <button type="button" onClick={reload} disabled={loading} className={button}>
        <RefreshCw size={15} aria-hidden="true"/> {loading ? "Đang tải..." : "Làm mới"}
      </button>
    </div>

    {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">{error}</p>}
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
      {kpis.map(([title, value]) => <div key={title} className={card}>
        <p className="text-xs text-slate-500">{title}</p>
        <p className="mt-2 text-2xl font-bold tabular-nums text-slate-900">{typeof value === "number" ? value.toLocaleString("vi-VN") : "—"}</p>
      </div>)}
    </div>

    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
      <div className="flex items-center gap-2 font-semibold"><ShieldAlert size={16}/> Các Job chưa rõ kết quả không được tự động thử lại.</div>
      <p className="mt-2 leading-relaxed">Cần kiểm tra chứng cứ đăng thực tế trước khi thay đổi trạng thái. Account có Job đang xử lý hoặc chưa xác minh sẽ tạm ngừng nhận công việc mới. Kết quả chờ duyệt không được tính là đã đăng thành công.</p>
    </div>

    <div className={card}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-900">Job cần kiểm tra</h2>
        <span className="text-xs text-slate-500">{data?.pagination.total ?? "—"} Job</span>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[780px] text-left text-xs">
          <thead><tr className="border-b text-slate-500"><th className="px-3 py-3">Job</th><th className="px-3 py-3">Account</th><th className="px-3 py-3">Group</th><th className="px-3 py-3">Vấn đề</th><th className="px-3 py-3">Cập nhật</th></tr></thead>
          <tbody>
            {data?.jobs.length ? data.jobs.map((row) => <tr key={row.job_id} className="border-b border-slate-100">
              <td className="px-3 py-3 font-mono" title={row.job_id}>{row.job_id.slice(0, 8)}</td>
              <td className="px-3 py-3">{row.account.label}</td>
              <td className="px-3 py-3">{row.group.name}</td>
              <td className="px-3 py-3"><div className={`flex items-center gap-1.5 ${row.severity === "critical" ? "text-red-700" : "text-amber-800"}`}><AlertTriangle size={14}/>{reasonNames[row.reason_code] ?? row.reason_code}</div>{row.error_code && <p className="mt-1 text-slate-500">{row.error_code}</p>}</td>
              <td className="px-3 py-3">{dateTime(row.updated_at)}</td>
            </tr>) : <tr><td colSpan={5} className="px-3 py-8 text-center text-slate-500">{loading ? "Đang tải..." : "Chưa có Job cần đối soát."}</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between border-t pt-3 text-xs">
        <span>Trang {data?.pagination.page ?? page}/{data?.pagination.total_pages ?? "—"}</span>
        <div className="flex gap-2">
          <button type="button" aria-label="Trang trước" className={button} disabled={!data?.pagination.has_previous || loading} onClick={() => setPage((p) => Math.max(1, p - 1))}><ChevronLeft size={15}/></button>
          <button type="button" aria-label="Trang sau" className={button} disabled={!data?.pagination.has_next || loading} onClick={() => setPage((p) => p + 1)}><ChevronRight size={15}/></button>
        </div>
      </div>
    </div>

    <div className="grid gap-4 lg:grid-cols-2">
      <div className={card}>
        <h2 className="text-sm font-semibold">Account cần chú ý</h2>
        <div className="mt-3 max-h-[400px] space-y-2 overflow-y-auto">
          {data?.account_alerts.length ? data.account_alerts.map((row) => <div key={row.account_id} className="rounded-lg border border-slate-100 p-3 text-xs">
            <p className="font-semibold">{row.label}</p>
            {row.codes.map((code) => <p key={code} className="mt-1 text-slate-600">{reasonNames[code] ?? code}</p>)}
          </div>) : <p className="text-xs text-slate-500">Chưa có cảnh báo Account.</p>}
        </div>
        {data?.account_alerts_truncated && <p className="mt-2 text-xs text-amber-800">Danh sách giới hạn 500 Account. Dùng API để rà soát thêm.</p>}
      </div>
      <div className={card}>
        <h2 className="text-sm font-semibold">Group bị tạm dừng / không khả dụng</h2>
        <div className="mt-3 max-h-[400px] space-y-2 overflow-y-auto">
          {data?.group_alerts.length ? data.group_alerts.map((row) => <div key={row.group_id} className="rounded-lg border border-slate-100 p-3 text-xs">
            <p className="font-semibold">{row.name}</p>
            <p className="mt-1 text-slate-600">{row.state === "paused" ? "Tạm dừng" : "Không khả dụng"}{row.reason_code ? ` · ${row.reason_code}` : ""}</p>
            {row.review_after && <p className="mt-1 text-slate-500">Kiểm tra lại: {dateTime(row.review_after)}</p>}
          </div>) : <p className="text-xs text-slate-500">Chưa có Group bị tạm dừng.</p>}
        </div>
        {data?.group_alerts_truncated && <p className="mt-2 text-xs text-amber-800">Danh sách giới hạn 500 Group.</p>}
      </div>
    </div>
    <CTVReviewCases pipelineId={pipelineId} flaggedJobs={data?.jobs ?? []} />
  </section>;
}
