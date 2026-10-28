"use client";
import {
  useEffect,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Search,
  X,
} from "lucide-react";
import {
  createGroup,
  listGroups,
  updateGroup,
  type FacebookGroup,
  type GroupInput,
  type GroupListResult,
} from "../api/groups";
const inputClass =
  "w-full rounded-lg border border-slate-200 bg-white " +
  "px-3 py-3 text-sm text-slate-900 outline-none " +
  "focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
function nameFromUrl(value: string): string {
  try {
    const url = new URL(value);
    const parts = url.pathname.split("/").filter(Boolean);
    const slug = parts[1] || "Facebook Group";
    return decodeURIComponent(slug)
      .replace(/[-_.]+/g, " ")
      .slice(0, 200);
  } catch {
    return "Facebook Group";
  }
}
function GroupCard({
  group,
  busy,
  onToggle,
  onEdit,
}: {
  group: FacebookGroup;
  busy: boolean;
  onToggle: (group: FacebookGroup) => void;
  onEdit: (group: FacebookGroup) => void;
}) {
  return (
    <article className="space-y-4 border-b border-slate-100 p-5 last:border-b-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <h3 className="break-words font-semibold text-slate-900">
            {group.name}
          </h3>
          <p className="break-all text-xs text-slate-500">
            {group.group_url}
          </p>
        </div>
        <span
          className={
            "rounded-full px-3 py-1 text-xs font-medium " +
            (group.is_enabled
              ? "bg-green-50 text-green-700"
              : "bg-slate-100 text-slate-500")
          }
        >
          {group.is_enabled ? "Đang bật" : "Đã tắt"}
        </span>
      </div>
      <p className="text-xs text-amber-700">
        {group.verification_status === "verified"
          ? "Đã xác minh Group"
          : group.verification_status === "unavailable"
            ? "Group không truy cập được"
            : "Chưa xác minh quyền đăng"}
      </p>
      {group.notes && (
        <p className="whitespace-pre-wrap text-sm text-slate-500">
          {group.notes}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => onEdit(group)}
          className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-50"
        >
          <Pencil size={16} />
          Chỉnh sửa
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onToggle(group)}
          className={
            "min-h-10 rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-50 " +
            (group.is_enabled
              ? "border-red-200 bg-red-50 text-red-700"
              : "border-green-200 bg-green-50 text-green-700")
          }
        >
          {group.is_enabled ? "Tắt Group" : "Bật Group"}
        </button>
      </div>
    </article>
  );
}
export default function FacebookGroupsPanel({
  pipelineId,
  backHref = "/pipelines/",
}: {
  pipelineId: string;
  backHref?: string | null;
}) {
  const [urls, setUrls] = useState("");
  const [adding, setAdding] = useState(false);
  const [addMessage, setAddMessage] = useState("");
  const [addErrors, setAddErrors] = useState<string[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [enabled, setEnabled] =
    useState<"all" | "true" | "false">("all");
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [result, setResult] =
    useState<GroupListResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editing, setEditing] =
    useState<FacebookGroup | null>(null);
  const [draft, setDraft] = useState<GroupInput>({
    name: "",
    group_url: "",
    is_enabled: true,
    notes: "",
  });
  function refresh() {
    setReload((value) => value + 1);
  }
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setListError("");
    listGroups(
      pipelineId,
      { page, search, enabled },
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult(data);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setResult(null);
        setListError(
          cause instanceof Error
            ? cause.message
            : "Không thể tải danh sách Group.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [pipelineId, page, search, enabled, reload]);
  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (adding) return;
    const lines = Array.from(
      new Set(
        urls.split(/\r?\n/)
          .map((value) => value.trim())
          .filter(Boolean),
      ),
    );
    if (lines.length === 0) {
      setAddMessage("Vui lòng nhập link Group.");
      return;
    }
    if (lines.length > 50) {
      setAddMessage("Mỗi lần chỉ thêm tối đa 50 Group.");
      return;
    }
    setAdding(true);
    setAddMessage("");
    setAddErrors([]);
    let added = 0;
    const failures: string[] = [];
    const failedUrls: string[] = [];
    for (const url of lines) {
      try {
        await createGroup(pipelineId, {
          name: nameFromUrl(url),
          group_url: url,
          is_enabled: true,
          notes: "",
        });
        added += 1;
      } catch (cause) {
        failedUrls.push(url);
        const message = cause instanceof Error
          ? cause.message
          : "Không thể thêm Group.";
        failures.push(`${url}: ${message}`);
      }
    }
    setAdding(false);
    setAddMessage(
      `Đã thêm ${added}/${lines.length} Group. ` +
      (failures.length
        ? `${failures.length} Group lỗi.`
        : "Hoàn thành."),
    );
    setAddErrors(failures);
    setUrls(failedUrls.join("\n"));
    if (added > 0) {
      setPage(1);
      setSearch("");
      setSearchInput("");
      setEnabled("all");
      refresh();
    }
  }
  async function toggleGroup(group: FacebookGroup) {
    if (busyId) return;
    setBusyId(group.id);
    setActionError("");
    try {
      await updateGroup(
        pipelineId,
        group.id,
        { is_enabled: !group.is_enabled },
      );
      refresh();
    } catch (cause) {
      setActionError(
        cause instanceof Error
          ? cause.message
          : "Không thể cập nhật Group.",
      );
    } finally {
      setBusyId(null);
    }
  }
  function startEdit(group: FacebookGroup) {
    setEditing(group);
    setActionError("");
    setDraft({
      name: group.name,
      group_url: group.group_url,
      is_enabled: group.is_enabled,
      notes: group.notes,
    });
  }
  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing || busyId) return;
    setBusyId(editing.id);
    setActionError("");
    try {
      await updateGroup(pipelineId, editing.id, draft);
      setEditing(null);
      refresh();
    } catch (cause) {
      setActionError(
        cause instanceof Error
          ? cause.message
          : "Không thể lưu Group.",
      );
    } finally {
      setBusyId(null);
    }
  }
  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  }
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        {backHref && (
          <Link
            href={backHref}
            className="inline-flex items-center gap-2 text-sm text-slate-500"
          >
            <ArrowLeft size={17} />
            Quay lại danh sách Pipeline
          </Link>
        )}
        <h2 className="text-2xl font-bold text-slate-900">
          Facebook Groups
        </h2>
        <p className="text-sm text-slate-500">
          Danh sách Group đích của Pipeline hiện tại.
        </p>
      </header>
      <form
        onSubmit={handleAdd}
        className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <div>
          <h3 className="text-lg font-semibold text-slate-900">
            Thêm Facebook Groups
          </h3>
          <p className="mt-1 text-sm text-slate-500">
            Mỗi dòng một link Group, tối đa 50 link/lần.
          </p>
        </div>
        <textarea
          value={urls}
          onChange={(event) => setUrls(event.target.value)}
          disabled={adding}
          required
          rows={6}
          placeholder={
            "https://www.facebook.com/groups/vietnambusinessnews/\n" +
            "https://www.facebook.com/groups/423059985272689/"
          }
          className={`${inputClass} resize-y`}
        />
        {addMessage && (
          <p role="status" className="text-sm text-slate-700">
            {addMessage}
          </p>
        )}
        {addErrors.length > 0 && (
          <div
            role="alert"
            className="max-h-48 space-y-1 overflow-auto rounded-lg bg-amber-50 p-3 text-xs text-amber-800"
          >
            {addErrors.map((message, index) => (
              <p key={index} className="break-all">
                {message}
              </p>
            ))}
          </div>
        )}
        <button
          type="submit"
          disabled={adding || !urls.trim()}
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50 sm:w-auto"
        >
          {adding ? (
            <LoaderCircle
              size={18}
              className="animate-spin"
            />
          ) : (
            <Plus size={18} />
          )}
          {adding ? "Đang thêm Group..." : "Thêm Group"}
        </button>
      </form>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-lg font-semibold text-slate-900">
            Danh sách Group
          </h3>
          <span className="text-sm text-slate-500">
            {result?.pagination.total ?? 0} Group
          </span>
        </div>
        <form
          onSubmit={handleSearch}
          className="flex flex-wrap gap-2"
        >
          <div className="relative min-w-0 flex-1">
            <Search
              size={17}
              className="absolute left-3 top-3 text-slate-400"
            />
            <input
              value={searchInput}
              onChange={(event) =>
                setSearchInput(event.target.value)
              }
              placeholder="Tìm Group..."
              className={`${inputClass} pl-10`}
            />
          </div>
          <button
            type="submit"
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm"
          >
            Tìm
          </button>
          <button
            type="button"
            onClick={refresh}
            aria-label="Làm mới Group"
            className="rounded-lg border border-slate-200 bg-white p-3"
          >
            <RefreshCw size={17} />
          </button>
        </form>
        <select
          value={enabled}
          onChange={(event) => {
            setEnabled(
              event.target.value as "all" | "true" | "false",
            );
            setPage(1);
          }}
          className={inputClass}
          aria-label="Lọc trạng thái Group"
        >
          <option value="all">Tất cả Group</option>
          <option value="true">Group đang bật</option>
          <option value="false">Group đã tắt</option>
        </select>
        {listError && (
          <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
            {listError}
          </p>
        )}
        {actionError && (
          <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
            {actionError}
          </p>
        )}
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          {loading ? (
            <p role="status" className="p-8 text-center text-sm text-slate-500">
              Đang tải Group...
            </p>
          ) : !listError && result?.data.length === 0 ? (
            <p className="p-8 text-center text-sm text-slate-500">
              Chưa có Group phù hợp.
            </p>
          ) : !listError ? (
            result?.data.map((group) => (
              <GroupCard
                key={group.id}
                group={group}
                busy={busyId !== null}
                onToggle={toggleGroup}
                onEdit={startEdit}
              />
            ))
          ) : null}
          {result && result.pagination.total_pages > 1 && (
            <div className="flex items-center justify-between border-t border-slate-100 p-4">
              <button
                type="button"
                disabled={!result.pagination.has_previous || loading}
                onClick={() =>
                  setPage((value) => Math.max(1, value - 1))
                }
                className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
              >
                <ChevronLeft size={18} />
              </button>
              <span className="text-sm text-slate-600">
                {result.pagination.page} / {result.pagination.total_pages}
              </span>
              <button
                type="button"
                disabled={!result.pagination.has_next || loading}
                onClick={() =>
                  setPage((value) => value + 1)
                }
                className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          )}
        </div>
      </div>
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-950/60 p-4">
          <form
            onSubmit={saveEdit}
            className="my-auto w-full max-w-lg space-y-4 rounded-2xl bg-white p-5 shadow-xl"
          >
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-lg font-bold text-slate-900">
                Chỉnh sửa Facebook Group
              </h3>
              <button
                type="button"
                disabled={busyId !== null}
                onClick={() => {
                  setEditing(null);
                  setActionError("");
                }}
                aria-label="Đóng"
                className="rounded-lg p-2"
              >
                <X size={20} />
              </button>
            </div>
            <label className="block space-y-2">
              <span className="text-sm font-medium">Tên Group</span>
              <input
                value={draft.name}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    name: event.target.value,
                  })
                }
                maxLength={200}
                required
                className={inputClass}
              />
            </label>
            <label className="block space-y-2">
              <span className="text-sm font-medium">URL Group</span>
              <input
                value={draft.group_url}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    group_url: event.target.value,
                  })
                }
                required
                className={inputClass}
              />
            </label>
            <label className="block space-y-2">
              <span className="text-sm font-medium">Ghi chú</span>
              <textarea
                value={draft.notes}
                maxLength={5000}
                rows={3}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    notes: event.target.value,
                  })
                }
                className={inputClass}
              />
            </label>
            <label className="flex items-center gap-3 text-sm">
              <input
                type="checkbox"
                checked={draft.is_enabled}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    is_enabled: event.target.checked,
                  })
                }
              />
              Bật Group làm đích đăng bài
            </label>
            {actionError && (
              <p role="alert" className="text-sm text-red-600">
                {actionError}
              </p>
            )}
            <button
              type="submit"
              disabled={busyId !== null}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
            >
              {busyId ? (
                <LoaderCircle
                  size={18}
                  className="animate-spin"
                />
              ) : (
                <Save size={18} />
              )}
              Lưu thay đổi
            </button>
          </form>
        </div>
      )}
    </section>
  );
}
