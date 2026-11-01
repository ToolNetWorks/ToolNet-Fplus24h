"use client";

import { useCallback, useEffect, useState } from "react";
import { getCsrfToken } from "@/features/auth/api/auth-client";

type Review = { id: string; job_id: string; state: string; account: string; group: string;
  group_url: string; text: string; digest: string; checkbox_count: number;
  checked_count: number; response_field_count: number; expires_at: string; browser_live: boolean;
  questions: { label: string; supported: boolean }[] };

export default function RulesReviewPanel({ pipelineId }: { pipelineId: string }) {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [error, setError] = useState("");
  const [consent, setConsent] = useState<Record<string, boolean>>({});
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);
  const root = `/api/v1/pipelines/${encodeURIComponent(pipelineId)}/rules-reviews/`;
  const refresh = useCallback(async () => {
    try {
      const response = await fetch(root, { credentials: "same-origin", cache: "no-store" });
      const body = await response.json();
      if (!response.ok || !body.success || !Array.isArray(body.data)) throw new Error("Không tải được quy tắc.");
      setReviews(body.data);
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Không tải được quy tắc."); }
  }, [root]);

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [refresh]);

  async function decide(review: Review, decision: "approve" | "reject") {
    if (busy || (decision === "approve" && !consent[review.id])) return;
    setBusy(true); setError("");
    try {
      const csrf = await getCsrfToken();
      const response = await fetch(`${root}${encodeURIComponent(review.job_id)}/`, {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ decision, digest: review.digest, consent: decision === "approve",
          answers: decision === "approve" ? (answers[review.id] || []) : [] }),
      });
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.message || "Không thể ghi quyết định.");
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Không thể ghi quyết định."); }
    finally { setBusy(false); }
  }

  if (!reviews.length && !error) return null;
  return <section className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-4" aria-label="Xác nhận quy tắc Facebook">
    <h2 className="font-bold">Quy tắc Facebook cần xem xét</h2>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {reviews.map((review) => <article key={review.id} className="space-y-3 rounded border bg-white p-3">
      <p className="text-sm">Tài khoản: <b>{review.account}</b> · Nhóm: <b>{review.group}</b></p>
      <p className="text-xs">Job {review.job_id} · {review.state} · Hết hạn {new Date(review.expires_at).toLocaleString("vi-VN")}</p>
      <div className="max-h-72 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 text-sm">{review.text}</div>
      {!review.browser_live && <p className="text-sm text-red-700">Phiên browser đã mất hoặc hết hạn. Bài cần được đối soát; không gửi lại.</p>}
      {review.questions.map((question, index) => question.supported && <label key={index} className="block space-y-1 text-sm">
        <span>{question.label}</span><textarea maxLength={500} value={answers[review.id]?.[index] || ""}
          onChange={(event) => setAnswers((old) => { const values = [...(old[review.id] || [])]; values[index] = event.target.value; return { ...old, [review.id]: values }; })}
          className="block w-full rounded border p-2" /></label>)}
      {(review.questions.length !== review.response_field_count || review.questions.some((q) => !q.supported)) &&
        <p className="text-sm text-red-700">Facebook yêu cầu câu hỏi chưa hỗ trợ. Không gửi lại bài; cần đối soát thủ công.</p>}
      {review.state === "pending" && <>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={!!consent[review.id]}
          onChange={(event) => setConsent((old) => ({ ...old, [review.id]: event.target.checked }))} />
          <span>Tôi đã đọc và đồng ý toàn bộ nội dung trên, bao gồm tham gia nhóm nếu Facebook yêu cầu.</span></label>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy || !consent[review.id] || !review.browser_live ||
            review.questions.length !== review.response_field_count || review.questions.some((q) => !q.supported) ||
            (answers[review.id] || []).length !== review.response_field_count ||
            review.questions.some((_, index) => !answers[review.id]?.[index]?.trim())}
            onClick={() => void decide(review, "approve")} className="rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:opacity-40">Xác nhận và tiếp tục</button>
          <button type="button" disabled={busy} onClick={() => void decide(review, "reject")}
            className="rounded border border-slate-400 px-4 py-2 text-sm disabled:opacity-40">Từ chối</button>
        </div>
      </>}
    </article>)}
  </section>;
}
