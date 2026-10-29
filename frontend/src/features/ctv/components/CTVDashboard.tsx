"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle, AlertTriangle, CalendarClock, CheckCircle2, Clock3,
  Layers3, ListTodo, RefreshCw, Settings2, Users, ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { listPublishingJobs, type JobList } from "../api/publishing-jobs";
import {
  dashboardMetrics, getSchedulerTickStatus, getWorkspaceAccountStats,
  type PipelineTickStatus, type ScheduleTickRow, type WorkspaceAccountStats,
} from "../api/dashboard";

type Navigate = "scheduler" | "jobs" | "accounts";
interface Props {
  pipelineId: string;
  pipelineName: string;
  onNavigate: (tab: Navigate) => void;
}

const dateTime = (input: string | null | undefined) => {
  if (!input) return "Chưa có";
  const date = new Date(input);
  return Number.isNaN(date.getTime()) ? "Không xác định" :
    date.toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });
};

const errorMessage = (error: unknown) => error instanceof Error
  ? error.message : "Không tải được dữ liệu.";

function Card({ title, value, icon: Icon, hint }: {
  title: string; value: number | null;
  icon: LucideIcon; hint: string;
}) {
  return <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
    <div className="flex items-center justify-between gap-2 text-slate-500">
      <p className="text-xs font-medium">{title}</p>
      <Icon size={17} strokeWidth={1.7} aria-hidden="true" />
    </div>
    <p className="mt-3 text-2xl font-bold tabular-nums text-slate-900">
      {value === null ? "—" : value.toLocaleString("vi-VN")}
    </p>
    <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{hint}</p>
  </div>;
}

function TickLabel({ row }: { row: ScheduleTickRow }) {
  if (!row.enabled) {
    return <span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-600">Đã tắt</span>;
  }
  if (row.last_tick?.outcome === "error") {
    return <span className="rounded-md bg-red-50 px-2 py-1 text-[11px] font-semibold text-red-700">Lần chạy gần nhất lỗi</span>;
  }
  if (row.due) {
    return <span className="rounded-md bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-800">Đã đến hạn</span>;
  }
  if (row.last_tick?.outcome === "queued") {
    return <span className="rounded-md bg-blue-50 px-2 py-1 text-[11px] text-blue-700">Đã tạo Job</span>;
  }
  if (row.last_tick?.outcome === "replayed") {
    return <span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-700">Đã đối chiếu Batch</span>;
  }
  return <span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-600">Chưa có lần chạy</span>;
}

