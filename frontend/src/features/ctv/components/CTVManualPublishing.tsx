"use client";

import { useEffect, useState } from 'react';
import { Copy, ExternalLink, RefreshCw, Search, X } from 'lucide-react';
import { getCsrfToken } from '@/features/auth/api/auth-client';
import {
  listHandoffQueue,
  readManualHandoff,
  manualAction,
  manualMediaUrl,
  PUBLICATION_STATUS_LABELS,
  PUBLICATION_STATUS_COLORS,
  type PublicationStatus,
  type QueueItem,
  type HandoffQueueResponse,
  type ManualHandoff,
} from '../api/manual-handoff';
import { getJobVerification, type VerificationObservation } from '../api/post-verification';

const SELECT_OPTIONS = [
  { value: 'all', label: 'Tất cả trạng thái' },
  { value: 'awaiting_ai', label: 'Chờ AI' },
  { value: 'approved', label: 'Đã duyệt' },
  { value: 'awaiting_handoff', label: 'Chờ bàn giao' },
  { value: 'processing', label: 'Đang xử lý' },
  { value: 'awaiting_verification', label: 'Chờ xác minh' },
  { value: 'published', label: 'Thành công' },
  { value: 'failed', label: 'Thất bại' },
] as const;

const input = "w-full rounded-md border border-slate-200 bg-white px-3 py-2.5 text-xs outline-none focus:border-blue-500";

