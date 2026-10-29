"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, Database, RefreshCw, ShieldCheck } from "lucide-react";
import { getOperationsHealth, type OperationsHealth } from "../api/operations-health";

const formatCount = (value: number) => value.toLocaleString("vi-VN");
const formatDate = (value: string | null | undefined) => {
  if (!value) return "Chưa có dữ liệu";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Không xác định" :
    parsed.toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "medium" });
};
const alertLabels: Record<string, string> = {
  DATABASE_UNAVAILABLE: "Không kết nối được database",
  SCHEDULE_OVERDUE: "Có lịch đăng trễ trên 15 phút",
  SCHEDULER_TICK_ERRORS: "Scheduler Tick xảy ra lỗi trong 1 giờ",
  UNRESOLVED_JOBS_OVER_48H: "Có Job chưa xác minh quá 48 giờ",
  EXPIRED_WORKER_LEASES: "Có Job hết hạn Worker lease",
  INTEGRITY_ATTENTION_REQUIRED: "Phát hiện dữ liệu không nhất quán",
  INTEGRITY_INCOMPLETE: "Kiểm toán chưa quét hết dữ liệu",
};
const jobNames: Record<string, string> = {
  queued: "Đang chờ", claimed: "Worker đã nhận", ready: "Đã chuẩn bị",
  dispatching: "Đang thử đăng", uncertain: "Cần đối soát", published: "Đã đánh dấu xuất bản",
  failed: "Lỗi", cancelled: "Đã hủy",
};

type HealthRow = { name: string; value: string; state: "ok" | "attention" | "idle"; detail: string };

function healthRows(data: OperationsHealth): HealthRow[] {
  const rows: HealthRow[] = [
    {
      name: "Neon PostgreSQL", value: data.database.connected ? "Đã kết nối" : "Không kết nối",
      state: data.database.connected ? "ok" : "attention",
      detail: `Database: ${data.database.vendor}; độ trễ truy vấn ${data.query_duration_ms} ms`,
    },
    {
      name: "Lịch đăng (Scheduler)",
      value: `${formatCount(data.schedules.enabled)}/${formatCount(data.schedules.total)} lịch đang bật`,
      state: data.schedules.total === 0 ? "idle" : data.schedules.overdue_15m ? "attention" : "ok",
      detail: data.schedules.total === 0 ? "Pipeline chưa cấu hình lịch đăng" :
        `${formatCount(data.schedules.due)} lịch đến hạn, ${formatCount(data.schedules.overdue_15m)} lịch trễ >15 phút`,
    },
    {
      name: "Scheduler Tick (ghi nhận)",
      value: data.tick.last_at ? formatDate(data.tick.last_at) : "Chưa có lần chạy",
      state: data.tick.errors_1h ? "attention" : data.tick.last_at ? "ok" : "idle",
      detail: `Lần chạy gần nhất: ${data.tick.last_outcome ?? "—"}; lỗi 1h: ${formatCount(data.tick.errors_1h)}`,
    },
    {
      name: "Worker lease", value: `${formatCount(data.worker.expired_claims)} Job hết hạn`,
      state: data.worker.expired_claims ? "attention" : "ok",
      detail: "Dữ liệu Job trong Neon, không phải trạng thái tiến trình systemd",
    },
    {
      name: "Job chưa xác minh", value: `${formatCount(data.worker.uncertain_over_48h)} Job quá 48h`,
      state: data.worker.uncertain_over_48h ? "attention" : "ok",
      detail: "Không tự retry hoặc tự đánh dấu đăng thành công",
    },
    {
      name: "Kiểm toán nhất quán", value: `${formatCount(data.integrity.issues)} vấn đề`,
      state: !data.integrity.complete || data.integrity.status !== "consistent" ? "attention" : "ok",
      detail: data.integrity.complete ? "Đã kiểm tra hết dữ liệu trong giới hạn quét" :
        "Chưa kiểm tra đầy đủ — không kết luận an toàn",
    },
  ];
  return rows;
}

function Tone({ state }: { state: HealthRow["state"] }) {
  const text = state === "ok" ? "Bình thường" : state === "idle" ? "Chưa có dữ liệu" : "Cần kiểm tra";
  const css = state === "ok" ? "bg-emerald-50 text-emerald-700" :
    state === "idle" ? "bg-slate-100 text-slate-600" : "bg-amber-50 text-amber-800";
  return <span className={`whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-medium ${css}`}>{text}</span>;
}

