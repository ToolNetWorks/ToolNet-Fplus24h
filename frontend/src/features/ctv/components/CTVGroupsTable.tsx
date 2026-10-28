"use client";
import { useEffect, useState, type FormEvent } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import {
  bulkUpdateGroupStatus,
  createGroup,
  listGroups,
  updateGroup,
  type FacebookGroup,
  type GroupInput,
  type GroupListResult,
} from "@/features/facebook-groups/api/groups";
type EnabledFilter = "all" | "true" | "false";
type VerifyFilter = "all" | "unknown" | "verified" | "unavailable";
const inputClass =
  "w-full rounded-md border border-slate-200 bg-white " +
  "px-3 py-2.5 text-xs text-slate-800 outline-none " +
  "focus:border-blue-500";
const verificationLabels: Record<string, string> = {
  verified: "Đã xác minh",
  unknown: "Chưa xác minh",
  unavailable: "Không truy cập được",
};
function toError(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Không thể xử lý yêu cầu.";
}
function groupNameFromUrl(value: string): string {
  try {
    const parsed = new URL(value);
    const parts = parsed.pathname.split("/").filter(Boolean);
    const identifier = parts[1] ?? "";
    return (
      decodeURIComponent(identifier)
        .replace(/[-_.]+/g, " ")
        .trim()
        .slice(0, 200) || "Facebook Group"
    );
  } catch {
    return "Facebook Group";
  }
}
export default function CTVGroupsTable({
  pipelineId,
}: {
  pipelineId: string;
}) {
  const [result, setResult] = useState<GroupListResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [enabled, setEnabled] = useState<EnabledFilter>("all");
  const [verification, setVerification] =
    useState<VerifyFilter>("all");
  const [revision, setRevision] = useState(0);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [urls, setUrls] = useState("");
  const [adding, setAdding] = useState(false);
  const [addErrors, setAddErrors] = useState<string[]>([]);
  const [editing, setEditing] = useState<FacebookGroup | null>(null);
  const [draft, setDraft] = useState<GroupInput>({
    name: "",
    group_url: "",
    is_enabled: true,
    notes: "",
  });
  const busy = adding || bulkBusy || busyId !== null;
  const items = result?.data ?? [];
  const pagination = result?.pagination;
  const summary = result?.summary;
  const allSelected =
    items.length > 0 &&
    items.every((item) => selectedIds.includes(item.id));
  function refresh() {
    setRevision((value) => value + 1);
  }
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setListError("");
    listGroups(
      pipelineId,
      {
        page,
        pageSize,
        search,
        enabled,
        verificationStatus: verification,
      },
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult(data);
        setSelectedIds([]);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setResult(null);
        setSelectedIds([]);
        setListError(toError(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [pipelineId, page, pageSize, search, enabled, verification, revision]);
  function toggleOne(id: string, checked: boolean) {
    setSelectedIds((current) =>
      checked
        ? Array.from(new Set([...current, id]))
        : current.filter((value) => value !== id),
    );
  }
  function toggleAll(checked: boolean) {
    setSelectedIds(checked ? items.map((item) => item.id) : []);
  }
  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
    setSelectedIds([]);
  }
  async function handleBulkUpdate(isEnabled: boolean) {
    if (busy || selectedIds.length === 0) return;
    const confirmed = window.confirm(
      `${isEnabled ? "Bật" : "Tắt"} ${selectedIds.length} Group đã chọn?`
    );
    if (!confirmed) return;
    setBulkBusy(true);
    setActionError("");
    setNotice("");
    try {
      const data = await bulkUpdateGroupStatus(
        pipelineId,
        selectedIds,
        isEnabled,
      );
      setNotice(
        `Đã xử lý ${data.selected_count} Group; ` +
        `${data.updated_count} Group thay đổi trạng thái.`
      );
      setSelectedIds([]);
      refresh();
    } catch (cause) {
      setActionError(toError(cause));
      refresh();
    } finally {
      setBulkBusy(false);
    }
  }
  async function handleToggle(group: FacebookGroup) {
    if (busy) return;
    setBusyId(group.id);
    setActionError("");
    setNotice("");
    try {
      await updateGroup(pipelineId, group.id, {
        is_enabled: !group.is_enabled,
      });
      setNotice("Đã cập nhật trạng thái Group.");
      refresh();
    } catch (cause) {
      setActionError(toError(cause));
    } finally {
      setBusyId(null);
    }
  }
  function openEdit(group: FacebookGroup) {
    setEditing(group);
    setActionError("");
    setDraft({
      name: group.name,
      group_url: group.group_url,
      notes: group.notes,
      is_enabled: group.is_enabled,
    });
  }
  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing || busy) return;
    setBusyId(editing.id);
    setActionError("");
    setNotice("");
    try {
      await updateGroup(pipelineId, editing.id, draft);
      setEditing(null);
      setNotice("Đã lưu thay đổi Group.");
      refresh();
    } catch (cause) {
      setActionError(toError(cause));
    } finally {
      setBusyId(null);
    }
  }
  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const lines = Array.from(
      new Set(
        urls.split(/\r?\n/)
          .map((value) => value.trim())
          .filter(Boolean),
      ),
    );
    if (lines.length === 0 || lines.length > 50) {
      setActionError("Mỗi lần thêm từ 1 đến 50 link Group.");
      return;
    }
    setAdding(true);
    setActionError("");
    setNotice("");
    setAddErrors([]);
    let added = 0;
    const errors: string[] = [];
    const failedLinks: string[] = [];
    for (const link of lines) {
      try {
        await createGroup(pipelineId, {
          name: groupNameFromUrl(link),
          group_url: link,
          is_enabled: true,
          notes: "",
        });
        added += 1;
      } catch (cause) {
        failedLinks.push(link);
        errors.push(`${link}: ${toError(cause)}`);
      }
    }
    setAdding(false);
    setAddErrors(errors);
    setUrls(failedLinks.join("\n"));
    setNotice(
      `Đã thêm ${added}/${lines.length} Group.` +
      (errors.length ? " Các link lỗi được giữ lại." : "")
    );
    if (added === 0) return;
    setPage(1);
    setSearch("");
    setSearchInput("");
    setEnabled("all");
    setVerification("all");
    setSelectedIds([]);
    refresh();
    if (errors.length === 0) {
      setShowAdd(false);
    }
  }
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            Quản lý Facebook Groups
          </h1>
          <p className="mt-1 text-xs text-slate-500">
            Danh sách Group đích của Pipeline hiện tại.
          </p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => setShowAdd((value) => !value)}
          className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50"
        >
          {showAdd ? <X size={16} /> : <Plus size={16} />}
          {showAdd ? "Đóng" : "Thêm Group"}
        </button>
      </div>
      {notice && (
        <p role="status" className="rounded-md bg-blue-50 p-3 text-xs text-blue-800">
          {notice}
        </p>
      )}
      {actionError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">
          {actionError}
        </p>
      )}
      {showAdd && (
        <form
          onSubmit={handleAdd}
          className="space-y-3 rounded-lg border border-slate-200 bg-white p-4"
        >
          <h2 className="text-sm font-semibold">
            Nhập link Facebook Group
          </h2>
          <p className="text-xs text-slate-500">
            Mỗi dòng một URL, tối đa 50 Group mỗi lần.
          </p>
          <textarea
            value={urls}
            onChange={(event) => setUrls(event.target.value)}
            disabled={adding}
            required
            rows={5}
            className={`${inputClass} resize-y`}
            placeholder={
              "https://www.facebook.com/groups/vietnambusinessnews/\n" +
              "https://www.facebook.com/groups/vietnamlinuxcommunity/"
            }
          />
          {addErrors.length > 0 && (
            <div
              role="alert"
              className="max-h-44 space-y-1 overflow-y-auto rounded-md bg-amber-50 p-3 text-xs text-amber-800"
            >
              {addErrors.map((err, index) => (
                <p key={index} className="break-all">{err}</p>
              ))}
            </div>
          )}
          <button
            type="submit"
            disabled={adding || !urls.trim()}
            className="rounded-md bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50"
          >
            {adding ? "Đang thêm Group..." : "Thêm vào Pipeline"}
          </button>
        </form>
      )}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap gap-x-5 gap-y-2 border-b border-slate-100 p-4 text-xs">
          <span>
            Tổng: <strong>{summary?.total ?? "—"}</strong>
          </span>
          <span className="text-green-700">
            Đang bật: <strong>{summary?.enabled ?? "—"}</strong>
          </span>
          <span className="text-slate-500">
            Đã tắt: <strong>{summary?.disabled ?? "—"}</strong>
          </span>
          <span className="text-blue-700">
            Đã xác minh: <strong>{summary?.verified ?? "—"}</strong>
          </span>
          <span className="font-semibold text-blue-700">
            Đã chọn trên trang: {selectedIds.length}
          </span>
        </div>
        <div className="flex flex-wrap gap-2 border-b border-slate-100 p-3">
          <form
            onSubmit={handleSearch}
            className="flex min-w-[190px] flex-1 gap-2"
          >
            <div className="relative min-w-0 flex-1">
              <Search
                size={15}
                className="absolute left-3 top-3 text-slate-400"
              />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Tìm Group theo tên, link..."
                maxLength={100}
                className={`${inputClass} pl-9`}
              />
            </div>
            <button
              type="submit"
              className="rounded-md border border-slate-200 px-3 text-xs"
            >
              Tìm
            </button>
          </form>
          <select
            value={enabled}
            aria-label="Lọc Group bật tắt"
            onChange={(event) => {
              setEnabled(event.target.value as EnabledFilter);
              setPage(1);
              setSelectedIds([]);
            }}
            className={`${inputClass} w-auto`}
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="true">Đang bật</option>
            <option value="false">Đã tắt</option>
          </select>
          <select
            value={verification}
            aria-label="Lọc xác minh Group"
            onChange={(event) => {
              setVerification(event.target.value as VerifyFilter);
              setPage(1);
              setSelectedIds([]);
            }}
            className={`${inputClass} w-auto`}
          >
            <option value="all">Tất cả xác minh</option>
            <option value="verified">Đã xác minh</option>
            <option value="unknown">Chưa xác minh</option>
            <option value="unavailable">Không truy cập được</option>
          </select>
          <select
            value={pageSize}
            aria-label="Số Group mỗi trang"
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setPage(1);
              setSelectedIds([]);
            }}
            className={`${inputClass} w-auto`}
          >
            <option value={10}>10 dòng</option>
            <option value={25}>25 dòng</option>
            <option value={50}>50 dòng</option>
          </select>
          <button
            type="button"
            onClick={refresh}
            disabled={busy}
            aria-label="Làm mới danh sách Group"
            className="rounded-md border border-slate-200 p-2 disabled:opacity-50"
          >
            <RefreshCw size={16} />
          </button>
        </div>
        {selectedIds.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-blue-100 bg-blue-50/50 p-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => void handleBulkUpdate(true)}
              className="rounded-md border border-green-200 bg-white px-3 py-2 text-xs font-semibold text-green-700 disabled:opacity-40"
            >
              Bật {selectedIds.length} Group
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void handleBulkUpdate(false)}
              className="rounded-md border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-700 disabled:opacity-40"
            >
              Tắt {selectedIds.length} Group
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setSelectedIds([])}
              className="px-3 py-2 text-xs text-slate-600"
            >
              Bỏ chọn
            </button>
          </div>
        )}
        {listError && (
          <p role="alert" className="m-3 rounded-md bg-red-50 p-3 text-xs text-red-700">
            {listError}
          </p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] text-left text-xs">
            <thead className="bg-slate-50 text-slate-600">
              <tr className="border-b border-slate-200">
                <th className="w-10 px-3 py-3">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    disabled={loading || busy || items.length === 0}
                    onChange={(event) => toggleAll(event.target.checked)}
                    aria-label="Chọn tất cả Group trên trang"
                    className="size-4 accent-blue-600"
                  />
                </th>
                <th className="px-3 py-3">STT</th>
                <th className="px-3 py-3">Tên Group</th>
                <th className="px-3 py-3">Group ID / Slug</th>
                <th className="px-3 py-3">Trạng thái</th>
                <th className="px-3 py-3">Xác minh</th>
                <th className="px-3 py-3">Ghi chú</th>
                <th className="px-3 py-3">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={8} className="p-10 text-center text-slate-500">
                    Đang tải Facebook Groups...
                  </td>
                </tr>
              ) : listError ? null : items.length === 0 ? (
                <tr>
                  <td colSpan={8} className="p-10 text-center text-slate-500">
                    Chưa có Group phù hợp.
                  </td>
                </tr>
              ) : (
                items.map((group, index) => (
                  <tr
                    key={group.id}
                    className={
                      selectedIds.includes(group.id)
                        ? "bg-blue-50"
                        : "hover:bg-slate-50"
                    }
                  >
                    <td className="px-3 py-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(group.id)}
                        disabled={busy}
                        onChange={(event) =>
                          toggleOne(group.id, event.target.checked)
                        }
                        aria-label={`Chọn Group ${group.name}`}
                        className="size-4 accent-blue-600"
                      />
                    </td>
                    <td className="px-3 py-3 text-slate-500">
                      {(page - 1) * pageSize + index + 1}
                    </td>
                    <td className="px-3 py-3">
                      <p className="max-w-52 truncate font-semibold text-slate-800">
                        {group.name}
                      </p>
                      <a
                        href={group.group_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-1 inline-flex items-center gap-1 text-blue-600 hover:underline"
                      >
                        Mở Facebook
                        <ExternalLink size={12} />
                      </a>
                    </td>
                    <td className="max-w-48 break-all px-3 py-3 font-mono text-slate-600">
                      {group.group_key}
                    </td>
                    <td className="px-3 py-3">
                      <span
                        className={
                          "rounded-full px-3 py-1 text-[11px] font-semibold " +
                          (group.is_enabled
                            ? "bg-green-50 text-green-700"
                            : "bg-slate-100 text-slate-600")
                        }
                      >
                        {group.is_enabled ? "Đang bật" : "Đã tắt"}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <span
                        className={
                          group.verification_status === "verified"
                            ? "text-green-700"
                            : group.verification_status === "unavailable"
                              ? "text-red-700"
                              : "text-amber-700"
                        }
                      >
                        {verificationLabels[group.verification_status] ??
                          group.verification_status}
                      </span>
                    </td>
                    <td
                      title={group.notes}
                      className="max-w-44 truncate px-3 py-3 text-slate-500"
                    >
                      {group.notes || "—"}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => openEdit(group)}
                          className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-3 py-2 disabled:opacity-40"
                        >
                          <Pencil size={13} />
                          Sửa
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleToggle(group)}
                          className={
                            "rounded-md border px-3 py-2 font-semibold disabled:opacity-40 " +
                            (group.is_enabled
                              ? "border-red-200 text-red-700"
                              : "border-green-200 text-green-700")
                          }
                        >
                          {group.is_enabled ? "Tắt" : "Bật"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-slate-100 p-4 text-xs text-slate-500">
          <span>
            {pagination?.total ?? "—"} Group phù hợp
          </span>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={!pagination?.has_previous || busy || loading}
              aria-label="Trang trước"
              onClick={() => setPage((value) => Math.max(1, value - 1))}
              className="rounded-md border border-slate-200 p-2 disabled:opacity-30"
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              {pagination
                ? `${pagination.page}/${pagination.total_pages}`
                : "—"}
            </span>
            <button
              type="button"
              disabled={!pagination?.has_next || busy || loading}
              aria-label="Trang sau"
              onClick={() => setPage((value) => value + 1)}
              className="rounded-md border border-slate-200 p-2 disabled:opacity-30"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>
      <p className="text-xs text-slate-500">
        Trạng thái xác minh là dữ liệu đang lưu trong hệ thống,
        không phải kết quả kiểm tra Facebook trực tiếp.
        Bật Group không đồng nghĩa với quyền đăng bài đã được xác minh.
      </p>
      {editing && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-3">
          <form
            onSubmit={saveEdit}
            aria-label="Chỉnh sửa Group"
            className="max-h-[90dvh] w-full max-w-lg space-y-4 overflow-y-auto rounded-xl bg-white p-5 shadow-xl"
          >
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-bold">
                Chỉnh sửa Facebook Group
              </h2>
              <button
                type="button"
                disabled={busy}
                onClick={() => setEditing(null)}
                aria-label="Đóng"
                className="rounded-md border border-slate-200 p-2"
              >
                <X size={18} />
              </button>
            </div>
            <label className="block space-y-1">
              <span className="text-xs font-medium">Tên Group</span>
              <input
                required
                maxLength={200}
                value={draft.name}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                className={inputClass}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium">URL Facebook Group</span>
              <input
                required
                type="url"
                maxLength={500}
                value={draft.group_url}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    group_url: event.target.value,
                  }))
                }
                className={inputClass}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium">Ghi chú</span>
              <textarea
                maxLength={5000}
                rows={3}
                value={draft.notes}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    notes: event.target.value,
                  }))
                }
                className={inputClass}
              />
            </label>
            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={draft.is_enabled}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    is_enabled: event.target.checked,
                  }))
                }
                className="size-4 accent-blue-600"
              />
              Bật Group làm đích đăng bài
            </label>
            {actionError && (
              <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">
                {actionError}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => setEditing(null)}
                className="rounded-md border border-slate-200 px-4 py-2 text-xs"
              >
                Hủy
              </button>
              <button
                type="submit"
                disabled={busy}
                className="rounded-md bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
              >
                {busy ? "Đang lưu..." : "Lưu thay đổi"}
              </button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}