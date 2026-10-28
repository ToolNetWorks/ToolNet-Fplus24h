"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ChevronLeft, ChevronRight, Plus, RefreshCw, X } from "lucide-react";
import {
  createPublishingJob, cancelPublishingJob, getPublishingJob,
  listPublishingJobs, type PublishingJob, type JobList, type JobState,
  type JobAttempt,
} from "../api/publishing-jobs";
import { searchFacebookAccounts, type ProxyAccount } from "../api/proxies";
import { listGroups, type FacebookGroup } from "@/features/facebook-groups/api/groups";

const names: Record<JobState, string> = {
  queued: "Đang chờ", claimed: "Worker đang xử lý", ready: "Đã chuẩn bị ảnh",
  dispatching: "Đang gửi", uncertain: "Chờ đối soát",
  published: "Đã đăng", failed: "Lỗi", cancelled: "Đã hủy",
};
const input = "w-full rounded-md border border-slate-200 bg-white px-3 py-2.5 text-xs outline-none focus:border-blue-500";
const errorText = (error: unknown) => error instanceof Error ? error.message : "Không thể thực hiện yêu cầu.";
const formatted = (date: string) => new Date(date).toLocaleString("vi-VN");

export default function CTVPublishingJobs({ pipelineId }: { pipelineId: string }) {
  const [result, setResult] = useState<JobList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [state, setState] = useState("all");
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [modal, setModal] = useState(false);
  const [accounts, setAccounts] = useState<ProxyAccount[]>([]);
  const [groups, setGroups] = useState<FacebookGroup[]>([]);
  const [optionError, setOptionError] = useState("");
  const [optionLoading, setOptionLoading] = useState(false);
  const [accountSearch, setAccountSearch] = useState("");
  const [groupSearch, setGroupSearch] = useState("");
  const [accountId, setAccountId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [caption, setCaption] = useState("");
  const [scheduledLocal, setScheduledLocal] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<(PublishingJob & { attempts: JobAttempt[] }) | null>(null);

  const refresh = () => setRevision((v) => v + 1);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    listPublishingJobs(pipelineId, { page, pageSize, state, search }, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setResult(data); })
      .catch((cause: unknown) => { if (!controller.signal.aborted) { setResult(null); setError(errorText(cause)); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [pipelineId, page, pageSize, state, search, revision]);

  useEffect(() => {
    if (!modal) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setOptionLoading(true); setOptionError("");
      Promise.all([
        searchFacebookAccounts(pipelineId, accountSearch, controller.signal),
        listGroups(pipelineId, { page: 1, pageSize: 50, search: groupSearch, enabled: "true" }, controller.signal),
      ])
        .then(([a, g]) => { if (!controller.signal.aborted) { setAccounts(a); setGroups(g.data); } })
        .catch((cause: unknown) => { if (!controller.signal.aborted) setOptionError(errorText(cause)); })
        .finally(() => { if (!controller.signal.aborted) setOptionLoading(false); });
    }, 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [pipelineId, modal, accountSearch, groupSearch]);

  function openCreate() {
    setKey(crypto.randomUUID()); setAccountId(""); setGroupId(""); setCaption("");
    setScheduledLocal(""); setAccountSearch(""); setGroupSearch(""); setOptionError(""); setModal(true);
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !accountId || !groupId || !key) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const payload = {
        account_id: accountId, group_id: groupId, caption, request_key: key,
        max_attempts: 3,
        ...(scheduledLocal ? { scheduled_at: new Date(scheduledLocal).toISOString() } : {}),
      };
      const job = await createPublishingJob(pipelineId, payload);
      setModal(false); setNotice(`Đã tạo Job ${job.id.slice(0, 8)}. Chưa đăng Facebook.`);
      setPage(1); setState("all"); setSearch(""); setSearchInput(""); refresh();
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }

  async function cancel(job: PublishingJob) {
    if (busy || !window.confirm("Hủy Job đang chờ?")) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await cancelPublishingJob(pipelineId, job.id);
      setNotice("Đã hủy Job."); refresh();
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }

  async function showDetail(job: PublishingJob) {
    setBusy(true); setError("");
    try { setSelected(await getPublishingJob(pipelineId, job.id)); }
    catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }

  const items = result?.data ?? [];
  const pag = result?.pagination;
  return <section className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Lịch đăng bài & Hàng đợi</h1>
        <p className="mt-1 text-xs text-slate-500">Job được lưu trong Pipeline. Worker hiện chỉ chuẩn bị ảnh, chưa đăng Facebook.</p>
      </div>
      <button type="button" onClick={openCreate} className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white">
        <Plus size={15}/> Tạo Job
      </button>
    </div>
    {notice && <p role="status" className="rounded-md bg-blue-50 p-3 text-xs text-blue-700">{notice}</p>}
    {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">{error}</p>}
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap gap-4 border-b border-slate-100 p-4 text-xs text-slate-600">
        <span>Tổng: <b>{result?.summary.total ?? "—"}</b></span>
        <span>Chờ: <b>{result?.summary.queued ?? "—"}</b></span>
        <span>Sẵn sàng: <b>{result?.summary.ready ?? "—"}</b></span>
        <span>Cần đối soát: <b>{result?.summary.uncertain ?? "—"}</b></span>
        <span>Đã xác minh: <b>{result?.summary.published ?? "—"}</b></span>
      </div>
      <div className="flex flex-wrap gap-2 border-b border-slate-100 p-3">
        <form className="flex min-w-[180px] flex-1 gap-2" onSubmit={(e) => {e.preventDefault(); setPage(1); setSearch(searchInput.trim());}}>
          <input value={searchInput} maxLength={100} onChange={(e) => setSearchInput(e.target.value)} placeholder="Tìm caption, Job, Group..." className={input}/>
          <button className="rounded-md border px-3 text-xs" type="submit">Tìm</button>
        </form>
        <select aria-label="Lọc trạng thái Job" className={`${input} w-auto`} value={state} onChange={(e) => {setState(e.target.value);setPage(1);}}>
          <option value="all">Tất cả trạng thái</option>
          {Object.entries(names).map(([k, v]) => <option value={k} key={k}>{v}</option>)}
        </select>
        <select aria-label="Số Job mỗi trang" className={`${input} w-auto`} value={pageSize} onChange={(e) => {setPageSize(Number(e.target.value));setPage(1);}}>
          <option value={10}>10 dòng</option><option value={20}>20 dòng</option><option value={50}>50 dòng</option>
        </select>
        <button type="button" aria-label="Làm mới" onClick={refresh} className="rounded-md border p-2"><RefreshCw size={15}/></button>
      </div>
      <div className="overflow-x-auto"><table className="w-full min-w-[1000px] text-left text-xs">
        <thead className="bg-slate-50 text-slate-600"><tr>{["Job", "Account", "Group", "Thời gian chạy", "Trạng thái", "Số lần", "Thao tác"].map(x=><th key={x} className="px-3 py-3">{x}</th>)}</tr></thead>
        <tbody className="divide-y divide-slate-100">
          {loading ? <tr><td colSpan={7} className="p-10 text-center">Đang tải...</td></tr> : items.length === 0 ?
          <tr><td colSpan={7} className="p-10 text-center text-slate-500">Chưa có Job phù hợp.</td></tr> :
          items.map((job) => <tr key={job.id} className="hover:bg-slate-50">
            <td className="px-3 py-3"><p className="font-mono font-semibold">{job.id.slice(0, 8)}</p><p className="max-w-48 truncate text-slate-500" title={job.caption}>{job.caption || "Không có caption"}</p></td>
            <td className="px-3 py-3">{job.account.label}</td>
            <td className="px-3 py-3">{job.group.name}</td>
            <td className="px-3 py-3">{formatted(job.scheduled_at)}</td>
            <td className="px-3 py-3"><span className="rounded-full bg-slate-100 px-2 py-1 font-medium">{names[job.state] ?? job.state}</span></td>
            <td className="px-3 py-3">{job.attempt_count}/{job.max_attempts}</td>
            <td className="px-3 py-3"><div className="flex gap-2">
              <button disabled={busy} onClick={() => void showDetail(job)} className="rounded border px-2 py-1.5 disabled:opacity-40">Chi tiết</button>
              {job.state === "queued" && <button disabled={busy} onClick={() => void cancel(job)} className="rounded border border-red-200 px-2 py-1.5 text-red-700 disabled:opacity-40">Hủy</button>}
            </div></td>
          </tr>)}
        </tbody>
      </table></div>
      <div className="flex items-center justify-between border-t p-4 text-xs text-slate-500">
        <span>{pag?.total ?? "—"} Job</span>
        <div className="flex items-center gap-3">
          <button type="button" aria-label="Trang trước" disabled={!pag?.has_previous || loading} onClick={() => setPage((v) => Math.max(1,v-1))} className="rounded border p-2 disabled:opacity-30"><ChevronLeft size={15}/></button>
          <span>{pag ? `${pag.page}/${pag.total_pages}` : "—"}</span>
          <button type="button" aria-label="Trang sau" disabled={!pag?.has_next || loading} onClick={() => setPage((v) => v+1)} className="rounded border p-2 disabled:opacity-30"><ChevronRight size={15}/></button>
        </div>
      </div>
    </div>
    {modal && <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-3">
      <form onSubmit={(e) => void create(e)} role="dialog" aria-modal="true" aria-label="Tạo Publishing Job" className="max-h-[90dvh] w-full max-w-lg space-y-3 overflow-y-auto rounded-xl bg-white p-5 shadow-xl">
        <div className="flex items-center justify-between"><h2 className="text-lg font-bold">Tạo Job đăng bài</h2><button type="button" disabled={busy} aria-label="Đóng" onClick={() => setModal(false)}><X size={18}/></button></div>
        <p className="text-xs text-amber-700">Tạo Job chỉ lưu vào hàng đợi, chưa đăng lên Facebook.</p>
        <label className="block text-xs">Tìm tài khoản Facebook<input className={`${input} mt-1`} value={accountSearch} onChange={(e) => setAccountSearch(e.target.value)} maxLength={100} placeholder="Tìm tên tài khoản"/></label>
        <label className="block text-xs">Tài khoản Facebook
          <select className={`${input} mt-1`} required value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Chọn tài khoản</option>{accounts.map((a)=><option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
        </label>
        <label className="block text-xs">Tìm Group<input className={`${input} mt-1`} value={groupSearch} onChange={(e) => setGroupSearch(e.target.value)} maxLength={100}/></label>
        <label className="block text-xs">Group đích
          <select className={`${input} mt-1`} required value={groupId} onChange={(e) => setGroupId(e.target.value)}>
            <option value="">Chọn Group</option>{groups.map((g)=><option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
        </label>
        <label className="block text-xs">Caption<textarea className={`${input} mt-1`} rows={4} maxLength={5000} value={caption} onChange={(e) => setCaption(e.target.value)} placeholder="Nội dung bài đăng"/></label>
        <label className="block text-xs">Thời gian đăng (để trống = ngay khi worker sẵn sàng)
          <input className={`${input} mt-1`} type="datetime-local" value={scheduledLocal} onChange={(e) => setScheduledLocal(e.target.value)}/>
        </label>
        {optionLoading && <p className="text-xs text-slate-500">Đang tải tài khoản/Group...</p>}
        {optionError && <p role="alert" className="text-xs text-red-700">{optionError}</p>}
        {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
        <div className="flex justify-end gap-2"><button type="button" disabled={busy} onClick={() => setModal(false)} className="rounded border px-4 py-2 text-xs">Hủy</button>
          <button type="submit" disabled={busy || !accountId || !groupId} className="rounded bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50">{busy ? "Đang lưu..." : "Tạo Job"}</button>
        </div>
      </form>
    </div>}
    {selected && <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-3">
      <div role="dialog" aria-modal="true" aria-label="Chi tiết Publishing Job" className="max-h-[90dvh] w-full max-w-lg space-y-3 overflow-y-auto rounded-xl bg-white p-5 shadow-xl text-xs">
        <div className="flex items-center justify-between"><h2 className="text-lg font-bold">Chi tiết Job</h2><button type="button" aria-label="Đóng" onClick={() => setSelected(null)}><X size={18}/></button></div>
        <p className="break-all font-mono">{selected.id}</p>
        <p>Trạng thái: {names[selected.state] ?? selected.state}</p>
        <p>Group: {selected.group.name}</p><p>Tài khoản: {selected.account.label}</p>
        <p>Đến hạn: {formatted(selected.scheduled_at)}</p>
        <p>Lỗi: {selected.error_code ?? "—"}</p>
        <p>Mã bài đăng đã xác minh: {selected.external_post_id ?? "—"}</p>
        <h3 className="font-semibold">Lịch sử lần thử</h3>
        {selected.attempts.length === 0 ? <p>Chưa có lần thử.</p> : selected.attempts.map((a) => <p key={a.number} className="rounded bg-slate-50 p-2">Lần {a.number}: {a.state} — {formatted(a.started_at)}</p>)}
      </div>
    </div>}
  </section>;
}
