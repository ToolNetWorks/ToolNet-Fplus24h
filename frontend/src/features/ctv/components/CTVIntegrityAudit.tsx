"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ClipboardCheck, RefreshCw, ShieldAlert } from "lucide-react";
import { getIntegrityAudit, type IntegrityAudit } from "../api/integrity-audit";

const checkNames: Record<string, string> = {
  JOB_FOREIGN_RESOURCE: "Job tham chiếu tài nguyên Pipeline khác",
  PUBLISHED_MISSING_ATTEMPT: "Job thành công chưa có lượt xử lý",
  ATTEMPT_FOREIGN_RESOURCE: "Lượt xử lý sử dụng tài nguyên Pipeline khác",
  PUBLISHED_ATTEMPT_NOT_FINAL: "Lượt xử lý cuối chưa được xác nhận hoàn tất",
  PUBLISHED_WITHOUT_POST_ID: "Job thành công thiếu mã bài đăng",
  PUBLISHED_WITHOUT_FINAL_TIME: "Job thành công thiếu thời gian kết thúc",
  PUBLISHED_MEDIA_NOT_CONSUMED: "Ảnh chưa được ghi nhận sử dụng dù Job đã hoàn tất",
  PUBLISHED_WITHOUT_TRUST_CHAIN: "Job thành công thiếu liên kết xác minh độc lập",
  PUBLISHED_TRUST_CHAIN_MISMATCH: "Mã bài hoặc Account/Group không khớp chứng cứ",
  PUBLISHED_WITHOUT_VERIFIED_READBACK: "Không có lượt đọc lại xác minh độc lập",
  UNVERIFIED_MEDIA_ALREADY_CONSUMED: "Ảnh đã được tiêu thụ dù Job chưa xác minh",
  EXPIRED_LEASE_NOT_QUARANTINED: "Worker quá hạn chưa được đưa vào đối soát",
  UNRESOLVED_JOB_OVER_48H: "Job chưa rõ kết quả quá 48 giờ",
  BATCH_FOREIGN_SCHEDULE: "Batch thuộc lịch của Pipeline khác",
  BATCH_ASSIGNMENT_COUNT_MISMATCH: "Số Job trong Batch không đúng",
  ASSIGNMENT_FOREIGN_RESOURCE: "Phân công chứa tài nguyên ngoài Pipeline",
  ASSIGNMENT_JOB_IDENTITY_MISMATCH: "Account/Group không khớp Job",
  ASSIGNMENT_PROXY_ACCOUNT_MISMATCH: "Proxy không thuộc Account đã phân công",
  SUBMISSION_JOB_IDENTITY_MISMATCH: "Thông tin nộp bài không khớp Job",
  RECEIPT_JOB_MISMATCH: "Biên nhận xác minh không khớp Job",
  CASE_FOREIGN_JOB: "Hồ sơ có Job ngoài Pipeline",
  CLOSED_CASE_WITH_UNRESOLVED_JOB: "Hồ sơ đóng khi Job chưa có kết quả hợp lệ",
  PROXY_PIN_FOREIGN_RESOURCE: "Proxy ghim sai Pipeline hoặc Account",
  PROXY_EXIT_IP_CHANGED: "IP hiện tại khác IP đã ghim",
  SCHEDULER_OVERDUE: "Scheduler quá hạn xử lý",
  READBACK_FOREIGN_JOB: "Nhật ký xác minh chứa Job ngoài Pipeline",
};

export default function CTVIntegrityAudit({ pipelineId }: { pipelineId: string }) {
  const [data, setData] = useState<IntegrityAudit | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    getIntegrityAudit(pipelineId, 100, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setData(value); })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setData(null);
          setError(cause instanceof Error ? cause.message : "Không thể kiểm toán.");
        }
      })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [pipelineId, revision]);

  const attention = data?.status === "attention_required";
  const incomplete = data?.status === "incomplete";
  return <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Kiểm toán nhất quán Pipeline">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><ClipboardCheck size={18} /> Kiểm toán nhất quán Pipeline</h2>
        <p className="mt-1 text-xs text-slate-500">Chỉ đọc dữ liệu Neon. Không thay đổi Job, không xác nhận bài Facebook.</p>
      </div>
      <button type="button" onClick={() => setRevision((n) => n + 1)} disabled={busy} className="inline-flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-xs disabled:opacity-50"><RefreshCw size={14}/>{busy ? "Đang kiểm tra..." : "Kiểm tra lại"}</button>
    </div>
    {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">{error}</p>}
    {data && <>
      <p role="status" className={`flex items-center gap-2 text-xs font-semibold ${attention || incomplete ? "text-amber-800" : "text-slate-700"}`}>
        {attention || incomplete ? <ShieldAlert size={16}/> : <ClipboardCheck size={16}/>}
        {incomplete ? "Chưa kiểm tra đầy đủ — không kết luận hệ thống an toàn" : attention ? "Phát hiện vấn đề cần kiểm tra" : "Dữ liệu trong phạm vi quét nhất quán"}
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {([ ["Job tổng", data.summary.total], ["Chưa xác minh", data.summary.uncertain], ["Nghiêm trọng", data.summary.critical], ["Cảnh báo", data.summary.warnings] ] as const).map(([label, count]) =>
          <div key={label} className="rounded-lg border border-slate-100 bg-slate-50 p-3 text-xs"><p className="text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold tabular-nums">{count.toLocaleString("vi-VN")}</p></div>
        )}
      </div>
      {data.truncated_categories.length > 0 && <p className="flex items-center gap-2 text-xs text-amber-800"><AlertTriangle size={15}/> Vượt giới hạn 100 bản ghi cho: {data.truncated_categories.join(", ")}. Dùng CLI tăng --limit để kiểm toán đầy đủ.</p>}
      {data.findings.length ? <div className="max-h-80 overflow-auto rounded-lg border border-slate-100">
        <table className="w-full min-w-[540px] text-left text-xs"><thead><tr className="bg-slate-50 text-slate-500"><th className="px-3 py-2">Mức độ</th><th className="px-3 py-2">Vấn đề</th><th className="px-3 py-2">Đối tượng</th></tr></thead><tbody>
          {data.findings.map((finding, index) => <tr key={`${finding.object_id}-${finding.code}-${index}`} className="border-t border-slate-100"><td className="px-3 py-2">{finding.severity === "critical" ? "Nghiêm trọng" : "Cảnh báo"}</td><td className="px-3 py-2">{checkNames[finding.code] ?? finding.code}</td><td className="px-3 py-2 font-mono" title={finding.object_id}>{finding.object_type} · {finding.object_id.slice(0, 8)}</td></tr>)}
        </tbody></table></div> : <p className="text-xs text-slate-500">Chưa phát hiện sai lệch trong phạm vi dữ liệu đã quét.</p>}
      <p className="text-[11px] text-slate-500">Không phải công cụ kiểm chứng bài đã hiển thị trên Facebook. Kết quả có giới hạn theo số bản ghi được kiểm tra.</p>
    </>}
  </section>;
}
