"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Bell, BellOff, CheckCheck, ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import {
  fetchOperationalAlerts, mutateOperationalAlert, fetchAlertEvents,
  type AlertEventHistory,
  type OperationalAlert, type AlertFilter, type AlertInbox,
} from "../api/operational-alerts";

const button = "inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40";
const fmt = (text: string | null) => text ? new Date(text).toLocaleString("vi-VN", {
  dateStyle: "short", timeStyle: "short",
}) : "Chưa có";
const errorText = (error: unknown) => error instanceof Error ? error.message : "Không thể thao tác với cảnh báo.";

export default function CTVAlertInbox({ pipelineId }: { pipelineId: string }) {
  const [filter, setFilter] = useState<AlertFilter>("open");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [inbox, setInbox] = useState<AlertInbox | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [history, setHistory] = useState<AlertEventHistory | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const reload = useCallback(() => setRevision((v) => v + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let running = false;
    async function load() {
      if (controller.signal.aborted || running) return;
      running = true;
      setLoading(true);
      try {
        const data = await fetchOperationalAlerts(pipelineId, filter, page, controller.signal);
        if (controller.signal.aborted) return;
        setInbox(data); setError("");
      } catch (cause) {
        if (controller.signal.aborted) return;
        setError(errorText(cause)); setInbox(null);
      } finally {
        running = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 60_000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [pipelineId, filter, page, revision]);

  async function act(item: OperationalAlert, action: "acknowledge" | "snooze") {
    if (busyId) return;
    setBusyId(item.id); setError(""); setNotice("");
    try {
      await mutateOperationalAlert(pipelineId, item, action);
      setNotice(action === "acknowledge"
        ? "Đã ghi nhận đã xem. Cảnh báo vẫn mở nếu sự cố chưa hết."
        : "Đã tạm ẩn thông báo 60 phút. Không thay đổi Job hay trạng thái sự cố.");
      reload();
    } catch (cause) {
      setError(errorText(cause));
    } finally { setBusyId(null); }
  }

  async function openHistory(item: OperationalAlert) {
    if (historyLoading) return;
    if (history?.alert_id === item.id) { setHistory(null); return; }
    setHistory(null); setHistoryLoading(true); setError("");
    try {
      const events = await fetchAlertEvents(pipelineId, item.id);
      setHistory(events);
    } catch (cause) { setError(errorText(cause)); }
    finally { setHistoryLoading(false); }
  }

  const summary = inbox?.summary;
  const total = inbox?.pagination.total ?? null;
  return <section className="space-y-4" aria-label="Hộp cảnh báo ToolNet Fplus24h">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-bold text-slate-900"><Bell size={20} /> Thông báo & Cảnh báo</h1>
        <p className="mt-1 text-xs text-slate-500">Thông báo nội bộ theo Pipeline. Không gửi email, Telegram hoặc gọi Facebook.</p>
        <p className="mt-1 text-[11px] text-slate-400">Quét gần nhất: {fmt(inbox?.last_scan_at ?? null)} · Làm mới giao diện mỗi 60 giây</p>
      </div>
      <button type="button" className={button} onClick={reload} disabled={loading}>
        <RefreshCw size={14} aria-hidden="true" /> {loading ? "Đang tải" : "Làm mới"}
      </button>
    </div>
    {inbox?.scan_stale && <div role="status" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
      Dữ liệu cảnh báo chưa được quét gần đây. Hãy kiểm tra lịch chạy <code>toolnet-alert-scanner.timer</code> trên VPS. Chưa thể kết luận không có sự cố.
    </div>}
    {error && <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-800">
      <AlertTriangle size={15} className="mr-1 inline" /> {error}
    </div>}
    {notice && <p role="status" className="rounded-md border border-blue-100 bg-blue-50 p-3 text-xs text-blue-800">{notice}</p>}

    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {([
        ["Đang mở", summary?.open],
        ["Nghiêm trọng", summary?.critical_open],
        ["Cần chú ý", summary?.requires_attention],
        ["Đã giải quyết", summary?.resolved],
      ] as const).map(([title, count]) => <div key={title} className="rounded-lg border border-slate-200 bg-white p-3">
        <p className="text-xs text-slate-500">{title}</p>
        <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{count === undefined ? "—" : count.toLocaleString("vi-VN")}</p>
      </div>)}
    </div>

    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-3">
        <div className="flex items-center gap-2">
          <label htmlFor="alert-filter" className="text-xs font-semibold text-slate-600">Hiển thị</label>
          <select id="alert-filter" value={filter} onChange={(event) => { setFilter(event.target.value as AlertFilter); setPage(1); }}
            className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800">
            <option value="open">Đang mở</option><option value="resolved">Đã giải quyết</option><option value="all">Tất cả</option>
          </select>
        </div>
        <span className="text-xs text-slate-500">{total === null ? "—" : total.toLocaleString("vi-VN")} cảnh báo</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-left text-xs">
          <thead><tr className="bg-slate-50 text-slate-500">
            <th className="p-3">STT</th><th className="p-3">Cảnh báo</th><th className="p-3">Mức độ</th>
            <th className="p-3">Trạng thái</th><th className="p-3">Lần cuối</th><th className="p-3">Hành động</th>
          </tr></thead>
          <tbody>{inbox?.items.map((item, index) => <tr key={item.id} className="border-t border-slate-100">
            <td className="p-3 text-slate-500">{(page - 1) * 20 + index + 1}</td>
            <td className="p-3"><p className="font-medium text-slate-800">{item.title}</p><p className="mt-1 font-mono text-[10px] text-slate-400">{item.code}</p></td>
            <td className="p-3"><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${item.severity === "critical" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-800"}`}>
              {item.severity === "critical" ? "Nghiêm trọng" : "Cảnh báo"}</span></td>
            <td className="p-3"><span className={item.state === "resolved" ? "text-emerald-700" : "text-slate-700"}>
              {item.state === "resolved" ? "Đã giải quyết" : item.is_snoozed ? "Đang tạm ẩn" : item.acknowledged_at ? "Đã xem" : "Chưa xem"}
            </span></td>
            <td className="p-3 tabular-nums text-slate-500">{fmt(item.last_seen_at)}</td>
            <td className="p-3"><div className="flex gap-1.5">
              <button type="button" className={button} disabled={historyLoading} onClick={() => void openHistory(item)}>Lịch sử</button>
              <button type="button" className={button} disabled={item.state !== "open" || !!item.acknowledged_at || busyId !== null}
                onClick={() => void act(item, "acknowledge")}><CheckCheck size={13}/> Đã xem</button>
              <button type="button" className={button} disabled={item.state !== "open" || busyId !== null}
                onClick={() => void act(item, "snooze")}><BellOff size={13}/> Tạm ẩn 60p</button>
            </div></td>
          </tr>)}</tbody>
        </table>
      </div>
      {history && <div className="border-t border-slate-100 bg-slate-50 p-4 text-xs">
        <div className="flex justify-between gap-3"><h2 className="font-semibold text-slate-800">Lịch sử sự kiện · {history.alert_id.slice(0, 8)}</h2>
          <button type="button" className={button} onClick={() => setHistory(null)}>Đóng</button></div>
        <div className="mt-2 space-y-1 text-slate-600">{history.events.map(event =>
          <p key={event.id}>{fmt(event.recorded_at)} · {event.kind}</p>)}</div>
        {history.pagination.has_next && <p className="mt-2 text-slate-500">Chỉ hiển thị 20 sự kiện mới nhất. Lịch sử đầy đủ có thể đọc qua API phân trang.</p>}
      </div>}
      {inbox && inbox.items.length === 0 && <p className="p-6 text-center text-xs text-slate-500">
        {inbox.scan_stale ? "Chưa có dữ liệu quét đáng tin cậy." : "Không có cảnh báo trong bộ lọc này."}
      </p>}
      <div className="flex items-center justify-between border-t border-slate-100 p-3">
        <p className="text-xs text-slate-500">Trang {page} / {inbox?.pagination.total_pages ?? 1}</p>
        <div className="flex gap-2">
          <button type="button" aria-label="Trang trước" className={button} disabled={loading || !inbox?.pagination.has_previous} onClick={() => setPage(v => v - 1)}><ChevronLeft size={14}/></button>
          <button type="button" aria-label="Trang sau" className={button} disabled={loading || !inbox?.pagination.has_next} onClick={() => setPage(v => v + 1)}><ChevronRight size={14}/></button>
        </div>
      </div>
    </div>
  </section>;
}
