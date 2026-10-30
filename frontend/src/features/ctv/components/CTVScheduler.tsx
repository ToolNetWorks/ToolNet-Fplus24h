"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { CalendarClock, CheckCircle2, ChevronLeft, ChevronRight, Eye, History, Plus, RefreshCw, Save, ShieldAlert, ShieldCheck } from "lucide-react";
import { searchFacebookAccounts, type ProxyAccount } from "../api/proxies";
import { listGroups, type FacebookGroup } from "@/features/facebook-groups/api/groups";
import { captionAPI, type CaptionConfig } from "../api/caption-engine";
import {
  createSchedule, listSchedules, updateSchedule, previewSchedule, runSchedule,
  listScheduleBatches, listEligibilities, saveEligibility,
  listGroupHealth, saveGroupHealth,
  type PipelineSchedule, type ScheduleWrite, type SchedulePreview,
  type ScheduledBatch, type EligibilityRecord, type EligibilityWrite,
  type GroupHealth, type EligibilityState, type HealthState,
} from "../api/scheduler";

type View = "schedules" | "eligibility" | "health" | "batches";
type FormSchedule = Omit<ScheduleWrite, "start_at"> & { start_at_local: string };

const inputClass = "w-full rounded-md border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-800 outline-none focus:border-blue-500 disabled:bg-slate-100";
const labelClass = "block space-y-1 text-xs font-medium text-slate-700";
const btn = "inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40";
const primaryBtn = "inline-flex items-center justify-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40";
const todayLocal = () => toInputDate(new Date().toISOString());
const timeLabel = (value?: string | null) => value ? new Date(value).toLocaleString("vi-VN") : "—";
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "Không thể xử lý yêu cầu.";

