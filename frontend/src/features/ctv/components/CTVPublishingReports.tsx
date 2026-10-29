"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, Download, Eye, RefreshCw, X } from "lucide-react";
import { listSchedules, type PipelineSchedule } from "../api/scheduler";
import {
  reportAccounts, reportBatches, reportBatchDetail, reportGroups, reportSummary,
  type AccountReport, type BatchDetail, type BatchSummary, type GroupReport,
  type Page, type ReportDays, type ReportFilters, type ReportSummary, type ReportTab,
} from "../api/reports";

const tabs: { key: ReportTab; label: string }[] = [
  { key: "overview", label: "Tổng quan" },
  { key: "batches", label: "Lượt lập lịch" },
  { key: "groups", label: "Theo Group" },
  { key: "accounts", label: "Theo Account" },
];
const skipReasons: Record<string, string> = {
  BATCH_LIMIT: "Vượt giới hạn Group/lượt",
  GROUP_DISABLED: "Group bị tắt",
  GROUP_PAUSED: "Group đang tạm dừng",
  GROUP_UNAVAILABLE: "Group được xác minh không khả dụng",
  GROUP_HAS_PENDING_JOB: "Group còn Job chưa hoàn tất",
  GROUP_COOLDOWN: "Group chưa hết thời gian giãn cách",
  ACCOUNT_PROXY_NOT_READY: "Account/Proxy không hợp lệ",
  NO_VERIFIED_ELIGIBLE_ACCOUNT: "Chưa xác minh quyền đăng ẩn danh / không tham gia Group",
  ACCOUNT_CAPACITY_EXHAUSTED: "Account đạt giới hạn nội bộ",
  CAPTION_TOO_LONG: "Caption quá 5.000 ký tự",
};
const stateLabels: Record<string, string> = {
  queued: "Đã tạo hàng đợi", claimed: "Worker đã nhận", ready: "Đã chuẩn bị",
  dispatching: "Đang gửi", uncertain: "Chưa rõ kết quả", published: "Đã xác minh đăng",
  failed: "Lỗi", cancelled: "Đã hủy",
};
const formatDate = (value: string | undefined | null) => value ?
  new Date(value).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" }) : "—";
const formatNumber = (n: number | null | undefined) => typeof n === "number" ? n.toLocaleString("vi-VN") : "—";
const errorText = (e: unknown) => e instanceof Error ? e.message : "Không tải được báo cáo.";
const fieldClass = "rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 focus:border-blue-500 focus:outline-none";
const buttonClass = "inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40";
const th = "whitespace-nowrap px-3 py-2.5 text-left text-[11px] font-semibold text-slate-500";
const td = "px-3 py-3 text-xs text-slate-700";

