"use client";

import { useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  KeyRound,
  LockKeyhole,
  LockKeyholeOpen,
  Plus,
  RefreshCw,
  Search,
  Users,
} from "lucide-react";

import {
  CTVManagementError,
  listCTVs,
  updateCTVStatus,
} from "../api/ctv-management";
import type {
  CTVListItem,
  CTVListResponse,
  CTVStatusFilter,
} from "../types/ctv-management";
import CTVAuditLog from "./CTVAuditLog";
import CreateCTVDialog from "./CreateCTVDialog";
import ResetCTVPasswordDialog from "./ResetCTVPasswordDialog";

const PAGE_SIZE = 10;

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return date.toLocaleDateString("vi-VN");
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "Chưa đăng nhập";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return date.toLocaleString("vi-VN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function StatusBadge({
  active,
}: {
  active: boolean;
}) {
  return (
    <span
      className={
        "inline-flex rounded-full px-3 py-1 text-xs font-semibold " +
        (active
          ? "bg-green-50 text-green-700"
          : "bg-red-50 text-red-700")
      }
    >
      {active ? "Hoạt động" : "Đã khóa"}
    </span>
  );
}

function PipelineStatusBadge({
  pipeline,
}: {
  pipeline: CTVListItem["pipeline"];
}) {
  if (!pipeline) {
    return (
      <span className="inline-flex rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
        Chưa có Pipeline
      </span>
    );
  }

  return <StatusBadge active={pipeline.status === "active"} />;
}