export default function CTVDashboard({ pipelineId, pipelineName, onNavigate }: Props) {
  const [ticks, setTicks] = useState<PipelineTickStatus | null>(null);
  const [jobs, setJobs] = useState<JobList | null>(null);
  const [accounts, setAccounts] = useState<WorkspaceAccountStats | null>(null);
  const [tickError, setTickError] = useState("");
  const [jobError, setJobError] = useState("");
  const [accountError, setAccountError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);

  // Only poll while this CTV dashboard is mounted. No write requests are sent.
  useEffect(() => {
    const controller = new AbortController();
    const reload = async (initial = false) => {
      if (initial) setLoading(true);
      const [tickResult, jobResult, accountResult] = await Promise.allSettled([
        getSchedulerTickStatus(pipelineId, controller.signal),
        listPublishingJobs(pipelineId, { page: 1, pageSize: 1, state: "all", search: "" }, controller.signal),
        getWorkspaceAccountStats(pipelineId, controller.signal),
      ]);
      if (controller.signal.aborted) return;
      if (tickResult.status === "fulfilled") {
        setTicks(tickResult.value);
        setTickError("");
      } else {
        setTicks(null);
        setTickError(errorMessage(tickResult.reason));
      }
      if (jobResult.status === "fulfilled") {
        setJobs(jobResult.value);
        setJobError("");
      } else {
        setJobs(null);
        setJobError(errorMessage(jobResult.reason));
      }
      if (accountResult.status === "fulfilled") {
        setAccounts(accountResult.value);
        setAccountError("");
      } else {
        setAccounts(null);
        setAccountError(errorMessage(accountResult.reason));
      }
      setUpdatedAt(new Date().toISOString());
      setLoading(false);
    };
    void reload(true);
    const timer = setInterval(() => { void reload(); }, 30_000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [pipelineId, refreshKey]);

  const metrics = useMemo(() => dashboardMetrics(ticks, jobs), [ticks, jobs]);
  const recent = useMemo(() => [...(ticks?.schedules ?? [])].sort((a, b) => {
    if (a.due !== b.due) return a.due ? -1 : 1;
    if ((a.last_tick?.outcome === "error") !== (b.last_tick?.outcome === "error")) {
      return a.last_tick?.outcome === "error" ? -1 : 1;
    }
    return Date.parse(a.next_run_at) - Date.parse(b.next_run_at);
  }), [ticks]);
  const issues = recent.filter((row) => row.enabled && (row.due || row.last_tick?.outcome === "error"));

  return <section className="space-y-5" aria-label="Tổng quan Pipeline">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Tổng quan Pipeline</h1>
        <p className="mt-1 text-xs text-slate-500">{pipelineName} · Theo dõi Scheduler và hàng đợi từ Neon PostgreSQL</p>
        <p className="mt-1 text-[11px] text-slate-400">Cập nhật mỗi 30 giây khi mở Dashboard. Lần tải: {dateTime(updatedAt)}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setRefreshKey((v) => v + 1)} disabled={loading}
          className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40">
          <RefreshCw size={14} aria-hidden="true" /> Làm mới
        </button>
        <button type="button" onClick={() => onNavigate("scheduler")}
          className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700">
          <Settings2 size={14} aria-hidden="true" /> Quản lý lịch
        </button>
      </div>
    </div>

    <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs text-blue-800">
      Scheduler chỉ tạo Job chờ xử lý. <strong>Không đồng nghĩa bài đã đăng Facebook.</strong> Trạng thái được suy ra từ bản ghi Tick trong database, không phải kiểm tra trực tiếp tiến trình systemd.
    </div>

    {(tickError || jobError || accountError) && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
      <p className="font-semibold">Không tải đủ dữ liệu Dashboard.</p>
      {tickError && <p>Scheduler: {tickError}</p>}
      {jobError && <p>Hàng đợi: {jobError}</p>}
      {accountError && <p>Tài khoản: {accountError}</p>}
      <p>Những mục chưa tải được hiển thị “—”, không mặc định là 0.</p>
    </div>}

    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Card title="Tổng Facebook Account" value={accounts?.facebook_accounts ?? null} icon={Users} hint="Số tài khoản thực của Pipeline" />
      <Card title="Account có trạng thái kết nối" value={accounts?.connected_accounts ?? null} icon={ShieldCheck} hint="Trạng thái nội bộ, không xác nhận quyền đăng Group" />
      <Card title="Lịch đang bật" value={metrics.enabled} icon={CalendarClock} hint={metrics.scheduledTotal === null ? "Đang chờ dữ liệu" : `Trong ${metrics.scheduledTotal} lịch của Pipeline`} />
      <Card title="Lịch đã đến hạn" value={metrics.due} icon={Clock3} hint="Chưa được xử lý theo con trỏ lịch hiện tại" />
      <Card title="Job đang chờ" value={metrics.queued} icon={ListTodo} hint="Đã tạo trong Neon; chưa xác nhận Facebook đã đăng" />
      <Card title="Cần đối soát" value={metrics.uncertain} icon={AlertCircle} hint="Không tự đăng lại khi chưa xác minh kết quả" />
      <Card title="Job sẵn sàng" value={metrics.ready} icon={Layers3} hint="Đã chuẩn bị ảnh, chưa xác nhận đăng" />
      <Card title="Job đã xác minh" value={metrics.published} icon={CheckCircle2} hint="Trạng thái published của Job Engine" />
      <Card title="Group bị bỏ qua (lần Tick mới nhất của từng lịch)" value={metrics.latestSkipped} icon={Users} hint="Không phải tổng Group bỏ qua từ trước đến nay" />
      <Card title="Lịch có lần Tick lỗi" value={metrics.tickErrors} icon={AlertTriangle} hint="Tính theo bản ghi Tick gần nhất của từng lịch" />
    </div>

    {ticks && ticks.schedule_count > ticks.schedules.length && <p className="rounded-md bg-amber-50 p-3 text-xs text-amber-800">
      Backend chỉ trả về {ticks.schedules.length} lịch đầu tiên trong tổng {ticks.schedule_count} lịch. Chỉ các dòng trong cửa sổ này được dùng để tính số Group bỏ qua và Tick lỗi.
    </p>}

    {issues.length > 0 && <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
      <div className="flex items-center gap-2 font-semibold"><AlertTriangle size={16} aria-hidden="true"/> Có {issues.length} lịch cần kiểm tra</div>
      <p className="mt-1">Lịch đến hạn hoặc lần chạy gần nhất bị lỗi. Kiểm tra log `toolnet-scheduler-tick` trên VPS nếu thời gian quá hạn kéo dài.</p>
    </div>}

    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_270px]">
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 p-4">
          <h2 className="text-sm font-semibold text-slate-900">Trạng thái từng lịch</h2>
          <span className="text-[11px] text-slate-500">{ticks?.schedules.length ?? "—"} lịch trong phản hồi</span>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-[680px] w-full text-left text-xs">
            <thead className="bg-slate-50 text-[11px] text-slate-500"><tr>
              <th className="px-4 py-3 font-medium">Tên lịch</th>
              <th className="px-4 py-3 font-medium">Trạng thái</th>
              <th className="px-4 py-3 font-medium">Lần Tick gần nhất</th>
              <th className="px-4 py-3 font-medium">Job / Bỏ qua</th>
              <th className="px-4 py-3 font-medium">Lần đến hạn tiếp</th>
            </tr></thead>
            <tbody className="divide-y divide-slate-100">
              {recent.map((row) => <tr key={row.schedule_id}>
                <td className="px-4 py-3 font-semibold text-slate-800">{row.name}</td>
                <td className="px-4 py-3"><TickLabel row={row}/></td>
                <td className="px-4 py-3 text-slate-600">
                  {dateTime(row.last_tick?.updated_at)}
                  {row.last_tick?.error_code && <span className="block text-red-700">{row.last_tick.error_code}</span>}
                </td>
                <td className="px-4 py-3 font-medium tabular-nums text-slate-700">{row.last_tick ? `${row.last_tick.assigned_count} / ${row.last_tick.skipped_count}` : "—"}</td>
                <td className="px-4 py-3 text-slate-600">{dateTime(row.next_run_at)}</td>
              </tr>)}
              {!loading && ticks && recent.length === 0 && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">Chưa có lịch. Vào Cấu hình lịch tự động để tạo lịch.</td></tr>}
              {(!ticks || loading) && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">{loading ? "Đang tải..." : "Không tải được trạng thái Scheduler."}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <div className="space-y-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><ShieldCheck size={17} aria-hidden="true" /> Lần Tick gần nhất</h2>
          {metrics.latestTick?.last_tick ? <div className="mt-3 space-y-2 text-xs text-slate-600">
            <p><span className="font-medium text-slate-800">{metrics.latestTick.name}</span></p>
            <p>Thời gian: {dateTime(metrics.latestTick.last_tick.updated_at)}</p>
            <p>Kết quả: {metrics.latestTick.last_tick.outcome === "queued" ? "Đã tạo hàng đợi" : metrics.latestTick.last_tick.outcome === "replayed" ? "Batch đã tồn tại" : "Lỗi"}</p>
            <p>Đã tạo: {metrics.latestTick.last_tick.assigned_count} · Bỏ qua: {metrics.latestTick.last_tick.skipped_count}</p>
          </div> : <p className="mt-3 text-xs text-slate-500">Chưa có bản ghi Tick của Pipeline.</p>}
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-900">Hàng đợi đăng bài</h2>
          <p className="mt-2 text-xs text-slate-600">Tổng số Job: {metrics.jobsTotal ?? "—"} · Lỗi: {metrics.failed ?? "—"}</p>
          <button type="button" onClick={() => onNavigate("jobs")}
            className="mt-3 w-full rounded-md border border-blue-200 px-3 py-2 text-xs font-semibold text-blue-700 hover:bg-blue-50">
            Xem danh sách Job
          </button>
        </div>
      </div>
    </div>
  </section>;
}