function exportCSV(filename: string, headers: string[], rows: (string | number | boolean | null | undefined)[][]) {
  const safe = (value: string | number | boolean | null | undefined) => {
    let text = String(value ?? "");
    // Do not execute CSV formulas when reports are opened in Excel/Sheets.
    if (/^[\s\u0000-\u001f]*[=+@-]/.test(text)) text = "'" + text;
    return `"${text.replace(/"/g, '""')}"`;
  };
  const csv = "\uFEFF" + [headers, ...rows].map((row) => row.map(safe).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Stat({ label, value, hint }: { label: string; value: number | null | undefined; hint: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
    <p className="text-xs font-medium text-slate-500">{label}</p>
    <p className="mt-2 text-2xl font-bold tabular-nums text-slate-900">{formatNumber(value)}</p>
    <p className="mt-2 text-[11px] text-slate-500">{hint}</p>
  </div>;
}

export default function CTVPublishingReports({ pipelineId }: { pipelineId: string }) {
  const [tab, setTab] = useState<ReportTab>("overview");
  const [days, setDays] = useState<ReportDays>(30);
  const [scheduleId, setScheduleId] = useState("");
  const [schedules, setSchedules] = useState<PipelineSchedule[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [summary, setSummary] = useState<ReportSummary | null>(null);
  const [batches, setBatches] = useState<Page<BatchSummary> | null>(null);
  const [groups, setGroups] = useState<Page<GroupReport> | null>(null);
  const [accounts, setAccounts] = useState<Page<AccountReport> | null>(null);
  const [detail, setDetail] = useState<BatchDetail | null>(null);
  const [error, setError] = useState("");
  const [scheduleError, setScheduleError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  const filters: ReportFilters = useMemo(() => ({
    days, scheduleId, page, pageSize: 20, search,
  }), [days, scheduleId, page, search]);
  const activePage = tab === "batches" ? batches?.pagination :
    tab === "groups" ? groups?.pagination : tab === "accounts" ? accounts?.pagination : undefined;
  const reload = () => setRevision((value) => value + 1);
  const changeTab = (next: ReportTab) => { setTab(next); setPage(1); setSearch(""); setSearchInput(""); };

  useEffect(() => {
    const controller = new AbortController();
    listSchedules(pipelineId, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setSchedules(data); })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setScheduleError(errorText(cause)); });
    return () => controller.abort();
  }, [pipelineId, revision]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    const load = async () => {
      // The overview figures are fetched separately so failures never appear as zero.
      const summaryPromise = reportSummary(pipelineId, filters, controller.signal);
      const rowsPromise = tab === "batches" ? reportBatches(pipelineId, filters, controller.signal) :
        tab === "groups" ? reportGroups(pipelineId, filters, controller.signal) :
        tab === "accounts" ? reportAccounts(pipelineId, filters, controller.signal) : Promise.resolve(null);
      const [summaryResult, rowsResult] = await Promise.allSettled([summaryPromise, rowsPromise]);
      if (controller.signal.aborted) return;
      if (summaryResult.status === "fulfilled") setSummary(summaryResult.value);
      else { setSummary(null); setError(errorText(summaryResult.reason)); }
      if (rowsResult.status === "fulfilled") {
        if (tab === "batches") setBatches(rowsResult.value as Page<BatchSummary>);
        if (tab === "groups") setGroups(rowsResult.value as Page<GroupReport>);
        if (tab === "accounts") setAccounts(rowsResult.value as Page<AccountReport>);
      } else {
        if (tab === "batches") setBatches(null);
        if (tab === "groups") setGroups(null);
        if (tab === "accounts") setAccounts(null);
        setError((current) => current || errorText(rowsResult.reason));
      }
    };
    void load().finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [pipelineId, filters, revision, tab]);

  async function openBatch(id: string) {
    setDetail(null); setDetailError(""); setDetailLoading(true);
    try { setDetail(await reportBatchDetail(pipelineId, id)); }
    catch (cause) { setDetailError(errorText(cause)); }
    finally { setDetailLoading(false); }
  }

  function exportCurrent() {
    const name = `toolnet-${tab}-${days}days-page${page}.csv`;
    if (tab === "batches" && batches) exportCSV(name,
      ["Batch ID", "Lịch", "Đến hạn", "Đã tạo Job", "Lượt bỏ qua"],
      batches.data.map((b) => [b.id, b.schedule_name, b.slot_at, b.assigned_count, b.skip_events]));
    if (tab === "groups" && groups) exportCSV(name,
      ["Group", "URL", "Trạng thái", "Job", "Đang chờ", "Cần đối soát", "Đã xác minh", "Bỏ qua"],
      groups.data.map((g) => [g.name, g.group_url, g.health_state, g.jobs,
        g.queued, g.uncertain, g.published_verified, g.skip_events]));
    if (tab === "accounts" && accounts) exportCSV(name,
      ["Account", "Kết nối", "Proxy", "Job", "Đang chờ", "Cần đối soát", "Đã xác minh"],
      accounts.data.map((a) => [a.label, a.connection_status, a.proxy_health,
        a.jobs, a.queued, a.uncertain, a.published_verified]));
  }

  return <section className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Lịch sử đăng bài & Báo cáo</h1>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-500">
          Số liệu từ Neon. Đã tạo Job không đồng nghĩa đã đăng Facebook;
          chỉ tính thành công khi có mã bài đăng được xác minh.
        </p>
      </div>
      <button type="button" onClick={reload} disabled={loading} className={buttonClass}>
        <RefreshCw size={14} /> Làm mới
      </button>
    </div>

    <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4">
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
        Khoảng thời gian
        <select aria-label="Khoảng thời gian báo cáo" className={fieldClass} value={days}
          onChange={(e) => { setDays(Number(e.target.value) as ReportDays); setPage(1); }}>
          <option value={7}>7 ngày</option><option value={30}>30 ngày</option><option value={90}>90 ngày</option>
        </select>
      </label>
      <label className="flex min-w-52 flex-1 flex-col gap-1 text-xs font-medium text-slate-600">
        Lọc theo lịch
        <select aria-label="Lọc theo lịch" value={scheduleId} className={fieldClass}
          onChange={(e) => { setScheduleId(e.target.value); setPage(1); }}>
          <option value="">Tất cả lịch và Job thủ công</option>
          {schedules.map((schedule) => <option key={schedule.id} value={schedule.id}>{schedule.name}</option>)}
        </select>
      </label>
      {scheduleError && <p role="alert" className="text-xs text-amber-700">{scheduleError}</p>}
    </div>

    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      <Stat label="Job tạo trong kỳ" value={summary?.jobs.total} hint="Không phải bài đăng" />
      <Stat label="Job đang chờ" value={summary?.jobs.queued} hint="Chờ xử lý" />
      <Stat label="Đăng xác minh" value={summary?.jobs.published_verified} hint="Có external post ID" />
      <Stat label="Cần đối soát" value={summary?.jobs.uncertain} hint="Chưa rõ kết quả" />
      <Stat label="Batch lập lịch" value={summary?.batches} hint="Tính theo slot_at" />
      <Stat label="Lượt Group bỏ qua" value={summary?.skip_events} hint="Lượt, không phải số Group duy nhất" />
    </div>

    {error && <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50 p-3 text-xs text-red-700"><AlertCircle size={15} />{error}</div>}
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap gap-1 border-b border-slate-200 p-3" role="tablist" aria-label="Chọn báo cáo">
        {tabs.map((option) => <button key={option.key} type="button" role="tab"
          aria-selected={tab === option.key} onClick={() => changeTab(option.key)}
          className={`rounded-lg px-3 py-2 text-xs font-semibold ${tab === option.key ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-50"}`}>
          {option.label}
        </button>)}
      </div>
      {tab === "overview" && <div className="space-y-4 p-4">
        <h2 className="text-sm font-semibold text-slate-900">Trạng thái Job hiện tại</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(["claimed", "ready", "dispatching", "failed", "cancelled", "published"] as const).map((state) =>
            <div key={state} className="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <div className="text-xs text-slate-600">{stateLabels[state]}</div>
              <div className="mt-1 text-xl font-bold">{formatNumber(summary?.jobs[state])}</div>
            </div>)}
        </div>
        <p className="text-xs text-slate-500">Job thủ công: {formatNumber(summary?.manual_jobs)} · Job thuộc lịch: {formatNumber(summary?.scheduled_jobs)}</p>
        <h2 className="text-sm font-semibold text-slate-900">Nguyên nhân bỏ qua Group</h2>
        {summary && Object.keys(summary.skip_reasons).length === 0 ?
          <p className="text-xs text-slate-500">Chưa ghi nhận lượt bỏ qua trong kỳ.</p> :
          <div className="grid gap-2 md:grid-cols-2">{Object.entries(summary?.skip_reasons ?? {})
            .sort((a, b) => b[1] - a[1]).map(([code, count]) =>
              <div key={code} className="flex items-center justify-between gap-3 rounded-lg border border-slate-100 px-3 py-2 text-xs">
                <span title={code}>{skipReasons[code] ?? code}</span><strong>{formatNumber(count)}</strong>
              </div>)}</div>}
        <p className="text-[11px] text-slate-500">Cửa sổ báo cáo tính theo ngày tạo Job và thời gian slot của Batch; trạng thái Job có thể thay đổi sau khi được tạo.</p>
      </div>}

      {tab !== "overview" && <div className="p-3">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {tab !== "batches" && <form className="flex flex-1 flex-wrap gap-2" onSubmit={(e: FormEvent<HTMLFormElement>) => { e.preventDefault(); setPage(1); setSearch(searchInput); }}>
            <input aria-label="Tìm kiếm Group hoặc Account" value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)} maxLength={100}
              className={`${fieldClass} min-w-40 flex-1`} placeholder="Tìm tên..." />
            <button className={buttonClass} type="submit">Tìm</button>
          </form>}
          <button type="button" onClick={exportCurrent} disabled={loading || !(tab === "batches" ? batches : tab === "groups" ? groups : accounts)} className={buttonClass}>
            <Download size={14} /> CSV trang hiện tại
          </button>
        </div>
        <div className="overflow-x-auto"><table className="min-w-[650px] w-full text-left">
          {tab === "batches" && <><thead><tr className="bg-slate-50">
            <th className={th}>Lịch</th><th className={th}>Đến hạn</th><th className={th}>Job đã tạo</th><th className={th}>Group bỏ qua</th><th className={th}>Chi tiết</th>
          </tr></thead><tbody className="divide-y divide-slate-100">
            {(batches?.data ?? []).map((b) => <tr key={b.id}>
              <td className={td}>{b.schedule_name}</td><td className={td}>{formatDate(b.slot_at)}</td>
              <td className={td}>{formatNumber(b.assigned_count)}</td><td className={td}>{formatNumber(b.skip_events)}</td>
              <td className={td}><button type="button" onClick={() => void openBatch(b.id)} className={buttonClass}><Eye size={13} /> Xem</button></td>
            </tr>)}
          </tbody></>}
          {tab === "groups" && <><thead><tr className="bg-slate-50">
            <th className={th}>Group</th><th className={th}>Trạng thái</th><th className={th}>Job</th><th className={th}>Đang chờ</th><th className={th}>Đã xác minh</th><th className={th}>Đối soát</th><th className={th}>Bỏ qua</th>
          </tr></thead><tbody className="divide-y divide-slate-100">
            {(groups?.data ?? []).map((g) => <tr key={g.group_id}>
              <td className={td}><a href={g.group_url} target="_blank" rel="noopener noreferrer" className="font-semibold text-blue-700 hover:underline">{g.name}</a></td>
              <td className={td}>{!g.is_enabled ? "Đã tắt" : g.health_state === "unavailable" ? "Không khả dụng" : g.health_state === "paused" ? "Tạm dừng" : "Đang hoạt động"}</td>
              <td className={td}>{g.jobs}</td><td className={td}>{g.queued}</td><td className={td}>{g.published_verified}</td><td className={td}>{g.uncertain}</td><td className={td}>{g.skip_events}</td>
            </tr>)}
          </tbody></>}
          {tab === "accounts" && <><thead><tr className="bg-slate-50">
            <th className={th}>Facebook Account</th><th className={th}>Kết nối</th><th className={th}>Proxy</th><th className={th}>Job</th><th className={th}>Đang chờ</th><th className={th}>Đã xác minh</th><th className={th}>Đối soát</th>
          </tr></thead><tbody className="divide-y divide-slate-100">
            {(accounts?.data ?? []).map((a) => <tr key={a.account_id}>
              <td className={td}><strong>{a.label}</strong></td><td className={td}>{a.connection_status}</td>
              <td className={td}>{a.proxy_assigned ? (a.proxy_health ?? "Chưa kiểm tra") : "Chưa gán"}</td>
              <td className={td}>{a.jobs}</td><td className={td}>{a.queued}</td><td className={td}>{a.published_verified}</td><td className={td}>{a.uncertain}</td>
            </tr>)}
          </tbody></>}
        </table></div>
        {!loading && (tab === "batches" ? batches?.data.length === 0 : tab === "groups" ? groups?.data.length === 0 : accounts?.data.length === 0) &&
          <p className="py-8 text-center text-xs text-slate-500">Không có dữ liệu phù hợp.</p>}
        <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500">
          <span>{activePage ? `${formatNumber(activePage.total)} bản ghi` : "—"}</span>
          <div className="flex items-center gap-3">
            <button type="button" disabled={loading || !activePage?.has_previous} onClick={() => setPage(Math.max(1, page - 1))} aria-label="Trang trước" className={buttonClass}><ChevronLeft size={14} /></button>
            <span>{activePage ? `${activePage.page}/${activePage.total_pages}` : "—"}</span>
            <button type="button" disabled={loading || !activePage?.has_next} onClick={() => setPage(page + 1)} aria-label="Trang sau" className={buttonClass}><ChevronRight size={14} /></button>
          </div>
        </div>
      </div>}
    </div>

    {detailLoading && <p role="status" className="text-xs text-slate-500">Đang tải chi tiết Batch...</p>}
    {detailError && <p role="alert" className="text-xs text-red-700">{detailError}</p>}
    {detail && <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-3" role="presentation">
      <div role="dialog" aria-modal="true" aria-label="Chi tiết Batch" className="max-h-[90dvh] w-full max-w-5xl overflow-y-auto rounded-xl bg-white p-5 shadow-xl">
        <div className="mb-4 flex items-start justify-between gap-2">
          <div><h2 className="text-lg font-bold text-slate-900">{detail.schedule_name}</h2>
            <p className="text-xs text-slate-500">Batch {detail.id} · {formatDate(detail.slot_at)}</p></div>
          <button type="button" onClick={() => setDetail(null)} aria-label="Đóng chi tiết" className={buttonClass}><X size={16} /></button>
        </div>
        <div className="mb-4 flex flex-wrap gap-3 text-xs text-slate-600">
          <span>Job tạo: <strong>{detail.assigned_count}</strong></span>
          <span>Lượt bỏ qua: <strong>{detail.skipped.length}</strong></span>
          <span>Tick: <strong>{detail.tick?.outcome ?? "Không có nhật ký"}</strong></span>
        </div>
        <h3 className="mb-2 text-sm font-semibold">Account–Group đã phân phối</h3>
        <div className="overflow-x-auto"><table className="min-w-[650px] w-full">
          <thead><tr className="bg-slate-50"><th className={th}>Group</th><th className={th}>Account</th><th className={th}>Thời gian</th><th className={th}>Trạng thái Job</th><th className={th}>Mã bài đăng</th></tr></thead>
          <tbody className="divide-y divide-slate-100">{detail.assignments.map((a) => <tr key={a.job_id}>
            <td className={td}>{a.group_name}</td><td className={td}>{a.account_label}</td>
            <td className={td}>{formatDate(a.scheduled_at)}</td>
            <td className={td}>{a.published_verified ? "Đăng xác minh" : stateLabels[a.job_state] ?? a.job_state}</td>
            <td className={`${td} break-all`}>{a.external_post_id ?? "—"}</td>
          </tr>)}</tbody>
        </table></div>
        <h3 className="mb-2 mt-5 text-sm font-semibold">Group bị bỏ qua</h3>
        {!detail.skipped.length && <p className="text-xs text-slate-500">Không có Group bị bỏ qua.</p>}
        <div className="space-y-2">{detail.skipped.map((s, index) =>
          <div key={`${s.group_id}-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs">
            <strong>{s.group_name}</strong><span title={s.code} className="text-slate-600">{skipReasons[s.code] ?? s.code}</span>
          </div>)}</div>
        <p className="mt-4 text-[11px] text-slate-500">Proxy và IP được lưu làm snapshot phục vụ đối chiếu, không sử dụng để tự đổi IP hoặc thực hiện đăng Facebook.</p>
      </div>
    </div>}
  </section>;
}