export default function CTVManagement() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] =
    useState<CTVStatusFilter>("all");
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);
  const [result, setResult] =
    useState<CTVListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [passwordItem, setPasswordItem] =
    useState<CTVListItem | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setPage(1);
      setSearch(searchInput.trim());
    }, 350);

    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    const controller = new AbortController();

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError("");

    listCTVs(
      {
        page,
        pageSize: PAGE_SIZE,
        search,
        status,
      },
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        setResult(data);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;

        if (
          cause instanceof CTVManagementError &&
          cause.message.includes("Trang không tồn tại") &&
          page > 1
        ) {
          setPage(1);
          return;
        }

        setResult(null);
        setError(
          cause instanceof Error
            ? cause.message
            : "Không thể kết nối API quản lý CTV.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [page, search, status, refreshKey]);

  function refresh() {
    setRefreshKey((value) => value + 1);
  }

  function handleCreated() {
    setCreateOpen(false);
    setFeedback("Đã tạo CTV và Pipeline thành công.");
    setPage(1);
    refresh();
  }

  function handlePasswordReset() {
    setPasswordItem(null);
    setFeedback("Đã đặt lại mật khẩu CTV thành công.");
    refresh();
  }

  async function handleToggleStatus(item: CTVListItem) {
    if (busyId) return;

    if (!item.pipeline) {
      setError(
        `CTV "${item.ctv.username}" chưa có Pipeline nên không thể khóa/mở khóa.`,
      );
      return;
    }

    const isLocked =
      item.pipeline.status !== "active" ||
      !item.ctv.is_active;

    const message = isLocked
      ? `Mở khóa CTV "${item.ctv.username}" và Pipeline "${item.pipeline.name}"?`
      : `Khóa CTV "${item.ctv.username}" và Pipeline "${item.pipeline.name}"? CTV sẽ không thể tiếp tục truy cập Workspace.`;

    if (!window.confirm(message)) return;

    setBusyId(item.id);
    setFeedback("");
    setError("");

    try {
      await updateCTVStatus(
        item.pipeline.id,
        isLocked ? "active" : "disabled",
      );
      setFeedback(
        isLocked
          ? `Đã mở khóa CTV "${item.ctv.username}".`
          : `Đã khóa CTV "${item.ctv.username}".`,
      );
      refresh();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Không thể cập nhật trạng thái CTV.",
      );
    } finally {
      setBusyId(null);
    }
  }

  const items = result?.data ?? [];
  const pagination = result?.pagination;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            Quản lý CTV
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Quản lý tài khoản CTV và Pipeline tương ứng.
          </p>
        </div>

        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-700"
        >
          <Plus size={18} />
          Tạo CTV
        </button>
      </div>

      {feedback && (
        <div
          role="status"
          className="rounded-xl border border-green-200 bg-green-50 p-4 text-sm text-green-800"
        >
          {feedback}
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search
              size={18}
              className="absolute left-3 top-3 text-slate-400"
            />
            <input
              type="search"
              value={searchInput}
              onChange={(event) =>
                setSearchInput(event.target.value)
              }
              placeholder="Tìm Username, Email hoặc Pipeline..."
              aria-label="Tìm kiếm CTV"
              className="w-full rounded-lg border border-slate-200 bg-white py-3 pl-10 pr-3 text-sm text-slate-900 outline-none focus:border-blue-500"
            />
          </div>

          <select
            value={status}
            aria-label="Lọc trạng thái CTV"
            onChange={(event) => {
              setPage(1);
              setStatus(
                event.target.value as CTVStatusFilter,
              );
            }}
            className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700"
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="active">Hoạt động</option>
            <option value="disabled">Đã khóa</option>
          </select>

          <button
            type="button"
            onClick={refresh}
            aria-label="Tải lại danh sách CTV"
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-4 py-3 text-sm text-slate-700 hover:bg-slate-50"
          >
            <RefreshCw size={17} />
            Làm mới
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          {error}
          <button
            type="button"
            onClick={refresh}
            className="ml-3 font-semibold underline"
          >
            Thử lại
          </button>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        {loading ? (
          <div
            role="status"
            className="p-10 text-center text-sm text-slate-500"
          >
            Đang tải danh sách CTV...
          </div>
        ) : !error && items.length === 0 ? (
          <div className="p-12 text-center">
            <Users
              size={28}
              className="mx-auto text-slate-300"
            />
            <p className="mt-3 font-medium text-slate-700">
              Không tìm thấy CTV
            </p>
            <p className="mt-2 text-sm text-slate-400">
              Hãy thử bộ lọc khác hoặc tạo CTV mới.
            </p>
          </div>
        ) : !error ? (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="px-5 py-3.5 font-semibold">
                      CTV
                    </th>
                    <th className="px-5 py-3.5 font-semibold">
                      Pipeline
                    </th>
                    <th className="px-5 py-3.5 font-semibold">
                      Trạng thái CTV
                    </th>
                    <th className="px-5 py-3.5 font-semibold">
                      Trạng thái Pipeline
                    </th>
                    <th className="px-5 py-3.5 font-semibold">
                      Đăng nhập gần nhất
                    </th>
                    <th className="px-5 py-3.5 text-right font-semibold">
                      Thao tác
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.map((item) => {
                    const pipeline = item.pipeline;
                    const pipelineActive = pipeline?.status === "active";
                    const canManage = pipeline !== null;
                    const isLocked =
                      !pipelineActive || !item.ctv.is_active;

                    return (
                      <tr
                        key={item.id}
                        className="transition-colors hover:bg-slate-50/60"
                      >
                        <td className="px-5 py-3.5">
                          <p className="font-semibold text-slate-800">
                            {item.ctv.username}
                          </p>
                          <p className="text-xs text-slate-400">
                            {item.ctv.email}
                          </p>
                        </td>

                        <td className="px-5 py-3.5">
                          {pipeline ? (
                            <>
                              <p className="font-medium text-slate-700">
                                {pipeline.name}
                              </p>
                              <p className="text-xs text-slate-400">
                                Tạo: {formatDate(pipeline.created_at)}
                              </p>
                            </>
                          ) : (
                            <>
                              <p className="font-medium text-amber-700">
                                Chưa có Pipeline
                              </p>
                              <p className="text-xs text-amber-500">
                                Dữ liệu cần kiểm tra
                              </p>
                            </>
                          )}
                        </td>

                        <td className="px-5 py-3.5">
                          <StatusBadge active={item.ctv.is_active} />
                        </td>

                        <td className="px-5 py-3.5">
                          <PipelineStatusBadge pipeline={pipeline} />
                        </td>

                        <td className="whitespace-nowrap px-5 py-3.5 text-slate-500">
                          {formatDateTime(item.ctv.last_login)}
                        </td>

                        <td className="px-5 py-3.5 text-right whitespace-nowrap">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              disabled={!canManage || busyId === item.id}
                              onClick={() =>
                                void handleToggleStatus(item)
                              }
                              title={
                                !canManage
                                  ? "CTV chưa có Pipeline"
                                  : undefined
                              }
                              className={
                                "inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-xs font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed " +
                                (canManage && isLocked
                                  ? "border-green-200 bg-green-50 text-green-700 hover:bg-green-100"
                                  : canManage
                                    ? "border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100"
                                    : "border-slate-200 bg-slate-100 text-slate-400")
                              }
                            >
                              {isLocked ? (
                                <LockKeyholeOpen size={15} />
                              ) : (
                                <LockKeyhole size={15} />
                              )}
                              {busyId === item.id
                                ? "Đang xử lý..."
                                : isLocked
                                  ? "Mở khóa"
                                  : "Khóa"}
                            </button>

                            <button
                              type="button"
                              disabled={!canManage}
                              onClick={() =>
                                canManage && setPasswordItem(item)
                              }
                              title={
                                !canManage
                                  ? "CTV chưa có Pipeline"
                                  : undefined
                              }
                              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <KeyRound size={15} />
                              Đặt lại mật khẩu
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="divide-y divide-slate-100 md:hidden">
              {items.map((item) => {
                const pipeline = item.pipeline;
                const pipelineActive = pipeline?.status === "active";
                const canManage = pipeline !== null;
                const isLocked =
                  !pipelineActive || !item.ctv.is_active;

                return (
                  <article
                    key={item.id}
                    className="space-y-3 p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <h2 className="break-words text-base font-bold text-slate-900">
                          {pipeline?.name ?? "Chưa có Pipeline"}
                        </h2>
                        <p className="mt-0.5 text-xs text-slate-400">
                          {pipeline
                            ? `Tạo: ${formatDate(pipeline.created_at)}`
                            : "Dữ liệu cần kiểm tra"}
                        </p>
                      </div>
                      <PipelineStatusBadge pipeline={pipeline} />
                    </div>

                    <div className="rounded-lg bg-slate-50 p-3 text-sm">
                      <div className="flex items-center gap-2">
                        <span className="text-slate-500">
                          CTV:
                        </span>
                        <span className="font-semibold text-slate-800">
                          {item.ctv.username}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-xs text-slate-400">
                        {item.ctv.email}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <StatusBadge active={item.ctv.is_active} />
                        <span className="text-xs text-slate-500">
                          Đăng nhập gần nhất:{" "}
                          {formatDateTime(item.ctv.last_login)}
                        </span>
                      </div>
                    </div>

                    <div className="flex flex-col gap-2 border-t border-slate-100 pt-3 sm:flex-row">
                      <button
                        type="button"
                        disabled={!canManage || busyId === item.id}
                        onClick={() =>
                          void handleToggleStatus(item)
                        }
                        title={
                          !canManage
                            ? "CTV chưa có Pipeline"
                            : undefined
                        }
                        className={
                          "inline-flex min-h-10 flex-1 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed " +
                          (canManage && isLocked
                            ? "border-green-200 bg-green-50 text-green-700"
                            : canManage
                              ? "border-amber-200 bg-amber-50 text-amber-700"
                              : "border-slate-200 bg-slate-100 text-slate-400")
                        }
                      >
                        {isLocked ? (
                          <LockKeyholeOpen size={16} />
                        ) : (
                          <LockKeyhole size={16} />
                        )}
                        {busyId === item.id
                          ? "Đang xử lý..."
                          : isLocked
                            ? "Mở khóa"
                            : "Khóa"}
                      </button>

                      <button
                        type="button"
                        disabled={!canManage}
                        onClick={() => canManage && setPasswordItem(item)}
                        title={
                          !canManage
                            ? "CTV chưa có Pipeline"
                            : undefined
                        }
                        className="inline-flex min-h-10 flex-1 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <KeyRound size={16} />
                        Đặt lại mật khẩu
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </>
        ) : null}

        {!loading && !error && pagination && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4">
            <p className="text-sm text-slate-500">
              Tổng: {pagination.total} CTV
            </p>

            <div className="flex items-center gap-3">
              <button
                type="button"
                aria-label="Trang trước"
                disabled={!pagination.has_previous}
                onClick={() =>
                  setPage((value) => Math.max(1, value - 1))
                }
                className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
              >
                <ChevronLeft size={18} />
              </button>

              <span className="text-sm text-slate-600">
                {pagination.page} / {pagination.total_pages}
              </span>

              <button
                type="button"
                aria-label="Trang sau"
                disabled={!pagination.has_next}
                onClick={() =>
                  setPage((value) => value + 1)
                }
                className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </div>
        )}
      </div>

      <CTVAuditLog refreshToken={refreshKey} />

      <CreateCTVDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleCreated}
      />

      <ResetCTVPasswordDialog
        item={passwordItem}
        open={passwordItem !== null}
        onClose={() => setPasswordItem(null)}
        onReset={handlePasswordReset}
      />
    </div>
  );
}