export default function CTVManualPublishing({ pipelineId }: { pipelineId: string }) {
  const [queue, setQueue] = useState<HandoffQueueResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [record, setRecord] = useState<ManualHandoff | null>(null);
  const [canPrepare, setCanPrepare] = useState(false);
  const [pending, setPending] = useState(false);
  const [verifications, setVerifications] = useState<VerificationObservation[]>([]);
  const [outcome, setOutcome] = useState<
    'submitted_reported' | 'pending_reported' | 'rejected_reported' | 'inconclusive'
  >('pending_reported');
  const [note, setNote] = useState('');

  const refresh = () => setRevision((v) => v + 1);

  function visibleItems(): QueueItem[] {
    if (!queue) return [];
    const items = queue.items;
    if (search.trim()) {
      const term = search.trim().toLowerCase();
      return items.filter((item) =>
        item.caption.toLowerCase().includes(term) ||
        item.group.name.toLowerCase().includes(term) ||
        item.account.label.toLowerCase().includes(term) ||
        item.job_id.toLowerCase().includes(term),
      );
    }
    return items;
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    listHandoffQueue(
      pipelineId,
      { page, pageSize, status: statusFilter === 'all' ? undefined : statusFilter },
      controller.signal,
    )
      .then((data) => {
        if (!controller.signal.aborted) {
          setQueue(data);
          setError('');
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setQueue(null);
          setError(cause instanceof Error ? cause.message : 'Không tải được hàng đợi bàn giao.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [pipelineId, page, pageSize, statusFilter, revision]);

  useEffect(() => {
    if (!selectedJobId) {
      setRecord(null);
      setCanPrepare(false);
      return;
    }
    const controller = new AbortController();
    setNotice('');
    readManualHandoff(pipelineId, selectedJobId, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) {
          setRecord(res.handoff);
          setCanPrepare(res.can_prepare);
          setError('');
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setRecord(null);
          setCanPrepare(false);
          setError(cause instanceof Error ? cause.message : 'Không đọc được bàn giao.');
        }
      });
    void getJobVerification(pipelineId, selectedJobId, 1, controller.signal).then((verifications) => {
      if (!controller.signal.aborted) setVerifications(verifications.observations ?? []);
    }).catch(() => {});
    return () => controller.abort();
  }, [pipelineId, selectedJobId, revision]);

  async function doAction(value: 'prepare' | 'open' | 'abandon' | 'report') {
    if (!selectedJobId || pending) return;
    if (value === 'open' && !window.confirm(
      'Xác nhận mở Facebook để tự đăng? Job sẽ được giữ ở trạng thái chưa xác minh, không được tự retry. ' +
      'Bạn phải chọn đúng Account và Group trong trình duyệt, sử dụng Proxy/IP đã được kiểm tra.'
    )) return;
    if (value === 'abandon' && !window.confirm('Chỉ hủy nếu CHƯA mở Facebook/chưa thực hiện đăng. Hủy Job này?')) return;

    const popup = value === 'open' ? window.open('about:blank', '_blank') : null;
    if (popup) popup.opener = null;

    setPending(true);
    setError('');
    setNotice('');
    try {
      const csrf = await getCsrfToken();
      let data: ManualHandoff;
      if (value === 'prepare') {
        data = await manualAction(pipelineId, selectedJobId, { action: 'prepare' }, csrf);
      } else if (value === 'report') {
        data = await manualAction(pipelineId, selectedJobId, {
          action: 'report',
          expected_version: record!.version,
          outcome, note,
        }, csrf);
      } else {
        data = await manualAction(pipelineId, selectedJobId, {
          action: value,
          expected_version: record!.version,
        }, csrf);
      }
      setRecord(data);
      setCanPrepare(false);
      setNotice('Đã lưu thao tác. Không xác nhận bài được xuất bản chỉ bằng báo cáo này.');
      if (value === 'open') {
        if (popup && !popup.closed) {
          popup.location.replace(data.group_url);
        } else {
          setNotice('Đã ghi mốc bắt đầu. Trình duyệt chặn tab mới: mở Group bằng liên kết bên dưới.');
        }
      }
      setRevision((v) => v + 1);
    } catch (e) {
      if (popup && !popup.closed) popup.close();
      setError(e instanceof Error ? e.message : 'Không xử lý được.');
    } finally {
      setPending(false);
    }
  }

  async function copyCaption() {
    if (!record) return;
    try {
      await navigator.clipboard.writeText(record.caption);
      setNotice('Đã sao chép caption.');
    } catch {
      setError('Không có quyền sao chép; hãy chọn và sao chép thủ công.');
    }
  }

  function statusBadge(status: PublicationStatus) {
    const label = PUBLICATION_STATUS_LABELS[status];
    const color = PUBLICATION_STATUS_COLORS[status];
    return (
      <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${color}`}>
        {label}
      </span>
    );
  }

  const items = visibleItems();
  const pag = queue?.pagination;

  return <section className="space-y-4" aria-label="Hàng đợi bàn giao đăng Facebook">
    <div>
      <h1 className="text-xl font-bold text-slate-900">Hàng đợi bàn giao đăng bài</h1>
      <p className="mt-1 text-xs text-slate-500">
        AI Caption tự động tạo &amp; duyệt → CTV mở Facebook để đăng thủ công → xác nhận kết quả.
        Không đăng Facebook tự động, không dùng API Groups đã ngừng hỗ trợ.
      </p>
    </div>

    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
      Facebook Groups API đăng bài đã ngừng hoạt động. CTV phải: chọn đúng Account/Group —
      mở Facebook bằng trình duyệt riêng — sử dụng ảnh đã được giữ — sao chép caption —
      đăng thủ công trong composer của Facebook. Báo cáo "đã gửi" không đồng nghĩa bài đã xuất bản.
    </div>

    {notice && <p role="status" className="rounded-md bg-blue-50 p-3 text-xs text-blue-700">{notice}</p>}
    {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">{error}</p>}

    <div className="flex flex-wrap gap-2 border-b border-slate-100 pb-2">
      <select
        aria-label="Lọc trạng thái"
        className={`${input} w-auto`}
        value={statusFilter}
        onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
      >
        {SELECT_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      <form
        className="flex min-w-[220px] flex-1 gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(searchInput.trim());
          setPage(1);
        }}
      >
        <input
          value={searchInput}
          maxLength={100}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Tìm caption, Group, Account..."
          className={input}
        />
        <button className="rounded-md border px-3 text-xs" type="submit">
          <Search size={14} className="inline" />
        </button>
      </form>
      <button
        type="button"
        aria-label="Làm mới"
        onClick={refresh}
        className="rounded-md border p-2"
      >
        <RefreshCw size={15} />
      </button>
    </div>

    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap gap-4 border-b border-slate-100 px-4 py-2 text-xs text-slate-600">
        {queue?.summary.total && Object.entries(queue.summary.total).map(([key, count]) => (
          <span key={key}>
            {PUBLICATION_STATUS_LABELS[key as PublicationStatus]}:{' '}
            <b>{count}</b>
          </span>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[1100px] text-left text-xs">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              {['Trạng thái', 'Job', 'Account', 'Group', 'Caption', 'Ảnh', 'Thời gian', 'Thao tác'].map(
                (h) => <th key={h} className="px-3 py-3">{h}</th>,
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan={8} className="p-10 text-center">Đang tải...</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={8} className="p-10 text-center text-slate-500">Chưa có Job phù hợp.</td></tr>
            ) : items.map((item) => {
              const selected = selectedJobId === item.job_id;
              return (
                <tr key={item.job_id} className="hover:bg-slate-50">
                  <td className="px-3 py-3">{statusBadge(item.unified_status as PublicationStatus)}</td>
                  <td className="px-3 py-3">
                    <p className="font-mono font-semibold">{item.job_id.slice(0, 8)}</p>
                    <p className="text-slate-500">{item.account.label}</p>
                  </td>
                  <td className="px-3 py-3">{item.group.name}</td>
                  <td className="px-3 py-3 max-w-xs truncate" title={item.caption}>
                    {item.caption || 'Không có caption'}
                    {item.caption_state && (
                      <span className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-slate-500">
                        AI: {item.caption_state}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    {item.media.length > 0 ? (
                      <span className="text-green-600">{item.media.length} ảnh</span>
                    ) : (
                      <span className="text-slate-400">Chưa có ảnh</span>
                    )}
                  </td>
                  <td className="px-3 py-3">{new Date(item.scheduled_at).toLocaleString('vi-VN')}</td>
                  <td className="px-3 py-3">
                    <div className="flex gap-2">
                      <button
                        onClick={() => setSelectedJobId(item.job_id)}
                        className="rounded border px-2 py-1.5 text-xs"
                      >
                        Chi tiết
                      </button>
                      {item.can_prepare && !item.handoff && (
                        <button
                          disabled={pending}
                          onClick={() => void doAction('prepare')}
                          className="rounded bg-blue-600 px-2 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
                        >
                          Chuẩn bị
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between border-t p-4 text-xs text-slate-500">
        <span>{pag?.total ?? '—'} Job</span>
        <div className="flex items-center gap-3">
          <button
            aria-label="Trang trước"
            disabled={!pag?.has_previous || loading}
            onClick={() => setPage((v) => Math.max(1, v - 1))}
            className="rounded border p-2 disabled:opacity-30"
          >
            ◀
          </button>
          <span>{pag ? `${pag.page}/${pag.total_pages}` : '—'}</span>
          <button
            aria-label="Trang sau"
            disabled={!pag?.has_next || loading}
            onClick={() => setPage((v) => v + 1)}
            className="rounded border p-2 disabled:opacity-30"
          >
            ▶
          </button>
        </div>
      </div>
    </div>

    {selectedJobId && record && (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-3">
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Chi tiết bàn giao"
          className="max-h-[90dvh] w-full max-w-3xl space-y-4 overflow-y-auto rounded-xl bg-white p-5 shadow-xl text-xs"
        >
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold">Chi tiết bàn giao đăng bài</h2>
            <button type="button" aria-label="Đóng" onClick={() => setSelectedJobId(null)}>
              <X size={18} />
            </button>
          </div>

          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <dt className="text-slate-500">Account được chỉ định</dt>
                <dd className="font-semibold">{record.account_label}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Group đích</dt>
                <dd className="font-semibold">{record.group_name}</dd>
              </div>
            </div>
            <div>
              <dt className="text-slate-500">Trạng thái bàn giao</dt>
              <dd>{record.state} · Job {record.job_state}</dd>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between">
              <strong className="text-xs">Caption</strong>
              <button
                type="button"
                onClick={() => void copyCaption()}
                className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium"
              >
                <Copy size={13} className="inline" /> Sao chép
              </button>
            </div>
            <textarea
              value={record.caption}
              readOnly
              rows={5}
              className="w-full rounded-md border border-slate-200 p-3 text-xs"
            />
          </div>

          <div>
            <strong className="text-xs">Ảnh đã giữ từ Album nguồn</strong>
            <div className="mt-2 flex flex-wrap gap-2">
              {record.media.map((item) => (
                <a
                  key={item.image_id}
                  href={manualMediaUrl(pipelineId, item)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-md border border-slate-200 px-3 py-2 text-xs text-blue-700"
                >
                  Ảnh {item.position} {item.available ? '· Xem / lưu' : '· Không còn khả dụng'}
                </a>
              ))}
            </div>
          </div>

          {record.state === 'prepared' && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={pending}
                onClick={() => void doAction('open')}
                className="rounded-md bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-40"
              >
                <ExternalLink size={13} className="inline" /> Mở Facebook để đăng thủ công
              </button>
              <button
                type="button"
                disabled={pending}
                onClick={() => void doAction('abandon')}
                className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium"
              >
                Hủy trước khi mở
              </button>
            </div>
          )}

          {record.state !== 'prepared' && record.state !== 'abandoned' && (
            <div className="space-y-2">
              <a
                href={record.group_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-700 underline text-xs"
              >
                Mở lại Group trên Facebook (không gửi lại bài tự động)
              </a>
            </div>
          )}

          {record.state !== 'prepared' && record.state !== 'abandoned' && (
            <div className="rounded-lg bg-slate-50 p-3 space-y-2">
              <p className="text-xs">
                Sau khi thao tác trên Facebook, ghi lại quan sát. Không điền cookie, HAR hoặc token.
              </p>
              <select
                value={outcome}
                onChange={(e) => setOutcome(e.target.value as typeof outcome)}
                className={input}
              >
                <option value="submitted_reported">Đã nhấn gửi bài</option>
                <option value="pending_reported">Bài đang chờ Group duyệt</option>
                <option value="rejected_reported">Group từ chối bài</option>
                <option value="inconclusive">Chưa xác định được kết quả</option>
              </select>
              <textarea
                maxLength={500}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                placeholder="Ghi chú đã làm sạch, tối đa 500 ký tự"
                className={input}
              />
              <button
                type="button"
                disabled={pending}
                onClick={() => void doAction('report')}
                className="rounded-md bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-40"
              >
                Lưu quan sát
              </button>
            </div>
          )}

          {verifications.length > 0 && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <strong className="text-xs">Lịch sử xác minh (quan sát)</strong>
              <div className="mt-2 space-y-1">
                {verifications.map((v) => (
                  <p key={v.id} className="text-xs">
                    {new Date(v.recorded_at).toLocaleString('vi-VN')} · {v.source} · {v.outcome}
                    {v.evidence_url && <> · <a href={v.evidence_url} target="_blank" rel="noopener noreferrer">link</a></>}
                  </p>
                ))}
              </div>
            </div>
          )}

          <div className="text-xs text-slate-500">
            Lịch sử hoạt động ({record.events?.length ?? 0}
            {record.events_truncated ? '+' : ''})
            <div className="mt-1 max-h-40 space-y-1 overflow-auto">
              {record.events?.map((event) => (
                <p key={event.id}>
                  {new Date(event.recorded_at).toLocaleString('vi-VN')} · {event.kind} {event.outcome || ''}
                </p>
              ))}
            </div>
          </div>
        </div>
      </div>
    )}
  </section>;
}