function toInputDate(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
function newForm(): FormSchedule {
  return {
    name: "", enabled: false, interval_minutes: 1440,
    max_groups_per_run: 10, timezone_name: "Asia/Ho_Chi_Minh",
    start_at_local: todayLocal(), caption_template: "",
    require_anonymous: true, require_nonmember: false,
  };
}
function fromSchedule(row: PipelineSchedule): FormSchedule {
  return {
    name: row.name, enabled: row.enabled,
    interval_minutes: row.interval_minutes, max_groups_per_run: row.max_groups_per_run,
    timezone_name: row.timezone_name, start_at_local: toInputDate(row.start_at),
    caption_template: row.caption_template,
    require_anonymous: row.require_anonymous, require_nonmember: row.require_nonmember,
  };
}


function serializeDraft(draft: FormSchedule, captionConfig: CaptionConfig | null): ScheduleWrite {
  const aiEnabled = captionConfig?.enabled && captionConfig?.auto_generate && captionConfig?.auto_approve;
  return {
    name: draft.name.trim(), enabled: draft.enabled,
    interval_minutes: draft.interval_minutes, max_groups_per_run: draft.max_groups_per_run,
    timezone_name: draft.timezone_name.trim(),
    start_at: new Date(draft.start_at_local).toISOString(),
    caption_template: aiEnabled ? '' : draft.caption_template.trim(),
    // Both requirements are deliberately mandatory in this CTV workflow.
    require_anonymous: true, require_nonmember: false,
  };
}
const reasonLabel: Record<string, string> = {
  BATCH_LIMIT: "Đã đạt số Group tối đa mỗi lượt",
  GROUP_DISABLED: "Group đang tắt",
  GROUP_PAUSED: "Group đang tạm dừng",
  GROUP_UNAVAILABLE: "Group được xác minh không khả dụng",
  GROUP_HAS_PENDING_JOB: "Group còn Job chưa hoàn tất",
  GROUP_COOLDOWN: "Group chưa qua thời gian giãn cách",
  ACCOUNT_PROXY_NOT_READY: "Account/Proxy không đủ điều kiện",
  NO_VERIFIED_ELIGIBLE_ACCOUNT: "Chưa xác minh quyền đăng với Account",
  ACCOUNT_CAPACITY_EXHAUSTED: "Account đã đạt giới hạn nội bộ",
  CAPTION_TOO_LONG: "Caption vượt 5.000 ký tự",
};
const eligibilityName: Record<EligibilityState, string> = { unknown: "Chưa xác minh", verified: "Đã kiểm tra", blocked: "Không đủ điều kiện" };
const healthName: Record<HealthState, string> = { active: "Đang xem xét", paused: "Tạm dừng", unavailable: "Không khả dụng" };
const headingClass = "text-sm font-semibold text-slate-900";

export default function CTVScheduler({ pipelineId, onDirtyChange }: {
  pipelineId: string;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [view, setView] = useState<View>("schedules");
  const [schedules, setSchedules] = useState<PipelineSchedule[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<FormSchedule | null>(null);
  const [baseline, setBaseline] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [preview, setPreview] = useState<SchedulePreview | null>(null);
  const [batches, setBatches] = useState<ScheduledBatch[]>([]);
  const [loadingBatches, setLoadingBatches] = useState(false);
  const [eligibilities, setEligibilities] = useState<EligibilityRecord[]>([]);
  const [health, setHealth] = useState<GroupHealth[]>([]);
  const [referenceLoading, setReferenceLoading] = useState(false);
  const [accountSearch, setAccountSearch] = useState("");
  const [groupSearch, setGroupSearch] = useState("");
  const [groupPage, setGroupPage] = useState(1);
  const [accounts, setAccounts] = useState<ProxyAccount[]>([]);
  const [groups, setGroups] = useState<FacebookGroup[]>([]);
  const [groupsTotalPages, setGroupsTotalPages] = useState(1);
  const [accountId, setAccountId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [eligState, setEligState] = useState<EligibilityState>("unknown");
  const [canAnon, setCanAnon] = useState(false);
  const [canNonmember, setCanNonmember] = useState(false);
  const [proof, setProof] = useState("");
  const [validDays, setValidDays] = useState(7);
  const [healthGroupId, setHealthGroupId] = useState("");
  const [healthState, setHealthState] = useState<HealthState>("active");
  const [healthCode, setHealthCode] = useState("");
  const [healthEvidence, setHealthEvidence] = useState("");
  const [reviewAt, setReviewAt] = useState("");
  const [captionConfig, setCaptionConfig] = useState<CaptionConfig | null>(null);
  const [captionConfigLoading, setCaptionConfigLoading] = useState(false);

  const aiCaptionEnabled = captionConfig?.enabled && captionConfig?.auto_generate && captionConfig?.auto_approve;

  const selected = schedules.find((row) => row.id === selectedId) ?? null;
  const original = selected ? fromSchedule(selected) : newForm();
  const dirty = draft !== null && JSON.stringify(draft) !== baseline;
  const scheduleIsSaved = !creating && !!selected;
  const canEditSchedule = draft !== null && (creating || !!selected);
  const groupNames = useMemo(() => new Map(groups.map((g) => [g.id, g.name])), [groups]);
  const accountNames = useMemo(() => new Map(accounts.map((a) => [a.id, a.label])), [accounts]);

  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    function warn(event: BeforeUnloadEvent) { event.preventDefault(); event.returnValue = ""; }
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    listSchedules(pipelineId, controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        setSchedules(rows);
        setSelectedId((previous) => rows.some((r) => r.id === previous) ? previous : (rows[0]?.id ?? ""));
      })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setError(errorText(cause)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [pipelineId, revision]);

  // Switch form only when the selected schedule changes. On save, explicitly
  // sync the baseline; do not discard edits due to background fetches.
  useEffect(() => {
    if (creating) return;
    const row = schedules.find((item) => item.id === selectedId);
    if (!row) { setDraft(null); setBaseline(""); return; }
    const next = fromSchedule(row);
    setDraft(next); setBaseline(JSON.stringify(next));
    setPreview(null);
  }, [selectedId, creating]);

  useEffect(() => {
    const controller = new AbortController();
    setCaptionConfigLoading(true);
    captionAPI.settings(pipelineId)
      .then((cfg) => {
        if (controller.signal.aborted) return;
        setCaptionConfig(cfg);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setCaptionConfig(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setCaptionConfigLoading(false);
      });
    return () => controller.abort();
  }, [pipelineId]);

  useEffect(() => {
    if (view !== "eligibility" && view !== "health") return;
    const controller = new AbortController();
    setReferenceLoading(true);
    Promise.all([
      listEligibilities(pipelineId, controller.signal),
      listGroupHealth(pipelineId, controller.signal),
    ]).then(([elig, h]) => {
      if (!controller.signal.aborted) { setEligibilities(elig); setHealth(h); }
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(errorText(cause));
    }).finally(() => { if (!controller.signal.aborted) setReferenceLoading(false); });
    return () => controller.abort();
  }, [pipelineId, view, revision]);

  useEffect(() => {
    if (view !== "eligibility" && view !== "health") return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      Promise.all([
        searchFacebookAccounts(pipelineId, accountSearch, controller.signal),
        listGroups(pipelineId, {
          page: groupPage, pageSize: 50, search: groupSearch, enabled: "all",
        }, controller.signal),
      ]).then(([a, g]) => {
        if (!controller.signal.aborted) {
          setAccounts(a); setGroups(g.data);
          setGroupsTotalPages(Math.max(1, g.pagination.total_pages));
        }
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(errorText(cause));
      });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [pipelineId, view, accountSearch, groupSearch, groupPage]);

  function selectSchedule(id: string) {
    if (working || (dirty && !window.confirm("Có cấu hình lịch chưa lưu. Bỏ thay đổi?"))) return;
    setCreating(false); setSelectedId(id); setPreview(null); setNotice(""); setError("");
  }
  function switchView(next: View) {
    if (view === next || working) return;
    if (dirty && !window.confirm("Có cấu hình lịch chưa lưu. Vẫn chuyển mục?")) return;
    setView(next); setError(""); setNotice("");
  }
  function refresh() {
    if (working || (dirty && !window.confirm("Có thay đổi chưa lưu. Tải lại sẽ bỏ các thay đổi đó. Tiếp tục?"))) return;
    setCreating(false); setPreview(null); setRevision((n) => n + 1);
    setError(""); setNotice("");
  }
  function createNew() {
    if (working || (dirty && !window.confirm("Bỏ thay đổi lịch hiện tại?"))) return;
    const next = newForm();
    setDraft(next); setBaseline(JSON.stringify(next)); setCreating(true);
    setPreview(null); setView("schedules"); setNotice(""); setError("");
  }
  function setField<K extends keyof FormSchedule>(key: K, value: FormSchedule[K]) {
    setDraft((old) => old ? { ...old, [key]: value } : old);
    setPreview(null); setError("");
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || working) return;
    if (!draft.name.trim()) {
      setError("Cần tên lịch.");
      return;
    }
    if (!aiCaptionEnabled && !draft.caption_template.trim()) {
      setError("Cần mẫu caption đã duyệt.");
      return;
    }
    if (!draft.start_at_local || !Number.isFinite(new Date(draft.start_at_local).getTime())) {
      setError("Thời điểm bắt đầu không hợp lệ.");
      return;
    }
    if (!creating && !selected) return;
    const payload = serializeDraft(draft, captionConfig);
    setWorking(true); setError(""); setNotice("");
    try {
      let saved: PipelineSchedule;
      if (creating) {
        saved = await createSchedule(pipelineId, { ...payload, enabled: false });
        setNotice("Đã tạo lịch ở trạng thái Tắt. Bật lịch riêng trước khi tạo batch.");
      } else {
        // Avoid sending unchanged start_at: the backend disallows changing it
        // after batches have been created, even when the value is identical.
        const changes: Partial<ScheduleWrite> = {};
        const current = serializeDraft(original, captionConfig);
        for (const key of Object.keys(payload) as (keyof ScheduleWrite)[]) {
          if (payload[key] !== current[key] || ((key === "require_anonymous" || key === "require_nonmember") && selected?.[key] !== true)) {
            Object.assign(changes, { [key]: payload[key] });
          }
        }
        if (Object.keys(changes).length === 0) {
          setNotice("Không có thay đổi để lưu."); return;
        }
        saved = await updateSchedule(pipelineId, selected!.id, changes);
        setNotice("Đã lưu cấu hình lịch.");
      }
      const next = fromSchedule(saved);
      setSchedules((current) => [saved, ...current.filter((row) => row.id !== saved.id)]);
      setCreating(false); setSelectedId(saved.id); setDraft(next);
      setBaseline(JSON.stringify(next)); setPreview(null);
    } catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  async function toggleSchedule() {
    if (!selected || working || dirty) {
      setError("Lưu hoặc bỏ các thay đổi đang chỉnh sửa trước khi bật/tắt lịch."); return;
    }
    if (!window.confirm(selected.enabled
      ? "Tắt lịch đăng này? Các Job đã tạo vẫn còn trong hàng đợi."
      : "Bật lịch đăng? Thao tác này không tự chạy Worker, chỉ cho phép tạo batch khi được xác nhận.")) return;
    setWorking(true); setError(""); setNotice("");
    try {
      const saved = await updateSchedule(pipelineId, selected.id, { enabled: !selected.enabled });
      const next = fromSchedule(saved);
      setSchedules((rows) => rows.map((r) => r.id === saved.id ? saved : r));
      setDraft(next); setBaseline(JSON.stringify(next)); setPreview(null);
      setNotice(saved.enabled ? "Đã bật lịch. Chưa tự tạo Job." : "Đã tắt lịch. Job đã tạo không tự hủy.");
    } catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  async function showPreview() {
    if (!selected || dirty || working) { setError("Cần lưu lịch trước khi xem trước."); return; }
    setWorking(true); setError(""); setNotice("");
    try { setPreview(await previewSchedule(pipelineId, selected.id)); }
    catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  async function run() {
    if (!selected || !selected.enabled || !preview || dirty || working) return;
    if (preview.committed) { setNotice("Batch đã tồn tại, không cần tạo lại."); return; }
    if (!window.confirm(`Xác nhận tạo ${preview.assigned_count ?? preview.assignments.length} Job cho lượt ${timeLabel(preview.slot_at)}?\n\nChỉ thêm Job vào hàng đợi Neon, KHÔNG đăng Facebook.`)) return;
    setWorking(true); setError(""); setNotice("");
    try {
      const result = await runSchedule(pipelineId, selected.id);
      setPreview(result);
      setNotice(result.committed
        ? `Đã ghi batch với ${result.assigned_count ?? result.assignments.length} Job vào hàng đợi. Chưa đăng Facebook.`
        : "Chưa đến thời điểm chạy hoặc lịch không tạo Job.");
      // Re-read saved cursor after commit without losing unsaved edits.
      const rows = await listSchedules(pipelineId);
      setSchedules(rows);
      const changed = rows.find((row) => row.id === selected.id);
      if (changed) {
        const form = fromSchedule(changed);
        setDraft(form); setBaseline(JSON.stringify(form));
      }
      setRevision((n) => n + 1);
    } catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }

  function choosePair(account: string, group: string) {
    const row = eligibilities.find((r) => r.account_id === account && r.group_id === group);
    setEligState(row?.state ?? "unknown");
    setCanAnon(row?.can_post_anonymous ?? false);
    setCanNonmember(row?.can_post_nonmember ?? false);
    setProof(row?.evidence_note ?? "");
    setValidDays(7);
  }
  async function storeEligibility(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working || !accountId || !groupId) return;
    if (eligState === "verified" && (!proof.trim() || !canAnon || !canNonmember)) {
      setError("Muốn dùng cho lịch ẩn danh/không tham gia, phải kiểm tra thực tế cả hai quyền và ghi bằng chứng."); return;
    }
    if (eligState === "verified" && !window.confirm(
      "Xác nhận bạn đã tự kiểm tra quyền đăng ẩn danh và quyền đăng khi chưa tham gia Group bằng tài khoản này?",
    )) return;
    setWorking(true); setError(""); setNotice("");
    try {
      const data: EligibilityWrite = {
        account_id: accountId, group_id: groupId, state: eligState,
        can_post_anonymous: eligState === "verified" && canAnon,
        can_post_nonmember: eligState === "verified" && canNonmember,
        evidence_note: proof.trim(), valid_days: validDays,
      };
      await saveEligibility(pipelineId, data);
      const rows = await listEligibilities(pipelineId);
      setEligibilities(rows);
      setNotice("Đã lưu điều kiện cho đúng cặp Account–Group. Đây là xác minh thủ công, không phải kiểm tra tự động Facebook.");
    } catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }
  function chooseHealth(group: string) {
    const record = health.find((r) => r.group_id === group);
    setHealthState(record?.state ?? "active");
    setHealthCode(record?.reason_code ?? "");
    setHealthEvidence(record?.evidence_note ?? "");
    setReviewAt(toInputDate(record?.review_after ?? ""));
  }
  async function storeHealth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!healthGroupId || working) return;
    if (healthState === "unavailable" && !healthEvidence.trim()) {
      setError("Cần ghi bằng chứng thực tế trước khi đánh dấu Group không khả dụng."); return;
    }
    setWorking(true); setError(""); setNotice("");
    try {
      await saveGroupHealth(pipelineId, {
        group_id: healthGroupId, state: healthState,
        reason_code: healthCode.toUpperCase().replace(/[^A-Z0-9_]/g, "").slice(0, 80),
        evidence_note: healthEvidence.trim(),
        review_after: reviewAt ? new Date(reviewAt).toISOString() : null,
      });
      setHealth(await listGroupHealth(pipelineId));
      setNotice("Đã cập nhật trạng thái Group trong Pipeline.");
    } catch (cause) { setError(errorText(cause)); }
    finally { setWorking(false); }
  }

  const sections: { key: View; label: string; icon: typeof CalendarClock }[] = [
    { key: "schedules", label: "Lịch & xem trước", icon: CalendarClock },
    { key: "eligibility", label: "Quyền Account–Group", icon: ShieldCheck },
    { key: "health", label: "Tình trạng Group", icon: ShieldAlert },
    { key: "batches", label: "Lịch sử batch", icon: History },
  ];
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Cấu hình lịch tự động</h1>
          <p className="mt-1 text-xs text-slate-500">Phân phối Account–Group và tạo Job theo lịch. Chưa tự động đăng Facebook.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" className={btn} onClick={refresh} disabled={working}><RefreshCw size={14}/> Tải lại</button>
          <button type="button" className={primaryBtn} onClick={createNew} disabled={working}><Plus size={14}/> Tạo lịch</button>
        </div>
      </div>
      <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        Chế độ bắt buộc: <b>đăng ẩn danh</b> và <b>không tham gia Group</b>. Chưa xác minh quyền của Account đối với Group sẽ không được phân phối. Tạo batch chỉ tạo Job hàng đợi, không gửi yêu cầu đến Facebook.
      </p>
      {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">{error}</p>}
      {notice && <p role="status" className="rounded-md bg-blue-50 p-3 text-xs text-blue-700">{notice}</p>}
      <div className="flex flex-wrap gap-1 border-b border-slate-200 pb-2" role="tablist" aria-label="Mục cấu hình Scheduler">
        {sections.map((section) => {
          const Icon = section.icon;
          return <button key={section.key} type="button" role="tab" aria-selected={view === section.key}
            onClick={() => switchView(section.key)} className={`inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium ${view === section.key ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-100"}`}>
            <Icon size={15}/>{section.label}
          </button>;
        })}
      </div>
      {view === "schedules" && <div className="grid gap-4 xl:grid-cols-[250px_minmax(0,1fr)]">
        <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
          <h2 className={headingClass}>Danh sách lịch ({schedules.length})</h2>
          {loading && <p className="text-xs text-slate-500">Đang tải...</p>}
          {!loading && !schedules.length && !creating && <p className="text-xs text-slate-500">Chưa có lịch. Chọn Tạo lịch.</p>}
          {creating && <div className="rounded-md border border-blue-300 bg-blue-50 p-3 text-xs font-semibold text-blue-700">Lịch mới (chưa lưu)</div>}
          {schedules.map((row) => <button type="button" key={row.id} onClick={() => selectSchedule(row.id)}
            className={`w-full rounded-md border p-3 text-left text-xs ${row.id === selectedId && !creating ? "border-blue-300 bg-blue-50" : "border-slate-100 hover:border-slate-300"}`}>
            <span className="block truncate font-semibold text-slate-800">{row.name}</span>
            <span className="mt-1 block text-slate-500">{row.enabled ? "Đã bật" : "Đang tắt"} · {row.interval_minutes} phút</span>
            <span className="mt-1 block text-slate-500">Tiếp theo: {timeLabel(row.next_run_at)}</span>
          </button>)}
        </div>
        <div className="space-y-4">
          {!canEditSchedule && <div className="rounded-lg border bg-white p-6 text-sm text-slate-500">Chọn một lịch hoặc tạo lịch mới.</div>}
          {draft && <form onSubmit={(e) => void save(e)} className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className={headingClass}>{creating ? "Tạo lịch mới" : `Cấu hình: ${selected?.name ?? ""}`}</h2>
              <div className="flex gap-2">
                {!creating && <button type="button" disabled={working || dirty} className={btn} onClick={() => void toggleSchedule()}>
                  {selected?.enabled ? "Tắt lịch" : "Bật lịch"}
                </button>}
                <button type="submit" disabled={working || (!creating && !dirty && selected?.require_anonymous === true && selected?.require_nonmember === false)} className={primaryBtn}><Save size={14}/>{working ? "Đang lưu" : "Lưu cấu hình"}</button>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className={labelClass}>Tên lịch<input required maxLength={150} className={inputClass} value={draft.name} onChange={(e) => setField("name", e.target.value)} placeholder="VD: Đợt sáng hàng ngày"/></label>
              <label className={labelClass}>Thời điểm bắt đầu (giờ trên thiết bị)<input required type="datetime-local" className={inputClass} value={draft.start_at_local} onChange={(e) => setField("start_at_local", e.target.value)}/></label>
              <label className={labelClass}>Chu kỳ chạy (phút)<input required min={60} max={10080} type="number" className={inputClass} value={draft.interval_minutes} onChange={(e) => setField("interval_minutes", Number(e.target.value))}/></label>
              <label className={labelClass}>Số Group tối đa mỗi lượt<input required type="number" min={1} max={50} className={inputClass} value={draft.max_groups_per_run} onChange={(e) => setField("max_groups_per_run", Number(e.target.value))}/></label>
              <label className={labelClass}>Múi giờ (dùng cho biến ngày trong caption)<input required maxLength={64} className={inputClass} value={draft.timezone_name} onChange={(e) => setField("timezone_name", e.target.value)} placeholder="Asia/Ho_Chi_Minh" /></label>
              <div className="space-y-2 rounded-md border border-slate-100 bg-slate-50 p-3 text-xs text-slate-600">
                <div><CheckCircle2 size={14} className="mr-1 inline text-green-600"/> Đăng ẩn danh: bắt buộc</div>
              </div>
            </div>
            {!aiCaptionEnabled && <label className={labelClass}>Mẫu caption đã duyệt<textarea required rows={4} maxLength={5000} className={inputClass} value={draft.caption_template} onChange={(e) => setField("caption_template", e.target.value)} placeholder="Nội dung {group_name} ngày {date}" />
              <span className="text-[11px] font-normal text-slate-500">Biến hỗ trợ: {"{group_name}"}, {"{date}"}. AI tự viết caption thuộc bước riêng.</span></label>}
            {aiCaptionEnabled && <div className="space-y-2 rounded-md border border-blue-100 bg-blue-50 p-3 text-xs text-blue-800">
              <div className="flex items-center gap-2 font-semibold"><CheckCircle2 size={14}/> AI Caption Engine được bật</div>
              <p>Caption sẽ được AI tạo và tự duyệt dựa trên kho mẫu của Pipeline. Không cần nhập mẫu caption thủ công.</p>
            </div>}
            <p className="text-xs text-slate-500">{creating ? "Lịch mới luôn được tạo ở trạng thái Tắt." : `Lịch đã lưu: ${timeLabel(selected?.updated_at)} · Lượt tiếp theo: ${timeLabel(selected?.next_run_at)}`}</p>
          </form>}
          {scheduleIsSaved && <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className={headingClass}>Xem trước phân phối</h2>
              <div className="flex flex-wrap gap-2">
                <button type="button" className={btn} disabled={working || dirty} onClick={() => void showPreview()}><Eye size={14}/> Xem trước</button>
                <button type="button" className={primaryBtn} disabled={working || dirty || !selected?.enabled || !preview || preview.committed} onClick={() => void run()}>
                  <CalendarClock size={14}/> Xác nhận tạo Job
                </button>
              </div>
            </div>
            {!preview && <p className="text-xs text-slate-500">Xem trước để biết Group nào sẽ được gán, Account/Proxy và lý do bỏ qua. Xem trước không ghi dữ liệu.</p>}
            {preview && <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <div className="rounded-md bg-slate-50 p-3"><p className="text-xs text-slate-500">Được phân phối</p><strong className="text-xl">{preview.assigned_count ?? preview.assignments.length}</strong></div>
                <div className="rounded-md bg-slate-50 p-3"><p className="text-xs text-slate-500">Bỏ qua</p><strong className="text-xl">{preview.skipped.length}</strong></div>
                <div className="rounded-md bg-slate-50 p-3"><p className="text-xs text-slate-500">Trạng thái</p><strong className="text-xs">{preview.committed ? "Đã tạo batch" : preview.status === "not_due" ? "Chưa đến giờ" : "Bản xem trước"}</strong></div>
              </div>
              <p className="text-xs text-slate-500">Lượt: {timeLabel(preview.slot_at)}{preview.replayed ? " · Đã tồn tại từ trước" : ""}</p>
              <h3 className="text-xs font-semibold text-slate-800">Phân phối Account – Group</h3>
              <div className="max-h-72 overflow-auto rounded-md border border-slate-200"><table className="min-w-full text-left text-xs"><thead className="sticky top-0 bg-slate-50 text-slate-600"><tr><th className="px-3 py-2">Group ID</th><th className="px-3 py-2">Account ID</th><th className="px-3 py-2">Proxy/IP</th><th className="px-3 py-2">Dự kiến</th></tr></thead><tbody>
                {preview.assignments.length === 0 ? <tr><td colSpan={4} className="px-3 py-4 text-slate-500">Không có nhóm đủ điều kiện.</td></tr> : preview.assignments.map((item, i) => <tr key={`${item.group_id}-${i}`} className="border-t"><td title={item.group_id} className="px-3 py-2 font-mono">{item.group_id.slice(0, 8)}</td><td title={item.account_id} className="px-3 py-2 font-mono">{item.account_id.slice(0, 8)}</td><td className="px-3 py-2">{item.exit_ip}</td><td className="px-3 py-2 whitespace-nowrap">{timeLabel(item.scheduled_at)}</td></tr>)}
              </tbody></table></div>
              <h3 className="text-xs font-semibold text-slate-800">Group bị bỏ qua ({preview.skipped.length})</h3>
              <div className="max-h-52 overflow-auto rounded-md border border-slate-200"><table className="min-w-full text-left text-xs"><thead className="sticky top-0 bg-slate-50"><tr><th className="px-3 py-2">Group ID</th><th className="px-3 py-2">Lý do</th></tr></thead><tbody>{preview.skipped.length === 0 ? <tr><td colSpan={2} className="px-3 py-3 text-slate-500">Không có Group bị bỏ qua.</td></tr> : preview.skipped.map((row, i) => <tr key={`${row.group_id}-${i}`} className="border-t"><td title={row.group_id} className="px-3 py-2 font-mono">{row.group_id.slice(0, 8)}</td><td className="px-3 py-2">{reasonLabel[row.code] ?? row.code}</td></tr>)}</tbody></table></div>
              {preview.committed && <p className="text-xs font-medium text-green-700">Batch đã được lưu vào Neon; đây không phải xác nhận đã đăng Facebook.</p>}
            </>}
          </div>}
        </div>
      </div>}
      {(view === "eligibility" || view === "health") && <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
          <h2 className={headingClass}>Tìm Account và Group</h2>
          <p className="text-xs text-slate-500">Lựa chọn từ tài nguyên của Pipeline. Tìm kiếm Group theo tên hoặc URL, mỗi trang tối đa 50 Group.</p>
          {view === "eligibility" && <>
            <label className={labelClass}>Tìm Account<input className={inputClass} value={accountSearch} onChange={(e) => { setAccountSearch(e.target.value); setAccountId(""); choosePair("", groupId); }} placeholder="Lọc tài khoản" maxLength={100}/></label>
            <label className={labelClass}>Account
              <select className={inputClass} value={accountId} onChange={(e) => { setAccountId(e.target.value); choosePair(e.target.value, groupId); }}>
                <option value="">Chọn Facebook Account</option>
                {accounts.map((row) => <option key={row.id} value={row.id}>{row.label}</option>)}
              </select>
            </label>
          </>}
          <label className={labelClass}>Tìm Group<input className={inputClass} value={groupSearch} onChange={(e) => { setGroupSearch(e.target.value); setGroupPage(1); setGroupId(""); setHealthGroupId(""); choosePair(accountId, ""); chooseHealth(""); }} placeholder="Tên Group hoặc liên kết" maxLength={100}/></label>
          <label className={labelClass}>Group
            <select className={inputClass} value={view === "eligibility" ? groupId : healthGroupId} onChange={(e) => {
              if (view === "eligibility") { setGroupId(e.target.value); choosePair(accountId, e.target.value); }
              else { setHealthGroupId(e.target.value); chooseHealth(e.target.value); }
            }}>
              <option value="">Chọn Group</option>
              {groups.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </label>
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Trang {groupPage}/{groupsTotalPages}</span>
            <div className="flex gap-2"><button type="button" className={btn} disabled={groupPage <= 1} onClick={() => setGroupPage((n) => n - 1)} aria-label="Trang Group trước"><ChevronLeft size={14}/></button>
              <button type="button" className={btn} disabled={groupPage >= groupsTotalPages} onClick={() => setGroupPage((n) => n + 1)} aria-label="Trang Group sau"><ChevronRight size={14}/></button></div>
          </div>
        </div>
        {view === "eligibility" ?         <form onSubmit={(e) => void storeEligibility(e)} className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
          <h2 className={headingClass}>Xác minh quyền đăng ẩn danh theo cặp Account–Group</h2>
          <p className="text-xs text-amber-700">Chỉ chọn Đã kiểm tra khi có bằng chứng thực tế về quyền đăng ẩn danh. Thành viên hay không thành viên không phải điều kiện loại trừ.</p>
          <label className={labelClass}>Trạng thái<select className={inputClass} value={eligState} onChange={(e) => setEligState(e.target.value as EligibilityState)}><option value="unknown">Chưa xác minh</option><option value="verified">Đã kiểm tra thủ công</option><option value="blocked">Không đủ điều kiện</option></select></label>
          <label className="flex items-center gap-2 text-xs text-slate-700"><input type="checkbox" checked={canAnon} onChange={(e) => setCanAnon(e.target.checked)} disabled={eligState !== "verified"}/> Đã xác minh có thể đăng ẩn danh</label>
          <label className="flex items-center gap-2 text-xs text-slate-700"><input type="checkbox" checked={canNonmember} onChange={(e) => setCanNonmember(e.target.checked)} disabled={eligState !== "verified"}/> Đã xác minh được đăng khi chưa tham gia</label>
          <label className={labelClass}>Hiệu lực xác minh (ngày)<input className={inputClass} type="number" min={1} max={30} value={validDays} onChange={(e) => setValidDays(Number(e.target.value))}/></label>
          <label className={labelClass}>Ghi chú bằng chứng<textarea className={inputClass} maxLength={500} rows={4} value={proof} onChange={(e) => setProof(e.target.value)} placeholder="Thời điểm kiểm tra, phương pháp, kết quả xác nhận..."/></label>
          <button type="submit" disabled={working || !accountId || !groupId} className={primaryBtn}><Save size={14}/> Lưu xác minh</button>
        </form> : <form onSubmit={(e) => void storeHealth(e)} className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
          <h2 className={headingClass}>Tình trạng Group</h2>
          <label className={labelClass}>Trạng thái<select className={inputClass} value={healthState} onChange={(e) => setHealthState(e.target.value as HealthState)}><option value="active">Đang xem xét đăng</option><option value="paused">Tạm dừng thủ công</option><option value="unavailable">Không khả dụng đã xác minh</option></select></label>
          <label className={labelClass}>Mã lý do<input className={inputClass} maxLength={80} value={healthCode} onChange={(e) => setHealthCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""))} placeholder="MANUAL_CHECK" /></label>
          <label className={labelClass}>Bằng chứng<textarea className={inputClass} rows={4} maxLength={500} value={healthEvidence} onChange={(e) => setHealthEvidence(e.target.value)} placeholder="Không đánh dấu Group bị vô hiệu hóa chỉ do một lần đăng thất bại."/></label>
          <label className={labelClass}>Kiểm tra lại sau (tùy chọn)<input className={inputClass} type="datetime-local" value={reviewAt} onChange={(e) => setReviewAt(e.target.value)}/></label>
          <p className="text-xs text-slate-500">Lưu ý: ngày kiểm tra lại hiện để theo dõi thủ công, chưa tự bật lại Group.</p>
          <button type="submit" disabled={working || !healthGroupId} className={primaryBtn}><Save size={14}/> Cập nhật Group</button>
        </form>}
      </div>}
      {view === "eligibility" && <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2"><h2 className={headingClass}>Các cặp đã lưu ({eligibilities.length})</h2>{referenceLoading && <span className="text-xs text-slate-500">Đang tải...</span>}</div>
        <div className="mt-3 max-h-72 overflow-auto"><table className="min-w-full text-left text-xs"><thead className="bg-slate-50"><tr><th className="px-3 py-2">Account</th><th className="px-3 py-2">Group</th><th className="px-3 py-2">Trạng thái</th><th className="px-3 py-2">Ẩn danh / Chưa tham gia</th><th className="px-3 py-2">Hết hạn</th></tr></thead><tbody>
          {eligibilities.length === 0 ? <tr><td colSpan={5} className="px-3 py-3 text-slate-500">Chưa có xác minh nào được lưu.</td></tr> : eligibilities.map((row) => <tr key={`${row.account_id}-${row.group_id}`} className="border-t"><td title={row.account_id} className="px-3 py-2">{accountNames.get(row.account_id) ?? row.account_id.slice(0, 8)}</td><td title={row.group_id} className="px-3 py-2">{groupNames.get(row.group_id) ?? row.group_id.slice(0, 8)}</td><td className="px-3 py-2">{eligibilityName[row.state]}</td><td className="px-3 py-2">{row.can_post_anonymous ? "Có" : "Không"} / {row.can_post_nonmember ? "Có" : "Không"}</td><td className="px-3 py-2 whitespace-nowrap">{timeLabel(row.expires_at)}</td></tr>)}
        </tbody></table></div><p className="mt-2 text-[11px] text-slate-500">Backend trả tối đa 1.000 bản ghi gần nhất. Tìm kiếm/bulk sẽ được mở rộng ở bước sau.</p>
      </div>}
      {view === "health" && <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className={headingClass}>Danh sách tình trạng Group ({health.length})</h2>
        <div className="mt-3 max-h-72 overflow-auto"><table className="min-w-full text-left text-xs"><thead className="bg-slate-50"><tr><th className="px-3 py-2">Group</th><th className="px-3 py-2">Trạng thái</th><th className="px-3 py-2">Lý do</th><th className="px-3 py-2">Kiểm tra lại</th></tr></thead><tbody>
          {health.length === 0 ? <tr><td colSpan={4} className="px-3 py-3 text-slate-500">Chưa có trạng thái Group được lưu.</td></tr> : health.map((row) => <tr className="border-t" key={row.group_id}><td title={row.group_id} className="px-3 py-2">{groupNames.get(row.group_id) ?? row.group_id.slice(0, 8)}</td><td className="px-3 py-2">{healthName[row.state]}</td><td className="px-3 py-2" title={row.evidence_note}>{row.reason_code || "—"}</td><td className="px-3 py-2">{timeLabel(row.review_after)}</td></tr>)}
        </tbody></table></div>
      </div>}
      {view === "batches" && <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2"><h2 className={headingClass}>Lịch sử tạo Batch</h2><span className="text-xs text-slate-500">Tối đa 50 batch gần nhất · không phải kết quả đăng Facebook</span></div>
        <label className={labelClass}>Chọn lịch<select className={inputClass} value={selectedId} onChange={(e) => selectSchedule(e.target.value)}><option value="">Chọn lịch</option>{schedules.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        {loadingBatches && <p className="text-xs text-slate-500">Đang tải batch...</p>}
        <div className="overflow-auto"><table className="min-w-full text-left text-xs"><thead className="bg-slate-50"><tr><th className="px-3 py-2">Slot</th><th className="px-3 py-2">Job đã tạo</th><th className="px-3 py-2">Group bỏ qua</th><th className="px-3 py-2">Ngày ghi nhận</th></tr></thead><tbody>
          {batches.length === 0 ? <tr><td colSpan={4} className="px-3 py-3 text-slate-500">Chưa có batch.</td></tr> : batches.map((row) => <tr key={row.id} className="border-t"><td className="px-3 py-2 whitespace-nowrap">{timeLabel(row.slot_at)}</td><td className="px-3 py-2 font-semibold">{row.assigned_count}</td><td className="px-3 py-2">{row.skipped.length}<details className="mt-1 text-slate-500"><summary className="cursor-pointer">Chi tiết</summary>{row.skipped.map((s, i) => <p key={`${s.group_id}-${i}`} className="py-0.5">{s.group_id.slice(0, 8)}: {reasonLabel[s.code] ?? s.code}</p>)}</details></td><td className="px-3 py-2 whitespace-nowrap">{timeLabel(row.created_at)}</td></tr>)}
        </tbody></table></div>
      </div>}
    </section>
  );
}