export default function CTVOperationsDashboard({ pipelineId }: { pipelineId: string }) {
  const [snapshot, setSnapshot] = useState<OperationsHealth | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let busy = false;
    async function load() {
      if (controller.signal.aborted || busy) return;
      busy = true;
      setLoading(true);
      try {
        const result = await getOperationsHealth(pipelineId, controller.signal);
        if (controller.signal.aborted) return;
        setSnapshot(result); setError("");
      } catch (cause) {
        if (controller.signal.aborted) return;
        setSnapshot(null); setError(cause instanceof Error ? cause.message : "Không thể đọc dữ liệu vận hành.");
      } finally {
        busy = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 60_000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [pipelineId, revision]);

  const rows = useMemo(() => snapshot ? healthRows(snapshot) : [], [snapshot]);
  const stateCount: Record<string, number> = snapshot?.jobs_by_state ?? {};
  const jobTotal = Object.values(stateCount).reduce((total, value) => total + value, 0);
  const pending = (stateCount.queued ?? 0) + (stateCount.claimed ?? 0) + (stateCount.ready ?? 0);
  const inReview = (stateCount.dispatching ?? 0) + (stateCount.uncertain ?? 0);
  const noActivity = snapshot && snapshot.schedules.total === 0 && jobTotal === 0;

  return <section className="space-y-4" aria-label="Giám sát vận hành ToolNet Fplus24h">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Giám sát vận hành</h1>
        <p className="mt-1 text-xs text-slate-500">ToolNet Fplus24h · Theo dõi trạng thái Pipeline từ Neon PostgreSQL</p>
        <p className="mt-1 text-[11px] text-slate-400">Lần kiểm tra: {formatDate(snapshot?.checked_at)} · Làm mới tự động mỗi 60 giây</p>
      </div>
      <button type="button" disabled={loading} onClick={refresh}
        className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
        <RefreshCw size={14} aria-hidden="true" /> {loading ? "Đang tải..." : "Làm mới"}
      </button>
    </div>

    <p className="rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-900">
      Chỉ đọc thông tin vận hành từ database. <strong>Không phải</strong> kiểm tra tiến trình VPS hoặc bằng chứng bài đã hiển thị trên Facebook.
    </p>
    {error && <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
      <AlertTriangle size={16} aria-hidden="true" />Không thể xác nhận trạng thái hệ thống: {error}
    </div>}

    {snapshot && <>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {([
          ["Job trong Pipeline", jobTotal, Activity],
          ["Job đang chờ", pending, RefreshCw],
          ["Cần đối soát", inReview, AlertTriangle],
          ["Lỗi vận hành", snapshot.alerts.length, Database],
        ] as const).map(([label, value, Icon]) => <div key={label} className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between text-xs text-slate-500"><span>{label}</span><Icon size={16} /></div>
          <div className="mt-3 text-2xl font-bold tabular-nums text-slate-900">{formatCount(value)}</div>
        </div>)}
      </div>

      {noActivity && <div role="status" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        Pipeline chưa có lịch và Job. Dù kiểm toán dữ liệu hiện nhất quán, chưa có hoạt động thực tế để đánh giá khả năng đăng bài.
      </div>}

      {snapshot.alerts.length > 0 && <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        <div className="font-semibold">{snapshot.alerts.length} cảnh báo cần kiểm tra</div>
        <ul className="mt-2 list-disc space-y-1 pl-4">
          {snapshot.alerts.map((code, idx) => <li key={`${code}-${idx}`}>{alertLabels[code] ?? code}</li>)}
        </ul>
      </div>}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 p-4">
          <h2 className="text-sm font-semibold text-slate-900">Danh sách trạng thái vận hành</h2>
          <span className="text-xs text-slate-500">{rows.length} hạng mục · {snapshot.pipeline_status}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-xs">
            <thead><tr className="bg-slate-50 text-slate-500"><th className="px-4 py-3">Hạng mục</th><th className="px-4 py-3">Kết quả</th><th className="px-4 py-3">Trạng thái</th><th className="px-4 py-3">Chi tiết</th></tr></thead>
            <tbody>{rows.map((row) => <tr key={row.name} className="border-t border-slate-100">
              <th scope="row" className="px-4 py-3 font-semibold text-slate-800">{row.name}</th>
              <td className="px-4 py-3 text-slate-700">{row.value}</td>
              <td className="px-4 py-3"><Tone state={row.state}/></td>
              <td className="px-4 py-3 text-slate-500">{row.detail}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center gap-2 border-b border-slate-100 p-4"><ShieldCheck size={16} className="text-slate-500" /><h2 className="text-sm font-semibold text-slate-900">Tình trạng hàng đợi Job</h2></div>
        <div className="grid grid-cols-2 gap-2 p-4 sm:grid-cols-4">
          {Object.entries(jobNames).map(([key, label]) => <div key={key} className="rounded-lg border border-slate-100 bg-slate-50 p-3">
            <p className="text-[11px] text-slate-600">{label}</p>
            <p className="mt-2 text-xl font-semibold tabular-nums text-slate-900">{formatCount(stateCount[key] ?? 0)}</p>
          </div>)}
        </div>
        <p className="border-t border-slate-100 px-4 py-3 text-[11px] text-slate-500">Trạng thái published trong bảng Job không tự chứng minh bài đang hiển thị; cần chuỗi xác minh độc lập.</p>
      </div>
    </>}
    {!snapshot && loading && <p role="status" className="text-xs text-slate-500">Đang truy vấn trạng thái vận hành...</p>}
  </section>;
}
