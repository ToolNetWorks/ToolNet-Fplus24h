"use client";
import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCw, ShieldCheck } from "lucide-react";
import { getWorkerGuard, type WorkerGuardSnapshot } from "../api/worker-reliability";

const stateNames: Record<string, string> = {
  claimed: "Worker đã nhận", ready: "Đã chuẩn bị ảnh", dispatching: "Đã bắt đầu thử đăng",
};
const formatTime = (text: string | null) => text
  ? new Date(text).toLocaleString("vi-VN") : "Không có lease";

export default function CTVWorkerReliability({ pipelineId }: { pipelineId: string }) {
  const [data, setData] = useState<WorkerGuardSnapshot | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    let active = false;
    async function reload() {
      if (active || controller.signal.aborted) return;
      active = true;
      setLoading(true);
      try {
        const result = await getWorkerGuard(pipelineId, controller.signal);
        if (!controller.signal.aborted) { setData(result); setError(""); }
      } catch (cause) {
        if (!controller.signal.aborted) {
          setData(null);
          setError(cause instanceof Error ? cause.message : "Không thể đọc Worker.");
        }
      } finally {
        active = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void reload();
    const timer = window.setInterval(() => { if (!document.hidden) void reload(); }, 60_000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [pipelineId, revision]);

  return <section aria-label="Worker Reliability" className="space-y-3 overflow-hidden rounded-lg border border-slate-200 bg-white p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <ShieldCheck size={17}/> Worker Reliability — kiểm tra lease
        </h2>
        <p className="mt-1 text-xs text-slate-500">Chỉ đọc. Không cấp lại lease, không đăng bài, không tự retry.</p>
      </div>
      <button type="button" onClick={() => setRevision(v => v + 1)} disabled={loading}
        className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-xs disabled:opacity-40">
        <RefreshCw size={14}/>{loading ? "Đang kiểm tra" : "Làm mới"}
      </button>
    </div>
    {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">{error}</p>}
    {data && <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {([
          ["Đang xử lý", data.summary.in_flight],
          ["Lease hết hạn / thiếu", data.summary.expired_or_missing_lease],
          ["Account đang giữ", data.summary.held_accounts],
          ["Đã cách ly (lịch sử)", data.summary.recorded_quarantines],
        ] as const).map(([label, number]) => <div key={label} className="rounded-md border border-slate-100 bg-slate-50 p-3">
          <div className="text-xs text-slate-500">{label}</div>
          <div className="mt-2 text-xl font-semibold tabular-nums">{number.toLocaleString("vi-VN")}</div>
        </div>)}
      </div>
      {data.summary.expired_or_missing_lease > 0 &&
        <p role="status" className="flex items-start gap-2 rounded-md bg-amber-50 p-3 text-xs text-amber-900">
          <AlertTriangle size={15}/> Có Job cần đối soát. Chỉ người vận hành VPS mới được cách ly rõ ràng bằng CLI.
        </p>}
      {data.truncated && <p className="text-xs text-amber-900">
        Chỉ hiển thị {data.items.length} Job trong {data.summary.expired_or_missing_lease} Job bất thường. Dùng CLI để xem thêm.
      </p>}
      <div className="overflow-x-auto rounded-md border border-slate-100">
        <table className="min-w-[740px] w-full text-left text-xs">
          <thead className="bg-slate-50 text-slate-500"><tr>
            <th className="px-3 py-2">Job</th><th className="px-3 py-2">Account / Group</th>
            <th className="px-3 py-2">Trạng thái</th><th className="px-3 py-2">Lease</th>
            <th className="px-3 py-2">Xử lý</th>
          </tr></thead>
          <tbody>{data.items.map(item => <tr key={item.job_id} className="border-t border-slate-100">
            <td className="px-3 py-3 font-mono" title={item.job_id}>{item.job_id.slice(0, 8)}</td>
            <td className="px-3 py-3">{item.account.label} / {item.group.name}</td>
            <td className="px-3 py-3">{stateNames[item.state] ?? item.state}</td>
            <td className="px-3 py-3">{formatTime(item.lease_expires_at)}</td>
            <td className="px-3 py-3 text-amber-800">Cần đối soát</td>
          </tr>)}</tbody>
        </table>
        {data.items.length === 0 && <p className="p-4 text-xs text-slate-500">
          Không phát hiện lease hết hạn hoặc bị thiếu trong Pipeline này.
        </p>}
      </div>
      <p className="text-[11px] text-slate-500">Theo dõi lease từ Neon, không phải trạng thái systemd hay xác minh Facebook.</p>
    </>}
  </section>;
}
